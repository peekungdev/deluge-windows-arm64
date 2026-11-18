#!/usr/bin/env python3
"""Fix Deluge's ConsoleUI 'started_deferred' ordering bug.

Running any non-interactive console command that begins with `connect` logs:

    AttributeError: 'ConsoleUI' object has no attribute 'started_deferred'

The `connect` command starts the ConsoleUI component, so ConsoleUI.start()
runs - and fires self.started_deferred - before start_console() has created
that attribute. The command still completes (a later start() succeeds), but the
traceback is printed on every invocation.

Fix: create the Deferred in __init__ so it always exists, stop start_console()
from replacing it (which would strand anyone awaiting the already-fired one),
and make start() tolerant of being called more than once.

Idempotent: safe to re-run.
"""

import argparse
import os
import shutil
import sys
import sysconfig

OLD_INIT = """        self.active_mode = None
        self.initialized = False
"""
NEW_INIT = """        self.active_mode = None
        self.initialized = False
        # Created here rather than in start_console(): the `connect` command
        # starts the ConsoleUI component, so start() can fire this before
        # start_console() has run.
        self.started_deferred = defer.Deferred()
"""

OLD_START_CONSOLE = """    async def start_console(self):
        self.started_deferred = defer.Deferred()

        if self.initialized:
"""
NEW_START_CONSOLE = """    async def start_console(self):
        if self.initialized:
"""

OLD_CALLBACK = """        self.started_deferred.callback(True)
"""
NEW_CALLBACK = """        if not self.started_deferred.called:
            self.started_deferred.callback(True)
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site-packages', default=sysconfig.get_path('platlib'))
    args = ap.parse_args()

    path = os.path.join(args.site_packages, 'deluge', 'ui', 'console', 'main.py')
    if not os.path.isfile(path):
        sys.exit('not found: %s' % path)

    with open(path, encoding='utf-8') as fh:
        src = fh.read()

    if 'start_console() has run' in src:
        print('deluge console started_deferred: already patched')
        return

    for old in (OLD_INIT, OLD_START_CONSOLE, OLD_CALLBACK):
        if src.count(old) != 1:
            sys.exit('unexpected main.py: %d matches for %r' % (src.count(old), old[:40]))

    if not os.path.exists(path + '.orig'):
        shutil.copyfile(path, path + '.orig')

    src = src.replace(OLD_INIT, NEW_INIT, 1)
    src = src.replace(OLD_START_CONSOLE, NEW_START_CONSOLE, 1)
    src = src.replace(OLD_CALLBACK, NEW_CALLBACK, 1)

    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(src)

    cache = os.path.join(args.site_packages, 'deluge', 'ui', 'console', '__pycache__')
    if os.path.isdir(cache):
        for f in os.listdir(cache):
            if f.startswith('main.'):
                os.remove(os.path.join(cache, f))

    print('deluge console started_deferred: patched OK')


if __name__ == '__main__':
    main()
