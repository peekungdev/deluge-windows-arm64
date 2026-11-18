#!/usr/bin/env bash
# Build libtorrent and its Python bindings for native Windows ARM64.
#
# MSYS2 ships libtorrent with no Python bindings, and there is no ARM64 wheel
# for any interpreter, so the bindings have to be compiled here.
#
# 2.1.x (currently 2.1.2, the newest release - there is no 2.2) replaced the
# original 2.0.x on 2026-09-28. 2.1 drops everything deprecated in libtorrent
# 1.1 and earlier and removes several settings, and Deluge 2.2.0 uses ~20 of
# those; patches/patch-deluge-libtorrent21.py (applied by install-deluge.sh)
# ports Deluge onto the replacements. Without it Deluge cannot even start.
#
# The one thing that makes this straightforward: MSYS2's Boost already builds
# libboost_python<ver> matching the CLANGARM64 Python exactly, so the bindings
# CMakeLists finds Boost::python314 without any coaxing.
#
# Run inside an MSYS2 CLANGARM64 shell, from anywhere: paths are relative to
# this script's directory (the repository root).
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
LT_TAG=v2.1.2
SRC=$ROOT/libtorrent-${LT_TAG#v}
BUILD=$ROOT/build-lt
PREFIX=$ROOT/prefix
# MSYS2 CLANGARM64 ships no git; fall back to Git for Windows.
GIT=$(command -v git || echo "/c/Program Files/Git/cmd/git.exe")

export COMSPEC="C:\Windows\System32\cmd.exe"   # qmake/cmake compiler probes

echo "==> build tools from MSYS2"
pacman -S --needed --noconfirm \
	mingw-w64-clang-aarch64-{clang,cmake,ninja,boost,openssl,python,python-packaging}

if [ ! -d "$SRC" ]; then
	echo "==> cloning libtorrent $LT_TAG"
	"$GIT" clone --depth 1 --branch "$LT_TAG" --recurse-submodules \
		https://github.com/arvidn/libtorrent.git "$SRC"
fi

# libc++ 23 dropped transitive <algorithm>/<iterator>; backport the upstream
# one-line include fixes 2.1.2 lacks. Idempotent; see the script for details.
python "$ROOT/patches/patch-libtorrent-libcxx-includes.py" "$SRC"

# Always configure from scratch. A reused cache has broken this twice: once when
# MSYS2 moved Boost 1.91 -> 1.92 (the cache pinned the old Boost paths) and once
# when changing LT_TAG (CMake refuses a cache made from a different source dir).
# A full build is only a few minutes, so incremental builds are not worth that.
rm -rf "$BUILD"

# Keep this folder's path and the build time out of the module, so a build in
# any other checkout gives the same bytes. Without the prefix map, __FILE__
# strings and clang's "(lambda at <path>)" names embed the source path; without
# --no-insert-timestamp, lld writes the build time into the PE header.
REPRO_CFLAGS="-ffile-prefix-map=$(cygpath -m "$SRC")=libtorrent-${LT_TAG#v}"
REPRO_LDFLAGS="-Wl,--no-insert-timestamp"

echo "==> configuring"
cmake -G Ninja -S "$SRC" -B "$BUILD" \
	-DCMAKE_BUILD_TYPE=Release \
	-Dpython-bindings=ON \
	-Dpython-egg-info=ON \
	-DBUILD_SHARED_LIBS=OFF \
	-DCMAKE_C_FLAGS="$REPRO_CFLAGS" \
	-DCMAKE_CXX_FLAGS="$REPRO_CFLAGS" \
	-DCMAKE_MODULE_LINKER_FLAGS="$REPRO_LDFLAGS" \
	-DCMAKE_SHARED_LINKER_FLAGS="$REPRO_LDFLAGS" \
	-DCMAKE_INSTALL_PREFIX="$PREFIX" \
	-DPython3_EXECUTABLE=/clangarm64/bin/python.exe

echo "==> building"
# Never pipe this into tail inside an && chain - the pipeline takes tail's
# exit status and a failed build reports success.
cmake --build "$BUILD" --parallel "$(nproc)"

PYD=$(find "$BUILD/bindings/python" -maxdepth 1 -name 'libtorrent*.pyd' | head -1)
[ -n "$PYD" ] || { echo "no .pyd produced" >&2; exit 1; }

SP=$(python -c 'import sysconfig; print(sysconfig.get_path("platlib"))')
echo "==> installing $(basename "$PYD") -> $SP"
cp "$PYD" "$SP/"
rm -rf "$SP/libtorrent.egg-info"
cp -r "$BUILD/bindings/python/libtorrent.egg-info" "$SP/"
# SOURCES.txt only lists absolute paths into build-lt/. Nothing reads it, and it
# would put this folder's path into the bundle.
rm -f "$SP/libtorrent.egg-info/SOURCES.txt"

python -c 'import libtorrent as lt; print("libtorrent", lt.__version__, "ok")'
