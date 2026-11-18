#!/usr/bin/env bash
# Assemble a self-contained, relocatable Deluge bundle for native Windows ARM64.
#
# Everything is taken from the MSYS2 CLANGARM64 prefix and laid out in the same
# bin/lib/share/etc shape, because GLib and GTK locate their own data by walking
# up from the DLL that is loaded - keeping the shape means that keeps working
# after the folder is moved. The pip-generated entry-point .exe files are NOT
# copied: they hard-code the absolute path of the interpreter that built them.
# deluge-launcher.c replaces them.
#
# Run inside an MSYS2 CLANGARM64 shell, after install-deluge.sh. Paths are
# relative to this script's directory (the repository root); the bundle goes to
# dist/ unless a destination is given as the first argument.
set -euo pipefail

PREFIX=/clangarm64
VERSION=2.2.0
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEST=${1:-$SRC/dist/Deluge-$VERSION-arm64}

# ntldd resolves the DLL closure below.
pacman -S --needed --noconfirm mingw-w64-clang-aarch64-ntldd > /dev/null

echo "==> destination: $DEST"
rm -rf "$DEST"
mkdir -p "$DEST"/{bin,lib,share,etc}

# ---------------------------------------------------------------- interpreter
echo "==> python runtime"
cp "$PREFIX/bin/python.exe" "$PREFIX/bin/pythonw.exe" "$DEST/bin/"

echo "==> python standard library"
mkdir -p "$DEST/lib/python3.14"
tar -C "$PREFIX/lib/python3.14" \
	--exclude='__pycache__' \
	--exclude='test' --exclude='tests' \
	--exclude='idlelib' --exclude='tkinter' --exclude='turtledemo' \
	--exclude='ensurepip' --exclude='pydoc_data' \
	--exclude='site-packages' \
	-cf - . | tar -C "$DEST/lib/python3.14" -xf -

# ------------------------------------------------------------- site-packages
echo "==> site-packages"
# An allowlist from Deluge's dependency closure, not a copy of everything
# MSYS2 has installed: the old denylist shipped 44 MB of unrelated packages
# (OpenEXR imath, VapourSynth, Meson) once those appeared in MSYS2.
mkdir -p "$DEST/lib/python3.14/site-packages"
python "$SRC/collect-site-packages.py" "$DEST/lib/python3.14/site-packages"

