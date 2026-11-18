"""Seed torrents on 127.0.0.1 and write magnet links that point at them.

Deluge is given only a magnet (info hash + peer hint), so it must fetch the
metadata from this peer - exercising metadata_received_alert and the
torrent_file() fix - then download and hash-check the data.

    python seeder.py [seconds] [--hybrid] [--file PATH ...]

Without --file it seeds a fresh 4 MiB random payload and records its sha256 in
payload.sha256, so the downloaded copy can be checked byte for byte. With
--file it seeds those files instead, one single-file torrent each. Magnets go
to magnet.txt next to this script, one per line.

--hybrid makes v1+v2 hybrid torrents (libtorrent's default) instead of v1-only.
Deluge 2.2.0 loses track of a hybrid torrent added by a v1-only magnet - see
hybrid_hash.py - so the normal test uses v1-only torrents.
"""
import argparse
import hashlib
import os
import sys
import time

import libtorrent as lt

BASE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser()
ap.add_argument('seconds', nargs='?', type=float, default=240, help='how long to seed')
ap.add_argument('--hybrid', action='store_true', help='make v1+v2 hybrid torrents')
ap.add_argument('--file', action='append', default=[], help='seed this existing file')
args = ap.parse_args()

if args.file:
    payloads = [os.path.abspath(p) for p in args.file]
else:
    os.makedirs(os.path.join(BASE, 'seed', 'magnet-payload'), exist_ok=True)
    data = os.urandom(4 * 1024 * 1024)
    path = os.path.join(BASE, 'seed', 'magnet-payload', 'data.bin')
    with open(path, 'wb') as fh:
        fh.write(data)
    with open(os.path.join(BASE, 'payload.sha256'), 'w') as fh:
        fh.write(hashlib.sha256(data).hexdigest())
    payloads = [os.path.dirname(path)]  # a one-file directory torrent


def make_torrent(path):
    fs = lt.file_storage()
    lt.add_files(fs, path)
    flags = 0 if args.hybrid else lt.create_torrent.v1_only
    ct = lt.create_torrent(fs, piece_size=262144, flags=flags)
    lt.set_piece_hashes(ct, os.path.dirname(path))
    return lt.torrent_info(ct.generate())


# Port 0: let the OS pick. A fixed port (this used 51413, the classic
# BitTorrent port) can land inside a range Hyper-V/WSL reserved at boot - the
# ranges move every boot - and then libtorrent cannot listen at all, so the
# test fails as "magnet never resolves" for a reason unrelated to Deluge.
ses = lt.session({'listen_interfaces': '127.0.0.1:0', 'enable_dht': False,
                  'enable_lsd': False, 'enable_upnp': False, 'enable_natpmp': False,
                  # Every test peer is 127.0.0.1. With libtorrent's default of
                  # one connection per IP, a peer that drops a torrent mid-
                  # transfer (remove, re-add) leaves a stale connection that
                  # makes the seeder refuse every new loopback peer for it.
                  'allow_multiple_connections_per_ip': True,
                  'alert_mask': lt.alert.category_t.error_notification
                  | lt.alert.category_t.status_notification})

# Do not hand out a magnet until the TCP listener really exists.
PORT = None
deadline = time.time() + 10
while PORT is None and time.time() < deadline:
    ses.wait_for_alert(500)
    for a in ses.pop_alerts():
        if isinstance(a, lt.listen_failed_alert):
            sys.exit('seeder cannot listen: %s' % a.message())
        if isinstance(a, lt.listen_succeeded_alert) and 'TCP' in a.message():
            PORT = ses.listen_port()
if not PORT:
    sys.exit('seeder: no TCP listen_succeeded within 10 s')

handles, magnets = [], []
for path in payloads:
    ti = make_torrent(path)
    atp = lt.add_torrent_params()
    atp.ti = ti
    atp.save_path = os.path.dirname(path)
    atp.flags = lt.torrent_flags.seed_mode
    handles.append(ses.add_torrent(atp))
    magnets.append('magnet:?xt=urn:btih:%s&dn=%s&x.pe=127.0.0.1:%d'
                   % (str(ti.info_hashes().v1), ti.name(), PORT))
    print('seeding %s, %d bytes, on 127.0.0.1:%d' % (ti.name(), ti.total_size(), PORT), flush=True)

with open(os.path.join(BASE, 'magnet.txt'), 'w') as fh:
    fh.write('\n'.join(magnets) + '\n')
for m in magnets:
    print(m, flush=True)

deadline = time.time() + args.seconds
while time.time() < deadline:
    for h in handles:
        st = h.status()
        if st.num_peers:
            print('  seeder: %s peers=%d uploaded=%d'
                  % (st.name, st.num_peers, st.all_time_upload), flush=True)
    time.sleep(5)
