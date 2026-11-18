#!/usr/bin/env bash
# Run Deluge's core test modules against whichever libtorrent is importable.
# Usage: run-core-tests.sh <label> [extra PYTHONPATH entry to put first]
#
# Run stage-tests.sh first. The test tools live in their own venv (testenv/,
# created here on first use) so pytest never lands in MSYS2's site-packages -
# and therefore never in the bundle.
set -uo pipefail
LABEL="$1"; EXTRA="${2:-}"
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
T=$ROOT/testsrc
OUT=$ROOT/testresults; mkdir -p "$OUT"
PY=$ROOT/testenv/bin/python
if [ ! -x "$PY.exe" ] && [ ! -x "$PY" ]; then
	echo "==> creating the test venv"
	python -m venv --system-site-packages "$ROOT/testenv" || exit 1
	"$PY" -m pip install -q pytest pytest-twisted pytest-mock mock pytest-timeout || exit 1
fi
[ -d "$T" ] || { echo "no $T - run stage-tests.sh first" >&2; exit 1; }
cd "$T"
export PYTHONPATH="${EXTRA:+$EXTRA:}$T"
export PYTHONWARNINGS=ignore
"$PY" -c "import libtorrent as l, deluge; print('libtorrent', l.__version__, '| deluge from', deluge.__file__)"
"$PY" -m pytest -p no:cacheprovider -q -rfE \
	--timeout=120 -m "not gtkui and not todo and not internet" \
	deluge/tests/test_core.py deluge/tests/test_torrent.py deluge/tests/test_torrentmanager.py \
	deluge/tests/test_alertmanager.py deluge/tests/test_sessionproxy.py \
	deluge/tests/test_maketorrent.py deluge/tests/test_metafile.py \
	> "$OUT/$LABEL.txt" 2>&1
echo "exit $? -> $OUT/$LABEL.txt"
tail -3 "$OUT/$LABEL.txt"
