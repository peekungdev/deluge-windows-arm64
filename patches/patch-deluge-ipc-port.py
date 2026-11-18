#!/usr/bin/env python3
"""Make Deluge's Windows single-instance IPC socket robust.

Two problems in the Windows branch of deluge/ui/gtk3/ipcinterface.py:

1. The IPC listener port is chosen with random.randrange(20000, 65535) and
   bound directly. Windows reserves large blocks of that range for Hyper-V,
   WSL, Docker and friends (see: netsh interface ipv4 show excludedportrange
   protocol=tcp - typically several hundred ports across a dozen ranges).
   Landing in one fails the bind with

       WinError 10013: An attempt was made to access a socket in a way
       forbidden by its access permissions

   and Deluge dies before the UI ever appears. It is intermittent, so it reads
   to a user as "Deluge randomly won't start". Binding port 0 and asking the
   OS for the actual port removes the guesswork entirely.

2. If the global mutex exists but the socket file does not - a previous
   instance was killed, or is still starting up - the else branch reads a file
   that isn't there and dies with FileNotFoundError. The POSIX branch already
   recovers from its equivalent stale-lockfile case; this makes the Windows
   branch recover the same way instead of crashing.

Idempotent: safe to re-run.
"""

import argparse
import os
import shutil
import sys
import sysconfig

OLD_LISTEN = """                self.factory = Factory()
                self.factory.protocol = IPCProtocolServer
                import random

                port = random.randrange(20000, 65535)
                self.listener = reactor.listenTCP(port, self.factory)
                # Store the port number in the socket file
                with open(socket, 'w') as _file:
                    _file.write(str(port))
"""

NEW_LISTEN = """                self.factory = Factory()
                self.factory.protocol = IPCProtocolServer
                # Bind port 0 and let the OS hand back a free port. Picking one
                # at random instead means sometimes landing inside a Windows
                # reserved port range (Hyper-V/WSL/Docker reserve hundreds of
                # ports in 20000-65535), where bind fails with WinError 10013
                # and Deluge exits before the UI appears.
                self.listener = reactor.listenTCP(0, self.factory)
                port = self.listener.getHost().port
                # Store the port number in the socket file
                with open(socket, 'w') as _file:
                    _file.write(str(port))
"""

OLD_CONNECT = """            else:
                # Send to existing deluge process
                with open(socket) as _file:
                    port = int(_file.readline())
"""

NEW_CONNECT = """            else:
                # Send to existing deluge process. The mutex can outlive the
                # socket file if the previous instance was killed, or precede
                # it if that instance is still starting up; either way there is
                # nothing to hand off to, so carry on starting normally rather
                # than dying with FileNotFoundError.
                try:
                    with open(socket) as _file:
                        port = int(_file.readline())
                except (OSError, ValueError):
                    log.warning(
                        'Deluge mutex is held but %s is unreadable; '
                        'assuming a stale instance and starting normally.',
                        socket,
                    )
                    self.factory = Factory()
                    self.factory.protocol = IPCProtocolServer
                    self.listener = reactor.listenTCP(0, self.factory)
                    with open(socket, 'w') as _file:
                        _file.write(str(self.listener.getHost().port))
                    process_args(args)
                    return
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site-packages', default=sysconfig.get_path('platlib'))
    args = ap.parse_args()

    path = os.path.join(
        args.site_packages, 'deluge', 'ui', 'gtk3', 'ipcinterface.py'
    )
    if not os.path.isfile(path):
        sys.exit('not found: %s' % path)

    with open(path, encoding='utf-8') as fh:
        src = fh.read()

    if 'Bind port 0 and let the OS hand back a free port' in src:
        print('deluge ipc port: already patched')
        return

    for old in (OLD_LISTEN, OLD_CONNECT):
        if src.count(old) != 1:
            sys.exit(
                'unexpected ipcinterface.py: %d matches for %r'
                % (src.count(old), old.strip()[:50])
            )

    if not os.path.exists(path + '.orig'):
        shutil.copyfile(path, path + '.orig')

    src = src.replace(OLD_LISTEN, NEW_LISTEN, 1)
    src = src.replace(OLD_CONNECT, NEW_CONNECT, 1)

    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(src)

    cache = os.path.join(args.site_packages, 'deluge', 'ui', 'gtk3', '__pycache__')
    if os.path.isdir(cache):
        for f in os.listdir(cache):
            if f.startswith('ipcinterface.'):
                os.remove(os.path.join(cache, f))

    print('deluge ipc port: patched OK')


if __name__ == '__main__':
    main()