# ------------------------------------------------------------------ GTK data
echo "==> GTK runtime data"
cp -r "$PREFIX/lib/gdk-pixbuf-2.0" "$DEST/lib/"
rm -f "$DEST"/lib/gdk-pixbuf-2.0/2.10.0/loaders/*.dll.a
# Allowlist the loaders and their cache entries, before the DLL closure below,
# so a loader some other MSYS2 package installed never drags its DLLs in.
python "$SRC/prune-pixbuf-loaders.py" "$DEST/lib/gdk-pixbuf-2.0/2.10.0"
cp -r "$PREFIX/lib/girepository-1.0" "$DEST/lib/"
mkdir -p "$DEST/share/glib-2.0"
cp -r "$PREFIX/share/glib-2.0/schemas" "$DEST/share/glib-2.0/"
mkdir -p "$DEST/share/icons"
cp -r "$PREFIX/share/icons/Adwaita" "$PREFIX/share/icons/hicolor" "$DEST/share/icons/"
[ -d "$PREFIX/share/themes" ] && cp -r "$PREFIX/share/themes" "$DEST/share/"
[ -d "$PREFIX/etc/gtk-3.0" ] && cp -r "$PREFIX/etc/gtk-3.0" "$DEST/etc/"
[ -d "$PREFIX/etc/fonts" ] && cp -r "$PREFIX/etc/fonts" "$DEST/etc/"
# OpenSSL looks for its provider modules and config relative to nothing
# useful once relocated, so ship them and point the launcher at them.
cp -r "$PREFIX/lib/ossl-modules" "$DEST/lib/"
mkdir -p "$DEST/etc/ssl"
cp "$PREFIX/etc/ssl/openssl.cnf" "$PREFIX/etc/ssl/cert.pem" "$DEST/etc/ssl/"
cp -r "$PREFIX/etc/ssl/certs" "$DEST/etc/ssl/"
# Deluge ships its own icons/glade under site-packages, nothing extra needed.

# -------------------------------------------------------------------- DLLs
echo "==> resolving DLL closure with ntldd"
ROOTS=("$DEST/bin/python.exe" "$DEST/bin/pythonw.exe" "$PREFIX/bin/libpython3.14.dll")

# GIRepository dlopens the GTK stack by name from the typelibs, so ntldd cannot
# discover it from the extension modules - list those explicitly.
for d in libgtk-3-0 libgdk-3-0 libgdk_pixbuf-2.0-0 libgio-2.0-0 libglib-2.0-0 \
         libgobject-2.0-0 libgmodule-2.0-0 libgirepository-1.0-1 libgirepository-2.0-0 \
         libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 libpangowin32-1.0-0 \
         libcairo-2 libcairo-gobject-2 libatk-1.0-0 librsvg-2-2 libepoxy-0 libharfbuzz-0; do
	[ -f "$PREFIX/bin/$d.dll" ] && ROOTS+=("$PREFIX/bin/$d.dll")
done

# Every extension module we just copied, plus the pixbuf loaders.
while IFS= read -r -d '' f; do ROOTS+=("$f"); done \
	< <(find "$DEST/lib/python3.14" -name '*.pyd' -print0)
while IFS= read -r -d '' f; do ROOTS+=("$f"); done \
	< <(find "$DEST/lib/gdk-pixbuf-2.0" -name '*.dll' -print0)

echo "    ${#ROOTS[@]} root binaries"
# ntldd is invoked one file at a time: passing the whole root set at once
# overflows its argument handling and it bails out mid-run.
: > /tmp/deluge-ntldd-raw.txt
for r in "${ROOTS[@]}"; do
	ntldd -R "$r" 2>/dev/null >> /tmp/deluge-ntldd-raw.txt || true
done
tr -d '\r' < /tmp/deluge-ntldd-raw.txt \
	| grep -oiE '[A-Za-z]:[\]+[^ ]*clangarm64[\]+bin[\]+[^ ]+[.]dll' \
	| sort -uf > /tmp/deluge-dlls.txt
echo "    $(grep -c '' /tmp/deluge-dlls.txt) bundled DLLs"

while IFS= read -r w; do
	u=$(cygpath -u "$w")
	[ -f "$u" ] && cp -n "$u" "$DEST/bin/" || true
done < /tmp/deluge-dlls.txt

# ntldd only ever reports a file's dependencies, never the file itself, so any
# root DLL nothing else depends on (libgtk-3-0, libgirepository-*) would be
# left behind. Copy the roots explicitly.
for r in "${ROOTS[@]}"; do
	case "$r" in
		"$PREFIX/bin/"*.dll) cp -n "$r" "$DEST/bin/" 2>/dev/null || true ;;
	esac
done

# ---------------------------------------------------------------- launchers
echo "==> generating entry-point scripts"
mkdir -p "$DEST/lib/deluge-scripts"
write_script() {
	local name="$1" body="$2"
	cat > "$DEST/lib/deluge-scripts/$name" <<SCRIPT
# Entry point for $name, run by bin/$name.exe.
# A real file, not a python -c string, so sys.argv[0] is the program name.
import warnings

# Deluge 2.2.0 still drives its plugin system through pkg_resources. The
# deprecation notice that provokes is not actionable for someone just running
# the application, so keep it out of the console output.
warnings.filterwarnings('ignore', message='pkg_resources is deprecated')

$body
SCRIPT
	echo "    $name"
}

write_script deluge         'from deluge.ui.ui_entry import start_ui; start_ui()'
write_script deluge-gtk     'from deluge.ui.gtk3 import start; start()'
write_script deluge-web     'from deluge.ui.web import start; start()'
write_script deluged        'from deluge.core.daemon_entry import start_daemon; start_daemon()'
write_script deluge-console 'from deluge.ui.console import start; start()'

echo "==> building launchers"
build_launcher() {
	local out="$1" script="$2" console="$3"
	# --no-insert-timestamp makes the launchers reproducible: lld otherwise
	# stamps the build time into the PE header, so every deploy produced
	# different .exe files and a fresh build could not be compared byte-for-
	# byte with the one that was tested.
	local flags=(-O2 -municode -Wall -Wl,--no-insert-timestamp
	             -o "$DEST/bin/$out" "$SRC/launcher/deluge-launcher.c"
	             "-DDELUGE_SCRIPT=L\"$script\"")
	if [ "$console" = yes ]; then
		flags+=(-DDELUGE_CONSOLE)
	else
		flags+=(-Wl,--subsystem,windows)
	fi
	clang "${flags[@]}"
	echo "    $out -> $script"
}

build_launcher Deluge.exe           deluge         no
build_launcher deluge-gtk.exe       deluge-gtk     no
build_launcher deluge-web.exe       deluge-web     no
build_launcher deluged.exe          deluged        no
build_launcher deluge-console.exe   deluge-console yes
build_launcher deluged-debug.exe    deluged        yes
build_launcher deluge-web-debug.exe deluge-web     yes

cp "$SRC/README-arm64-build.txt" "$DEST/"

echo "==> done: $(du -sh "$DEST" | cut -f1)"
