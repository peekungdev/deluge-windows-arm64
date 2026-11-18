"""Does handle.info_hash() change once a v1 magnet's metadata reveals a hybrid
torrent? Joins the running seeder with a plain libtorrent session - no Deluge.

    python seeder.py --hybrid     (in another shell)
    python hybrid_hash.py

It does, on libtorrent 2.0.14 and 2.1.2 alike: info_hash() returns the "best"
hash, which switches from v1 to v2 when the metadata arrives. Deluge keys every
torrent by info_hash(), so such a torrent downloads but stays "Downloading" with
no files in Deluge - a pre-existing Deluge 2.2.0 bug, not a libtorrent 2.1 one.
"""
import os
import re
import tempfile
import time

import libtorrent as lt

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'magnet.txt')) as fh:
    magnet = fh.readline().strip()
peer_host, peer_port = re.search(r'x\.pe=([^&:]+):(\d+)', magnet).groups()

ses = lt.session({'listen_interfaces': '127.0.0.1:0', 'enable_dht': False,
                  'enable_lsd': False, 'enable_upnp': False, 'enable_natpmp': False})
atp = lt.parse_magnet_uri(magnet)
atp.save_path = tempfile.mkdtemp(prefix='hyb')
h = ses.add_torrent(atp)
before = str(h.info_hash())
h.connect_peer((peer_host, int(peer_port)))
for _ in range(60):
    if h.status().has_metadata:
        break
    time.sleep(0.25)
ih = h.info_hashes()
print('libtorrent %-9s before metadata info_hash()=%s' % (lt.__version__, before[:12]))
print('                     after  metadata info_hash()=%s  v1=%s  has_v2=%s  has_metadata=%s'
      % (str(h.info_hash())[:12], str(ih.v1)[:12], ih.has_v2(), h.status().has_metadata))
