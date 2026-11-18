#!/usr/bin/env bash
# Install Deluge + the pywin32 shim + patches into the MSYS2 CLANGARM64 Python.
# Run inside an MSYS2 CLANGARM64 shell, after build-libtorrent.sh. Paths are
# relative to this script's directory (the repository root).
set -euo pipefail
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SP=$(python -c 'import sysconfig; print(sysconfig.get_path("platlib"))')

DELUGE_VERSION=2.2.0
# Pinned: the sdist is verified against this, not just against what PyPI says.
DELUGE_SHA256=f0fc64e052334ef294ca3951975dd926f129d62813f6c909bb523d914abe6537

echo "==> runtime dependencies from MSYS2"
pacman -S --needed --noconfirm \
	mingw-w64-clang-aarch64-python-{pip,setuptools,gobject,cairo,twisted,rencode} \
	mingw-w64-clang-aarch64-python-{zope.interface,chardet,pillow,pyopenssl} \
	mingw-w64-clang-aarch64-python-{cryptography,mako,pyasn1,setproctitle,ifaddr} \
	mingw-w64-clang-aarch64-python-{service-identity,certifi,idna} \
	mingw-w64-clang-aarch64-{gtk3,librsvg,adwaita-icon-theme,hicolor-icon-theme}

echo "==> pure-python bits pip has to supply"
python -m pip install --break-system-packages pyxdg jaraco.text

echo "==> pkg_resources (setuptools 83 no longer ships it)"
python - <<'PY'
import glob, os, shutil, subprocess, sys, sysconfig, tempfile, zipfile
sp = sysconfig.get_path('platlib')
if not os.path.isdir(os.path.join(sp, 'pkg_resources')):
    # A real temp dir: a POSIX-looking '/tmp/...' would mean C:\tmp to this
    # native Windows Python.
    tmp = tempfile.mkdtemp(prefix='swheel')
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'download', '--no-deps',
                               '--only-binary', ':all:', 'setuptools==80.9.0', '-d', tmp])
        whl = glob.glob(os.path.join(tmp, 'setuptools-80.9.0*.whl'))[0]
        with zipfile.ZipFile(whl) as z:
            for n in z.namelist():
                if n.startswith('pkg_resources/'):
                    z.extract(n, sp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('pkg_resources installed')
else:
    print('pkg_resources already present')
PY

if [ ! -d "$SRC/deluge-$DELUGE_VERSION" ]; then
	echo "==> fetching the Deluge $DELUGE_VERSION sdist from PyPI"
	python - "$SRC" "$DELUGE_VERSION" "$DELUGE_SHA256" <<'PY'
import hashlib, io, json, sys, tarfile, urllib.request
dest, ver, pinned = sys.argv[1:4]
meta = json.load(urllib.request.urlopen('https://pypi.org/pypi/deluge/%s/json' % ver))
sdist = next(u for u in meta['urls'] if u['packagetype'] == 'sdist')
data = urllib.request.urlopen(sdist['url']).read()
digest = hashlib.sha256(data).hexdigest()
if digest != pinned:
    sys.exit('%s: sha256 %s, expected %s - refusing to build' % (sdist['filename'], digest, pinned))
with tarfile.open(fileobj=io.BytesIO(data)) as tf:
    tf.extractall(dest, filter='data')
print('extracted %s (sha256 verified)' % sdist['filename'])
PY
fi

echo "==> pywin32 shim"
cp "$SRC"/pywin32-shim/*.py "$SP/"
rm -rf "$SP/pywin32-306.dist-info"
cp -r "$SRC/pywin32-shim/pywin32-306.dist-info" "$SP/"

echo "==> Deluge"
python -m pip install --break-system-packages --no-deps --no-build-isolation "$SRC/deluge-$DELUGE_VERSION"

echo "==> patches"
"$SRC/patches/patch-twisted-glib-waker.sh"
python "$SRC/patches/patch-twisted-portable-glib-reactor.py"
python "$SRC/patches/patch-deluge-crypto.py"
python "$SRC/patches/patch-deluge-console-started.py"
python "$SRC/patches/patch-deluge-ipc-port.py"
# libtorrent 2.1 compatibility. Must run after the pip reinstall above, like
# the others; it rewrites core/ files pip has just restored.
python "$SRC/patches/patch-deluge-libtorrent21.py"

echo "==> done"
python -c "import deluge.common; from deluge._libtorrent import lt; print('deluge', deluge.common.get_version(), '/ libtorrent', lt.__version__)"
