#!/usr/bin/env bash
# Stage a test tree = the installed (patched) Deluge package + the sdist's test
# suite, so the tests exercise exactly what ships rather than the unpatched
# sdist. Unpatched Deluge dies generating its daemon certificate on pyOpenSSL 26
# (see patches/patch-deluge-crypto.py), which would fail nearly every test and
# hide the signal being looked for.
#
# Run inside an MSYS2 CLANGARM64 shell, after install-deluge.sh (which also
# fetches the sdist this takes the tests from). Then run run-core-tests.sh.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SDIST=$ROOT/deluge-2.2.0
[ -d "$SDIST/deluge/tests" ] || { echo "no $SDIST - run install-deluge.sh first" >&2; exit 1; }
SP=$(python -c 'import sysconfig; print(sysconfig.get_path("platlib"))')
T=$ROOT/testsrc
rm -rf "$T"; mkdir -p "$T"
cp -r "$SP/deluge" "$T/deluge"
rm -rf "$T/deluge/tests"
cp -r "$SDIST/deluge/tests" "$T/deluge/tests"
[ -f "$T/deluge/conftest.py" ] || cp "$SDIST/deluge/conftest.py" "$T/deluge/"
cp "$SDIST/pyproject.toml" "$T/"

# test_prefetch_metadata mocks handle.get_torrent_info(), an ABI-1-only method
# libtorrent 2.1 removed. patches/patch-deluge-libtorrent21.py moved Deluge onto
# handle.torrent_file(), so point the mock at the method Deluge now calls;
# otherwise the test hands an unconfigured MagicMock to b64encode and fails for
# a reason that has nothing to do with Deluge's behaviour.
python - "$T/deluge/tests/test_torrentmanager.py" <<'PY'
import sys
path = sys.argv[1]
src = open(path, encoding='utf-8').read()
old = 'mock_alert.handle.get_torrent_info = mock.MagicMock(return_value=t_info)'
new = 'mock_alert.handle.torrent_file = mock.MagicMock(return_value=t_info)'
if old in src:
    open(path, 'w', encoding='utf-8').write(src.replace(old, new, 1))
elif new not in src:
    sys.exit('test_prefetch_metadata mock not found - upstream test changed')
PY

find "$T" -name '__pycache__' -type d -prune -exec rm -rf {} +
echo "staged $T ($(ls "$T"/deluge/tests/test_*.py | wc -l) test files)"
