import sys
from twisted.internet import defer, reactor
from deluge.ui.client import client
TID, PW = sys.argv[1], sys.argv[2]
@defer.inlineCallbacks
def main():
    yield client.connect('127.0.0.1', 58846, 'localclient', PW)
    st = yield client.core.get_torrent_status(TID, ['name', 'state', 'total_size', 'progress',
        'num_files', 'files', 'is_finished', 'seeding_time', 'active_time', 'time_since_download'])
    for k in sorted(st): print('  %-20s %r' % (k, st[k] if k != 'files' else [f['path'] for f in st[k]]))
    yield client.disconnect(); reactor.stop()
reactor.callWhenRunning(main); reactor.run()
