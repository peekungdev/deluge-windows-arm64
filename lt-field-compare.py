"""Print old (ABI-1) torrent_status fields next to their replacements.

Run once against 2.0.14 and once against 2.1.2 on the same torrent, to prove
the replacement expressions yield the values Deluge used to get. Uses a test
torrent from the Deluge sdist that install-deluge.sh fetches.
"""
import datetime
import os
import shutil
import tempfile
import time

import libtorrent as lt

data = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    'deluge-2.2.0', 'deluge', 'tests', 'data', 'test.torrent')
save = tempfile.mkdtemp(prefix='ltcmp')
s = lt.session({'enable_dht': False, 'enable_lsd': False, 'enable_upnp': False,
                'enable_natpmp': False, 'listen_interfaces': '127.0.0.1:0'})
atp = lt.add_torrent_params()
atp.ti = lt.torrent_info(data)
atp.save_path = save
h = s.add_torrent(atp)
time.sleep(3)
st = h.status()
print('libtorrent', lt.__version__)
for name in ('paused', 'auto_managed', 'seed_mode', 'super_seeding',
             'active_time', 'seeding_time', 'finished_time',
             'time_since_download', 'time_since_upload'):
    print('  old %-22s %r' % (name, getattr(st, name, '<absent>')))
print('  new flags                  %r' % int(st.flags))
for name in ('paused', 'auto_managed', 'seed_mode', 'super_seeding'):
    print('  new flags&%-15s %r' % (name, bool(st.flags & getattr(lt.torrent_flags, name))))
for name in ('active_duration', 'seeding_duration', 'finished_duration',
             'last_download', 'last_upload'):
    v = getattr(st, name, '<absent>')
    print('  new %-22s %r  (%s)' % (name, v, type(v).__name__))
ti = h.torrent_file()
print('  old file_at(0).path        %r' % (ti.file_at(0).path if hasattr(ti, 'file_at') else '<absent>'))
print('  new files().file_path(0)   %r' % ti.files().file_path(0))
print('  tracker alert: url attr=%s tracker_url()=%s' % (
    hasattr(lt.tracker_error_alert, 'url'), hasattr(lt.tracker_error_alert, 'tracker_url')))
s.remove_torrent(h)
shutil.rmtree(save, ignore_errors=True)
