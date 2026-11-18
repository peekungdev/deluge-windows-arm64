"""Run by the portable folder's own Python, from magtest/e2e.py.

    python e2e_client.py <localclient password> <magnet> <download dir>

Adds the magnet to the deluged on 127.0.0.1:58846, dials the seeder named in
the magnet's x.pe hint (Deluge ignores the hint), waits until the torrent is
complete and seeding, then shuts the daemon down. Exit status 0 on success.
"""
import re
import sys

from twisted.internet import defer, reactor, task

from deluge.ui.client import client

PW, MAGNET, DL = sys.argv[1:4]
HOST, PORT = re.search(r'x\.pe=([^&:]+):(\d+)', MAGNET).groups()
PORT = int(PORT)
KEYS = ['name', 'state', 'total_size', 'progress', 'num_peers', 'is_finished']
result = {'ok': False}


@defer.inlineCallbacks
def main():
    try:
        yield client.connect('127.0.0.1', 58846, 'localclient', PW)
        version = yield client.daemon.get_version()
        lt_version = yield client.core.get_libtorrent_version()
        print('daemon: deluge %s, libtorrent %s' % (version, lt_version), flush=True)
        tid = yield client.core.add_torrent_magnet(MAGNET, {'download_location': DL})
        print('added %s' % tid, flush=True)
        for i in range(90):
            st = yield client.core.get_torrent_status(tid, KEYS)
            print('  t+%3ds %-11s size=%-8s %5.1f%% peers=%s'
                  % (i * 2, st['state'], st['total_size'], st['progress'], st['num_peers']),
                  flush=True)
            if st['is_finished'] and st['state'] == 'Seeding':
                result['ok'] = True
                print('COMPLETE: %s, %d bytes, seeding' % (st['name'], st['total_size']), flush=True)
                break
            if not st['num_peers']:
                yield client.core.connect_peer(tid, HOST, PORT)
            yield task.deferLater(reactor, 2, lambda: None)
        try:
            yield client.daemon.shutdown()
            print('daemon shutdown requested', flush=True)
        except Exception as e:  # the connection can drop before the reply
            print('shutdown: %r' % e, flush=True)
    except Exception as e:
        print('ERROR: %r' % e, flush=True)
    finally:
        if reactor.running:
            reactor.stop()


reactor.callWhenRunning(main)
reactor.run()
sys.exit(0 if result['ok'] else 1)
