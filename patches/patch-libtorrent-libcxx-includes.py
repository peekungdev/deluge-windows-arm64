#!/usr/bin/env python3
"""Backport two missing-#include fixes so libtorrent 2.1.2 builds with clang 23.

libc++ 23 stopped pulling <algorithm> and <iterator> in transitively, and two
files in the libtorrent 2.1.2 tree relied on that:

    src/escape_string.cpp:439
        error: no member named 'back_inserter' in namespace 'std'
    deps/libdatachannel/src/configuration.cpp:29
        error: no member named 'transform' in namespace 'std'

Both are already fixed upstream with exactly these one-line includes -
libtorrent's RC_2_1 branch adds <iterator> to escape_string.cpp, and
libdatachannel master adds <algorithm> to configuration.cpp - but neither fix
is in a tagged libtorrent release yet (2.1.2 pins the older libdatachannel).
Drop this script once a libtorrent release ships both.

Run against the libtorrent source tree; build-libtorrent.sh does this before
configuring. Idempotent: safe to re-run.
"""

import os
import sys

# (path relative to the source tree, line to insert after, line to insert)
EDITS = [
    (
        'src/escape_string.cpp',
        '#include <cstring>\n',
        '#include <iterator>\n',
    ),
    (
        'deps/libdatachannel/src/configuration.cpp',
        '#include "impl/utils.hpp"\n\n',
        '#include <algorithm>\n',
    ),
]


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: %s <libtorrent source tree>' % sys.argv[0])
    root = sys.argv[1]

    sources = {}
    for rel, anchor, inserted in EDITS:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            sys.exit('not found: %s' % path)
        with open(path, encoding='utf-8', newline='') as fh:
            src = fh.read()
        # A Windows git checkout has CRLF endings; match whatever the file uses.
        nl = '\r\n' if '\r\n' in src else '\n'
        anchor, inserted = anchor.replace('\n', nl), inserted.replace('\n', nl)
        if inserted in src:
            continue
        if src.count(anchor) != 1:
            sys.exit(
                'unexpected %s: %d matches for %r' % (rel, src.count(anchor), anchor)
            )
        sources[rel] = src.replace(anchor, anchor + inserted, 1)

    if not sources:
        print('libtorrent libc++ includes: already patched')
        return

    for rel, src in sources.items():
        with open(os.path.join(root, rel), 'w', encoding='utf-8', newline='') as fh:
            fh.write(src)
    print('libtorrent libc++ includes: patched OK (%s)' % ', '.join(sorted(sources)))


if __name__ == '__main__':
    main()
