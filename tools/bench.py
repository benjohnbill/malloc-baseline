#!/usr/bin/env python3
"""baseline 의 처리량을 이 머신에서 재고, 선택적으로 내 코드와 비교한다.

  tools/bench.sh                    baseline 만 N회 측정 (이 머신의 눈금을 얻는다)
  tools/bench.sh 내_mm.c            baseline 과 내 코드를 번갈아 N회씩 측정하고 비교한다
  옵션: --runs N (기본 10)   --b-ref KOPS (기준값을 바꿔 보고 싶을 때)

번갈아 재는 이유: 노트북의 발열이나 부스트 때문에 머신 속도가 도중에 바뀌어도, 두 코드가 같은 영향을
받게 하려는 것이다. 비율(내 코드 ÷ baseline)이 이 도구의 핵심 수치다.

필요한 것: python3, make, gcc (또는 clang). 이 repo 의 파일은 건드리지 않고 임시 디렉토리에서 빌드한다.
"""
import argparse
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAB = ROOT / "malloc-lab"

# ---------------------------------------------------------------- 기준값 (팀 공통 눈금)
# 기준 머신에서 baseline 을 10회 측정한 처리량의 중앙값. 한 번 정하면 바꾸지 않는다.
# 기준 머신: Intel Core Ultra 7 155H, WSL2 (Linux 6.18), gcc 15.2.0. 2026-10-02, tools/bench.sh --runs 10
# 10회: 중앙값 160.2, 최소 149.3, 최대 165.8 Kops/s (흔들림 10.3%)
B_REF_KOPS = 160.2
BASELINE_UTIL = 74          # baseline 의 평균 utilization(%). 코드와 trace 가 같으면 어느 머신에서나 같다.
# mdriver 의 점수식 상수 (malloc-lab/config.h): UTIL_WEIGHT .60, AVG_LIBC_THRUPUT 600E3
UTIL_WEIGHT = 0.60
CAP_KOPS = 600.0

ROW = re.compile(r"^\s*(\d+)\s+(yes|no)\s+(\d+)%\s+(\d+)\s+(\d+\.\d{6})\s*(\d+)\s*$")
BADROW = re.compile(r"^\s*(\d+)\s+no\b")
TOTAL = re.compile(r"^Total\s+(\d+)%\s+(\d+)\s+(\d+\.\d{6})\s*(\d+)\s*$")  # secs 와 Kops 가 붙어 나올 수 있어서 \s*


