#!/usr/bin/env python3
"""malloc-lab/mm.c 의 출처 표시를 기계로 검사한다. (관리하는 사람용, 팀원은 몰라도 된다)

  python3 tools/audit.py book --pdf CSAPP.pdf   @BOOK / @BOOK-FIX 구간이 책과 같은지 검사
  python3 tools/audit.py added                  @ADDED 구간이 하나씩 빠질 수 없는지 검사

book  : 구간의 모든 공백을 지운 문자열이, PDF 해당 그림(해답)의 코드와 같아야 통과한다.
        주석 문구는 비교하고, 책의 줄 번호는 제외한다. PDF 는 repo 에 없고 인자로 받는다.
        필요한 것: pdftotext (poppler).
added : @ADDED 구간을 하나씩 지우고 빌드해서, 매번 실패해야 통과한다.
        실패하면 그 추가는 빠질 수 없다는 증거다. 첫 오류 줄을 같이 보여 준다.
        필요한 것: make, gcc 와 mdriver 를 빌드할 수 있는 환경.

종료 코드: 모두 통과하면 0, 하나라도 어긋나면 1.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAB = ROOT / "malloc-lab"
MM = LAB / "mm.c"

# 구간 표시는 독립된 한 줄의 주석이다. 파일 머리말 설명(" * @BOOK ...")은 여기에 걸리지 않는다.
MARK = re.compile(r"^\s*/\*\s*@(BOOK-FIX|BOOK|ADDED|END)\b(.*?)\*/\s*$")


def parse_blocks(text):
    """mm.c 를 구간 목록으로 나눈다. 각 구간은 dict(kind, head, start, end, body)."""
    lines = text.split("\n")
    blocks, cur = [], None
    for i, line in enumerate(lines):
        m = MARK.match(line)
        if m and m.group(1) != "END":
            if cur is not None:
                sys.exit(f"mm.c:{i + 1}: @END 없이 새 구간이 시작됐다 (앞 구간은 {cur['start'] + 1}행)")
            cur = {"kind": m.group(1), "head": m.group(2).strip(), "start": i, "body": []}
        elif m and m.group(1) == "END":
            if cur is None:
                sys.exit(f"mm.c:{i + 1}: 짝이 없는 @END")
            cur["end"] = i
            blocks.append(cur)
            cur = None
        elif cur is not None:
            cur["body"].append(line)
    if cur is not None:
        sys.exit(f"mm.c:{cur['start'] + 1}: @END 가 없다")
    return blocks, lines


def squash(s):
    return re.sub(r"\s+", "", s)


# ---------------------------------------------------------------- book

NUM = re.compile(r"^\s*\d+(?:\s+|$)")
BORDER = re.compile(r"^\s*code/vm/malloc/mm\.c\s*$")


def pdf_text(pdf):
    if shutil.which("pdftotext") is None:
        sys.exit("pdftotext 가 필요하다 (poppler). 예: sudo apt install poppler-utils")
    out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"pdftotext 실패: {out.stderr.strip()}")
    return out.stdout.split("\n")


def code_between_borders(lines, start):
    """start 이후 첫 'code/vm/malloc/mm.c' 줄과 그다음 같은 줄 사이의 코드를 돌려준다."""
    i = start
    while i < len(lines) and not BORDER.match(lines[i]):
        i += 1
    j = i + 1
    while j < len(lines) and not BORDER.match(lines[j]):
        j += 1
    return [NUM.sub("", l, count=1) for l in lines[i + 1:j]]


def book_reference(lines, label):
    """'Fig 9.43' 또는 'Sol 9.8' 에 해당하는 책의 코드 줄 목록."""
    m = re.match(r"(Fig|Sol)\s+(\d+\.\d+)", label)
    if not m:
        sys.exit(f"알 수 없는 출처 표기: {label!r} (예: 'Fig 9.43, p.893' 또는 'Sol 9.8, p.920')")
    kind, num = m.groups()
    if kind == "Fig":
        # 그림의 코드는 캡션 바로 앞에 있다: [border][코드][border] ... Figure N.M 캡션
        # 본문의 "Figure 9.43 shows ..." 같은 언급과 구별하려고, 코드 끝 border 바로 다음 줄인 것만 캡션으로 본다.
        cap = re.compile(rf"^\s*Figure {re.escape(num)}\s")

        def after_border(k):
            j = k - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            return j >= 0 and BORDER.match(lines[j]) is not None

        idx = [k for k, l in enumerate(lines) if cap.match(l) and after_border(k)]
        if len(idx) != 1:
            sys.exit(f"Figure {num} 캡션을 {len(idx)}번 찾았다 (정확히 1번이어야 한다)")
        k = idx[0]
        # 캡션에서 거슬러 올라가 코드 끝 border 와 시작 border 를 찾는다.
        e = k
        while e >= 0 and not BORDER.match(lines[e]):
            e -= 1
        b = e - 1
        while b >= 0 and not BORDER.match(lines[b]):
            b -= 1
        return [NUM.sub("", l, count=1) for l in lines[b + 1:e]]
    # Sol: 'Solution to Problem N.M' 다음의 첫 코드 블록
    head = re.compile(rf"^\s*Solution to Problem {re.escape(num)}\s")
    idx = [k for k, l in enumerate(lines) if head.match(l)]
    if len(idx) != 1:
        sys.exit(f"'Solution to Problem {num}' 를 {len(idx)}번 찾았다 (정확히 1번이어야 한다)")
    return code_between_borders(lines, idx[0])


def cmd_book(args):
    blocks, _ = parse_blocks(MM.read_text(encoding="utf-8"))
    pdf = pdf_text(args.pdf)
    bad = 0
    n = 0
    for b in blocks:
        if b["kind"] not in ("BOOK", "BOOK-FIX"):
            continue
        n += 1
        label = b["head"]
        drop = None
        if b["kind"] == "BOOK-FIX":
            label, _, d = label.partition("|")
            m = re.match(r"\s*drop:\s*(.+?)\s*$", d)
            if not m:
                sys.exit(f"mm.c:{b['start'] + 1}: @BOOK-FIX 에 '| drop: <줄>' 이 없다")
            drop = m.group(1)
        ref = book_reference(pdf, label.strip())
        if drop is not None:
            hits = [k for k, l in enumerate(ref) if squash(l) == squash(drop)]
            if len(hits) != 1:
                sys.exit(f"mm.c:{b['start'] + 1}: drop 줄 {drop!r} 이 책에서 {len(hits)}번 나온다 (정확히 1번이어야 한다)")
            del ref[hits[0]]
        ours = squash("\n".join(b["body"]))
        theirs = squash("\n".join(ref))
        ok = ours == theirs
        tag = f"{b['kind']} {label.strip()}"
        print(f"  {'✅' if ok else '❌'} {tag}")
        if not ok:
            bad += 1
            k = next((i for i, (x, y) in enumerate(zip(ours, theirs)) if x != y), min(len(ours), len(theirs)))
            print(f"      첫 차이: 위치 {k}")
            print(f"      우리: …{ours[max(0, k - 30):k + 30]}…")
            print(f"      책  : …{theirs[max(0, k - 30):k + 30]}…")
            if len(ours) != len(theirs):
                print(f"      길이(공백 제외): 우리 {len(ours)}, 책 {len(theirs)}")
    print()
    if n == 0:
        print("  ❌ 검사할 @BOOK 구간이 없다")
        return 1
    print(f"  {'✅' if bad == 0 else '❌'} {n - bad}/{n} 구간이 책과 같다")
    return 0 if bad == 0 else 1


# ---------------------------------------------------------------- added


def build_without(skip_idx, blocks, lines):
    """skip_idx 구간(표시 줄 포함)을 지운 mm.c 로 빌드하고 (성공 여부, 첫 오류 줄)을 돌려준다."""
    b = blocks[skip_idx]
    kept = lines[: b["start"]] + lines[b["end"] + 1:]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "malloc-lab"
        work.mkdir()
        for p in list(LAB.glob("*.c")) + list(LAB.glob("*.h")) + [LAB / "Makefile"]:
            shutil.copy(p, work / p.name)
        (work / "mm.c").write_text("\n".join(kept), encoding="utf-8")
        r = subprocess.run(["make", "-C", str(work)], capture_output=True, text=True)
        err = ""
        for l in (r.stderr + r.stdout).split("\n"):
            if re.search(r"\berror\b|undefined reference", l):
                err = l.strip()
                break
        return r.returncode == 0, err


def cmd_added(args):
    text = MM.read_text(encoding="utf-8")
    blocks, lines = parse_blocks(text)
    # 기준: 지우지 않은 mm.c 는 빌드돼야 한다. 이게 안 되면 아래 결과는 아무 뜻이 없다.
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "malloc-lab"
        work.mkdir()
        for p in list(LAB.glob("*.c")) + list(LAB.glob("*.h")) + [LAB / "Makefile"]:
            shutil.copy(p, work / p.name)
        r = subprocess.run(["make", "-C", str(work)], capture_output=True, text=True)
        if r.returncode != 0:
            print("  ❌ 지우지 않은 mm.c 가 빌드되지 않는다. 먼저 이것부터 고쳐야 한다.")
            return 1
    bad = n = 0
    for i, b in enumerate(blocks):
        if b["kind"] != "ADDED":
            continue
        n += 1
        ident = b["head"].split(":")[0].strip()
        built, err = build_without(i, blocks, lines)
        if built:
            bad += 1
            print(f"  ❌ {ident}: 지워도 빌드된다 -> 필요한 추가가 아니다")
        else:
            print(f"  ✅ {ident}: 지우면 빌드 실패 | {err[:110]}")
    print()
    if n == 0:
        print("  ❌ 검사할 @ADDED 구간이 없다")
        return 1
    print(f"  {'✅' if bad == 0 else '❌'} {n - bad}/{n} 구간이 빠질 수 없다")
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("book", help="@BOOK 구간이 책과 같은지")
    b.add_argument("--pdf", required=True, type=Path, help="CS:APP PDF 경로")
    b.set_defaults(fn=cmd_book)
    a = sub.add_parser("added", help="@ADDED 구간이 빠질 수 없는지")
    a.set_defaults(fn=cmd_added)
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
