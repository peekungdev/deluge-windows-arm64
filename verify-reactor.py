"""Verify the gtk3/glib reactor can do socket I/O on Windows.

This is the regression check for the thin-client fix. Twisted 26's
PortableGIReactor watches descriptors through GLib IO watches, which never fire
for Windows SOCKETs, so the GTK UI's RPC to deluged silently never completes
and every daemon shows as Offline. patches/patch-twisted-portable-glib-reactor.py
restores Twisted's old SelectReactor-based portable reactor; this proves it.

Run after any Twisted, GLib or GTK update:
    python verify-reactor.py gtk3      # must print PONG:PING
    python verify-reactor.py default   # control, always works

Exits non-zero if the round trip fails.
"""

import socket
import sys
import threading

MODE = sys.argv[1] if len(sys.argv) > 1 else 'gtk3'

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.bind(('127.0.0.1', 0))
srv.listen(1)
PORT = srv.getsockname()[1]


def echo():
    conn, _ = srv.accept()
    data = conn.recv(64)
    conn.sendall(b'PONG:' + data)
    conn.close()


threading.Thread(target=echo, daemon=True).start()

if MODE == 'gtk3':
    from twisted.internet import gtk3reactor

    gtk3reactor.install()

from twisted.internet import reactor  # noqa: E402
from twisted.internet.protocol import ClientFactory, Protocol  # noqa: E402

result = {'got': None}


class P(Protocol):
    def connectionMade(self):
        self.transport.write(b'PING')

    def dataReceived(self, data):
        result['got'] = data
        reactor.stop()


class F(ClientFactory):
    protocol = P

    def clientConnectionFailed(self, connector, reason):
        result['got'] = b'CONNECT FAILED'
        reactor.stop()


def timeout():
    result['got'] = result['got'] or b'** TIMED OUT - no data ever read **'
    reactor.stop()


reactor.callLater(8, timeout)
reactor.connectTCP('127.0.0.1', PORT, F())
reactor.run()

got = result['got'].decode(errors='replace')
print('reactor : %s' % type(reactor).__name__)
print('result  : %s' % got)
sys.exit(0 if got == 'PONG:PING' else 1)