def run_out(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return r.stdout.strip()


def machine():
    sysname = platform.system()
    rel = platform.release()
    env = "Linux 네이티브"
    if sysname == "Darwin":
        env = "macOS"
    elif Path("/.dockerenv").exists():
        env = "Docker"
    elif "microsoft" in rel.lower():
        env = "WSL"
    cpu = ""
    if sysname == "Darwin":
        cpu = run_out(["sysctl", "-n", "machdep.cpu.brand_string"])
    else:
        try:
            for line in Path("/proc/cpuinfo").read_text().split("\n"):
                if line.lower().startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
        if not cpu and shutil.which("lscpu"):
            for line in run_out(["lscpu"]).split("\n"):
                if line.startswith("Model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    cc = run_out(["gcc", "--version"]).split("\n")[0] if shutil.which("gcc") else "gcc 없음"
    try:
        load = f"{os.getloadavg()[0]:.2f}"
    except OSError:
        load = "?"
    return {
        "환경": env,
        "OS": f"{sysname} {rel} {platform.machine()}",
        "CPU": cpu or platform.processor() or "?",
        "코어": str(os.cpu_count()),
        "cc": cc,
        "load(시작)": load,
    }


def build(mm_c, tag):
    """LAB 의 소스를 임시 디렉토리에 복사하고, mm.c 만 mm_c 로 바꿔 빌드한다. 빌드 디렉토리를 돌려준다."""
    d = Path(tempfile.mkdtemp(prefix=f"bench-{tag}-"))
    for p in list(LAB.glob("*.c")) + list(LAB.glob("*.h")) + [LAB / "Makefile"]:
        shutil.copy(p, d / p.name)
    shutil.copy(mm_c, d / "mm.c")
    (d / "traces").symlink_to(LAB / "traces")
    # stderr 를 stdout 에 합쳐야 컴파일러 오류가 make 의 출력 순서 그대로 남는다.
    r = subprocess.run(["make", "-C", str(d)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        shutil.rmtree(d, ignore_errors=True)
        print(f"\n빌드 실패 ({tag}: {mm_c}):")
        print("\n".join(r.stdout.strip().split("\n")[-15:]))
        sys.exit(2)
    return d


def run_once(d):
    """mdriver -v 를 한 번 돌려 결과를 dict 로 돌려준다."""
    try:
        r = subprocess.run(["./mdriver", "-v"], cwd=d, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"valid": False, "why": "600초 안에 끝나지 않음 (무한 루프 의심)"}
    out = r.stdout + r.stderr
    errs = [l.strip() for l in out.split("\n") if l.startswith("ERROR") or l.startswith("Terminated")]
    bad_rows = [l.split()[0] for l in out.split("\n") if BADROW.match(l)]
    perf = next((l for l in out.split("\n") if l.startswith("Perf index")), None)
    tot = next((m for m in (TOTAL.match(l) for l in out.split("\n")) if m), None)
    if errs or bad_rows or perf is None or tot is None:
        return {"valid": False, "why": "; ".join(errs[:3]) or "결과 줄을 읽지 못함", "bad": bad_rows}
    util, ops, secs = int(tot.group(1)), int(tot.group(2)), float(tot.group(3))
    return {"valid": True, "util": util, "kops": ops / secs / 1000.0, "perf": perf}


def summarize(runs):
    kops = [r["kops"] for r in runs]
    med = statistics.median(kops)
    spread = (max(kops) - min(kops)) / med * 100
    rep = min(runs, key=lambda r: abs(r["kops"] - med))   # 중앙값에 가장 가까운 회차
    return {
        "med": med, "min": min(kops), "max": max(kops), "spread": spread,
        "util_same": len({r["util"] for r in runs}) == 1, "util": runs[0]["util"],
        "perf": rep["perf"], "n": len(runs),
    }


def show_stats(label, s):
    print(f"[{label}]  {s['n']}회")
    print(f"  처리량 Kops/s : 중앙값 {s['med']:.1f}  (최소 {s['min']:.1f} ~ 최대 {s['max']:.1f}, 흔들림 {s['spread']:.1f}%)")
    print(f"  util          : {s['util']}%  ({'모든 회차에서 같음' if s['util_same'] else '⚠ 회차마다 다름'})")
    print(f"  mdriver 출력  : {s['perf']}   <- 중앙값에 가장 가까운 회차")
    if s["spread"] > 15:
        print("  ⚠ 흔들림이 커요. 다른 프로그램을 닫고 다시 재면 더 믿을 수 있어요.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mm_c", nargs="?", type=Path, help="비교할 내 mm.c (생략하면 baseline 만 잰다)")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--b-ref", type=float, default=B_REF_KOPS, help=f"기준값 Kops/s (기본 {B_REF_KOPS})")
    a = ap.parse_args()
    if a.runs < 1:
        sys.exit("--runs 는 1 이상이어야 한다")
    if a.mm_c is not None and not a.mm_c.is_file():
        sys.exit(f"파일이 없다: {a.mm_c}")

    print("== 머신 ==")
    for k, v in machine().items():
        print(f"  {k:<10}: {v}")
    print()

    base_dir = mine_dir = None
    try:
        base_dir = build(LAB / "mm.c", "baseline")
        mine_dir = build(a.mm_c, "mine") if a.mm_c else None
        measure_and_report(a, base_dir, mine_dir)
    finally:
        for d in (base_dir, mine_dir):
            if d is not None:
                shutil.rmtree(d, ignore_errors=True)


def measure_and_report(a, base_dir, mine_dir):
    plan = f"{a.runs}회" + ("씩 번갈아" if a.mm_c else "")
    print(f"측정 중... ({plan}, 한 번에 약 10초)", flush=True)

    base, mine = [], []
    for i in range(a.runs):
        order = [("b", base_dir, base)] + ([("m", mine_dir, mine)] if mine_dir else [])
        if i % 2 == 1:
            order.reverse()
        for _, d, acc in order:
            r = run_once(d)
            if not r["valid"]:
                if d is base_dir:
                    sys.exit(f"baseline 이 이 머신에서 무효다: {r['why']}  (환경 문제일 수 있어요)")
                print("\n❌ 내 코드가 무효예요. 점수가 없어요.")
                print(f"   이유: {r['why']}")
                if r.get("bad"):
                    print(f"   틀린 trace 번호: {', '.join(r['bad'])}")
                sys.exit(1)
            acc.append(r)
        print(".", end="", flush=True)
    print("\n")

    sb = summarize(base)
    show_stats("baseline", sb)
    if sb["util"] != BASELINE_UTIL:
        print(f"  ⚠ baseline 의 util 이 기준({BASELINE_UTIL}%)과 달라요. 코드나 trace 가 바뀌었을 수 있어요.")
    factor = sb["med"] / a.b_ref
    print(f"  머신 계수     : {factor:.2f}  (= 이 머신 baseline ÷ 기준 {a.b_ref:g}. 1보다 작으면 기준 머신보다 느려요)")

    if not mine_dir:
        print()
        print("baseline 만 쟀어요. 내 코드와 비교하려면: tools/bench.sh 내_mm.c")
        return

    print()
    sm = summarize(mine)
    show_stats("내 코드", sm)
    r = sm["med"] / sb["med"]
    thr = (1 - UTIL_WEIGHT) * 100 * min(1.0, r * a.b_ref / CAP_KOPS)
    utl = UTIL_WEIGHT * sm["util"]
    est = utl + thr
    sat = r * a.b_ref >= CAP_KOPS
    print()
    print("[비교]")
    print(f"  비율 r = 내 코드 ÷ baseline = {r:.2f}  (같은 머신에서 번갈아 잰 값이라 머신 속도가 상쇄돼요)")
    print(f"  환산 추정(근사) = {UTIL_WEIGHT * 100:.0f} × util {sm['util']}% + {(1 - UTIL_WEIGHT) * 100:.0f} × min(1, r × 기준 {a.b_ref:g} ÷ {CAP_KOPS:g})")
    print(f"                  = {utl:.1f} + {thr:.1f} = {est:.1f} / 100")
    if sat:
        print(f"  처리량 점수가 만점(40)에서 포화됐어요. 이 위로는 속도를 올려도 점수가 오르지 않고, util 만 점수를 올려요.")
        print(f"  (포화 지점: r ≥ {CAP_KOPS / a.b_ref:.2f})")
    print("  ※ 환산 점수는 팀 안의 공통 눈금이에요. 채점 머신의 점수를 예측하지 않고, 처리량 항은 근사예요.")


if __name__ == "__main__":
    main()
