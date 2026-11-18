#!/usr/bin/env bash
# Twisted >= 26 hardcodes GlibWaker's base class to _UnixWaker, which is built on
# os.pipe() + twisted.internet.fdesc. fdesc is only imported on POSIX, so on
# Windows any glib/gtk3 reactor dies at startup with:
#     NameError: name 'fdesc' is not defined
# _signals.py already picks the right waker per platform as `_Waker`
# (_SocketWaker on Windows), so use that instead. Idempotent.
set -euo pipefail

SP="${1:-$(python -c 'import sysconfig;print(sysconfig.get_path("platlib"))')}"
F="$SP/twisted/internet/_glibbase.py"

[ -f "$F" ] || { echo "not found: $F" >&2; exit 1; }

if grep -q "_Waker as _PlatformWaker" "$F"; then
	echo "twisted glib waker: already patched"
	exit 0
fi

[ -f "$F.orig" ] || cp "$F" "$F.orig"

sed -i \
	-e 's/^from \._signals import _IWaker, _UnixWaker$/from ._signals import _IWaker, _Waker as _PlatformWaker/' \
	-e 's/^class GlibWaker(_UnixWaker):$/class GlibWaker(_PlatformWaker):/' \
	"$F"

grep -q "_Waker as _PlatformWaker" "$F" && grep -q "class GlibWaker(_PlatformWaker):" "$F" \
	|| { echo "twisted glib waker: PATCH FAILED, restoring" >&2; cp "$F.orig" "$F"; exit 1; }

# Drop any stale bytecode so the patched source is what actually loads.
rm -f "$SP/twisted/internet/__pycache__/_glibbase."*.pyc 2>/dev/null || true
echo "twisted glib waker: patched OK"
