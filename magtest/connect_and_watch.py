"""Tell the running deluged to dial the local seeder, then watch the magnet
resolve: metadata fetch (size goes from 0), download, and completion.

    python connect_and_watch.py <info hash> <localclient password>

Expects deluged on 127.0.0.1:58846 and seeder.py's magnet.txt next to this file.
"""
import os
import re
import sys

from twisted.internet import defer, reactor, task

from deluge.ui.client import client

TID, PW = sys.argv[1], sys.argv[2]

# The seeder binds an OS-chosen port and records it as the magnet's x.pe hint;
# Deluge ignores that hint, so read it here and dial the peer explicitly.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'magnet.txt')) as fh:
    PEER_HOST, PEER_PORT = re.search(r'x\.pe=([^&:]+):(\d+)', fh.read()).groups()
PEER_PORT = int(PEER_PORT)
KEYS = ['name', 'state', 'total_size', 'progress', 'num_peers', 'active_time',
        'time_since_download', 'seeding_time', 'paused', 'is_finished']


@defer.inlineCallbacks
def main():
    yield client.connect('127.0.0.1', 58846, 'localclient', PW)
    ok = yield client.core.connect_peer(TID, PEER_HOST, PEER_PORT)
    print('connect_peer %s:%d -> %r' % (PEER_HOST, PEER_PORT, ok), flush=True)
    for i in range(40):
        yield task.deferLater(reactor, 3, lambda: None)
        st = yield client.core.get_torrent_status(TID, KEYS)
        print('  t+%3ds  %-11s size=%-8s progress=%5.1f%% peers=%s active=%ss since_dl=%s paused=%s'
              % ((i + 1) * 3, st['state'], st['total_size'], st['progress'],
                 st['num_peers'], st['active_time'], st['time_since_download'],
                 st['paused']), flush=True)
        if st['progress'] >= 100:
            print('COMPLETE: %r' % {k: st[k] for k in KEYS}, flush=True)
            break
    yield client.disconnect()
    reactor.stop()


reactor.callWhenRunning(main)
reactor.run()
