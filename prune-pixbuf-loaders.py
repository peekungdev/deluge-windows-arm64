#!/usr/bin/env python3
"""Keep only the gdk-pixbuf image loaders the bundle is meant to ship.

deploy.sh copies MSYS2's whole lib/gdk-pixbuf-2.0, so any loader installed in
MSYS2 for some other program rides along, along with every DLL ntldd finds
behind it. In 2026-11 that was the JPEG XL loader, pulling in libjxl,
libjxl_cms, libjxl_threads and libbrotlienc - 2.9 MB Deluge never uses.

This deletes loaders outside ALLOWED and rewrites loaders.cache to match, so
gdk-pixbuf never looks for a module that is not there. It runs before the DLL
closure is computed, so the dropped loaders' dependencies are never collected.

Usage: python prune-pixbuf-loaders.py <bundle>/lib/gdk-pixbuf-2.0/2.10.0
"""

import os
import re
import sys

# The stock gdk-pixbuf loaders plus librsvg's SVG loader - the set the bundle
# shipped through 2026-09. Deluge's own icons are PNG and SVG; tracker icons are
# converted to PNG by Deluge before GTK sees them.
ALLOWED = {
    'ani', 'avif', 'bmp', 'gif', 'icns', 'ico', 'jpeg', 'png', 'pnm',
    'qtif', 'tga', 'tiff', 'xbm', 'xpm', 'svg',
}

LOADER = re.compile(r'^(?:libpixbufloader-|pixbufloader_)([a-z0-9]+)\.dll$')


def fmt(filename):
    m = LOADER.match(filename)
    return m.group(1) if m else None


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: %s <gdk-pixbuf-2.0/2.10.0 dir>' % sys.argv[0])
    base = sys.argv[1]
    loaders = os.path.join(base, 'loaders')
    cache = os.path.join(base, 'loaders.cache')

    removed = []
    for f in sorted(os.listdir(loaders)):
        kind = fmt(f)
        if kind is not None and kind not in ALLOWED:
            os.remove(os.path.join(loaders, f))
            removed.append(kind)

    with open(cache, encoding='utf-8', newline='') as fh:
        text = fh.read()
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = text.split(nl)

    # Leading '#' comment lines, then blocks separated by blank lines, each
    # starting with the quoted loader path.
    i = 0
    while i < len(lines) and lines[i].startswith('#'):
        i += 1
    header, rest = lines[:i], lines[i:]
    blocks, cur = [], []
    for line in rest:
        if line.strip():
            cur.append(line)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)

    kept = []
    for block in blocks:
        dll = re.split(r'[\\/]+', block[0].strip('"'))[-1]
        if fmt(dll) in ALLOWED:
            kept.append(block)

    with open(cache, 'w', encoding='utf-8', newline='') as fh:
        fh.write(nl.join(header) + nl + (nl * 2).join(nl.join(b) for b in kept) + nl * 2)

    # Every remaining DLL must have a cache entry and vice versa.
    on_disk = {fmt(f) for f in os.listdir(loaders) if fmt(f)}
    in_cache = {fmt(re.split(r'[\\/]+', b[0].strip('"'))[-1]) for b in kept}
    if on_disk != in_cache:
        sys.exit('loaders.cache out of step: disk=%s cache=%s' % (sorted(on_disk), sorted(in_cache)))
    missing = ALLOWED - on_disk
    if missing:
        sys.exit('expected loaders missing from MSYS2: %s' % sorted(missing))

    print('    pixbuf loaders kept: %d; removed: %s' % (len(kept), ', '.join(removed) or 'none'))


if __name__ == '__main__':
    main()
