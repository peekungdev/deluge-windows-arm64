#!/usr/bin/env python3
"""Restore Twisted's portable (Windows) glib reactor.

Twisted 26's gtk3/gi reactor cannot do socket I/O on Windows at all. Both
GIReactor and PortableGIReactor now derive from GlibReactorBase, which watches
descriptors through GLib IO watches - and a Windows SOCKET is not a GLib-
watchable file descriptor, so read and write events are simply never delivered.
The connection is established and then nothing moves:

    Sent 30 B (0.0 KiB/s) Recv 0 B (0.0 KiB/s)

which is what breaks Deluge's thin-client mode: the GTK UI talks to deluged
over Twisted, so the RPC never completes and the Connection Manager reports
every daemon as Offline. Standalone mode is unaffected because libtorrent does
its own networking in C++.

Twisted used to ship exactly the fix for this - PortableGlibReactorBase, a
SelectReactor subclass that keeps Twisted's own select() loop for sockets and
merely pumps the glib main loop on a timer. It was dropped, but the vestigial
no-op PortableGIReactor.simulate() is still there as evidence. This patch puts
that class back and points PortableGIReactor at it.

Idempotent: safe to re-run.
"""

import argparse
import os
import shutil
import sys
import sysconfig

MARKER = 'class PortableGlibReactorBase'

REACTOR_CLASS = '''

class PortableGlibReactorBase(selectreactor.SelectReactor):
    """
    Base class for GObject event loop reactors that work on Windows.

    GLib's IO watches are built on Unix file descriptors, and a Windows SOCKET
    is not one, so the descriptor-driven L{GlibReactorBase} silently never
    delivers read or write events there. This variant keeps Twisted's own
    select() loop for socket I/O and only pumps the glib main loop on a timer,
    which is what lets a GTK UI and Twisted coexist on Windows.
    """

    def __init__(self, glib_module, gtk_module, useGtk=False):
        self._simtag = None
        self._glib = glib_module
        self._gtk = gtk_module
        selectreactor.SelectReactor.__init__(self)
        self.context = self._glib.main_context_default()
        self.loop = self._glib.MainLoop()

    def crash(self):
        selectreactor.SelectReactor.crash(self)
        if self.loop:
            self.loop.quit()

    def run(self, installSignalHandlers=True):
        self.startRunning(installSignalHandlers=installSignalHandlers)
        self._glib.timeout_add(0, self.simulate)
        if self._started:
            self.loop.run()

    def simulate(self):
        """
        Run a Twisted iteration, then reschedule ourselves from the glib loop.
        """
        if self._simtag is not None:
            self._glib.source_remove(self._simtag)
        self.iterate(0)
        timeout = self.timeout()
        # Cap the wait so the UI stays responsive; timeout() may return None
        # when there is no scheduled call at all.
        if timeout is None or timeout > 0.01:
            timeout = 0.01
        self._simtag = self._glib.timeout_add(int(timeout * 1000), self.simulate)
        return False
'''


def patch_glibbase(path):
    with open(path, encoding='utf-8') as fh:
        src = fh.read()

    if MARKER in src:
        print('  _glibbase.py: already patched')
        return

    old_import = 'from twisted.internet import posixbase\n'
    if old_import not in src:
        sys.exit('unexpected _glibbase.py: import block not found')

    if not os.path.exists(path + '.orig2'):
        shutil.copyfile(path, path + '.orig2')

    src = src.replace(old_import, 'from twisted.internet import posixbase, selectreactor\n', 1)
    src = src.rstrip('\n') + '\n' + REACTOR_CLASS

    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(src)
    print('  _glibbase.py: PortableGlibReactorBase restored')


def patch_gireactor(path):
    with open(path, encoding='utf-8') as fh:
        src = fh.read()

    if 'PortableGlibReactorBase' in src:
        print('  gireactor.py: already patched')
        return

    old_base = 'class PortableGIReactor(_glibbase.GlibReactorBase):'
    new_base = 'class PortableGIReactor(_glibbase.PortableGlibReactorBase):'
    if old_base not in src:
        sys.exit('unexpected gireactor.py: PortableGIReactor base not found')

    # This no-op override would defeat the restored base class.
    old_sim = '''
    def simulate(self) -> None:
        """
        For compatibility only. Do nothing.
        """
'''
    if old_sim not in src:
        sys.exit('unexpected gireactor.py: no-op simulate() not found')

    if not os.path.exists(path + '.orig'):
        shutil.copyfile(path, path + '.orig')

    src = src.replace(old_base, new_base, 1).replace(old_sim, '', 1)

    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(src)
    print('  gireactor.py: PortableGIReactor rebased, no-op simulate() removed')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site-packages', default=sysconfig.get_path('platlib'))
    args = ap.parse_args()

    internal = os.path.join(args.site_packages, 'twisted', 'internet')
    for name in ('_glibbase.py', 'gireactor.py'):
        if not os.path.isfile(os.path.join(internal, name)):
            sys.exit('not found: %s' % os.path.join(internal, name))

    patch_glibbase(os.path.join(internal, '_glibbase.py'))
    patch_gireactor(os.path.join(internal, 'gireactor.py'))

    cache = os.path.join(internal, '__pycache__')
    if os.path.isdir(cache):
        for f in os.listdir(cache):
            if f.startswith(('_glibbase.', 'gireactor.', 'gtk3reactor.')):
                os.remove(os.path.join(cache, f))

    print('twisted portable glib reactor: patched OK')


if __name__ == '__main__':
    main()
