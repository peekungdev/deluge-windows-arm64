"""Print one torrent's status from the deluged on 127.0.0.1:58846.

    python status.py <info hash> <localclient password>
"""
import sys

from twisted.internet import defer, reactor

from deluge.ui.client import client

TID, PW = sys.argv[1], sys.argv[2]
KEYS = ['name', 'state', 'total_size', 'progress', 'num_files', 'files', 'is_finished',
        'seeding_time', 'active_time', 'time_since_download']


@defer.inlineCallbacks
def main():
    try:
        yield client.connect('127.0.0.1', 58846, 'localclient', PW)
        st = yield client.core.get_torrent_status(TID, KEYS)
        for k in sorted(st):
            print('  %-20s %r' % (k, [f['path'] for f in st[k]] if k == 'files' else st[k]))
        yield client.disconnect()
    finally:
        reactor.stop()


reactor.callWhenRunning(main)
reactor.run()
