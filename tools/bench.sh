#!/usr/bin/env bash
# tools/bench.py 를 부르는 얇은 래퍼. python3 가 필요하다.
exec python3 "$(dirname "$0")/bench.py" "$@"
