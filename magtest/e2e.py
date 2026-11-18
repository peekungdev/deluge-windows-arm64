"""End-to-end check of a portable Deluge folder, using scratch state only.

    python magtest/e2e.py <portable folder> [--work DIR] [--no-gui]

Any Python 3 on Windows can run this. To use the folder's own, run
bin/python.exe -B magtest/e2e.py <folder>; -B keeps that Python from writing
__pycache__ into the folder. The steps:

1. seeder.py, run by the folder's own Python, seeds a fresh random 4 MiB
   payload on 127.0.0.1 and writes a magnet link for it.
2. The folder's deluged-debug.exe starts with a scratch config folder whose
   core.conf turns off UPnP, NAT-PMP, DHT, LSD and the release check, so the
   test talks to nothing but the seeder, and makes it listen on 127.0.0.1 on
   a port that is free for TCP and UDP (see write_core_conf).
3. e2e_client.py (the folder's Python again) adds the magnet, dials the
   seeder, waits until the torrent is complete and seeding, then shuts the
   daemon down.
4. The downloaded file's SHA-256 must equal the seeded payload's.
5. Unless --no-gui: Deluge.exe (GTK, standalone, scratch config) must open
   its main window, which appears on screen for a few seconds, and exit when
   that window is closed.

Your own Deluge settings are never read or written. If something already
listens on 127.0.0.1:58846 (a running Deluge daemon), the test refuses to
start. Every process it starts is created suspended, put into a job object
with kill-on-close and only then resumed, so it can only ever stop processes
it started itself.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time

from freeport import free_tcp_udp_port

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
ap.add_argument('bundle', help='the portable folder, e.g. Deluge-2.2.0-arm64')
ap.add_argument('--work', default=os.path.join(HERE, 'e2e-work'),
                help='scratch folder, emptied first (default: magtest/e2e-work)')
ap.add_argument('--no-gui', action='store_true', help='skip the GTK client step')
args = ap.parse_args()

BUNDLE, WORK = os.path.abspath(args.bundle), os.path.abspath(args.work)
BIN = os.path.join(BUNDLE, 'bin')
PY = os.path.join(BIN, 'python.exe')
RPC_PORT = 58846
if not os.path.isfile(os.path.join(BIN, 'deluged-debug.exe')):
    sys.exit('%s does not look like a portable Deluge folder' % BUNDLE)

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
u32 = ctypes.WinDLL('user32', use_last_error=True)
ntdll = ctypes.WinDLL('ntdll')
k32.CreateJobObjectW.restype = wt.HANDLE
k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
k32.QueryInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                          wt.DWORD, ctypes.c_void_p]
k32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
ntdll.NtResumeProcess.argtypes = [wt.HANDLE]
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
u32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
u32.IsWindowVisible.argtypes = [wt.HWND]
u32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]

CREATE_SUSPENDED = 0x4
CREATE_NO_WINDOW = 0x08000000
WM_CLOSE = 0x0010


class BASIC_LIMIT(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64),
                ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', wt.DWORD),
                ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', wt.DWORD),
                ('Affinity', ctypes.c_size_t),
                ('PriorityClass', wt.DWORD),
                ('SchedulingClass', wt.DWORD)]


class EXT_LIMIT(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', BASIC_LIMIT),
                ('IoInfo', ctypes.c_uint64 * 6),
                ('ProcessMemoryLimit', ctypes.c_size_t),
                ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t),
                ('PeakJobMemoryUsed', ctypes.c_size_t)]


class PID_LIST(ctypes.Structure):
    _fields_ = [('Assigned', wt.DWORD), ('InList', wt.DWORD), ('Ids', ctypes.c_size_t * 256)]


JOB = k32.CreateJobObjectW(None, None)
_lim = EXT_LIMIT()
_lim.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
if not k32.SetInformationJobObject(JOB, 9, ctypes.byref(_lim), ctypes.sizeof(_lim)):
    sys.exit('SetInformationJobObject failed: %d' % ctypes.get_last_error())

# The environment bin/*.exe sets up (see launcher/deluge-launcher.c), plus no
# bytecode, so the folder is left exactly as it was.
ENV = dict(os.environ)
ENV['PATH'] = BIN + ';' + ENV.get('PATH', '')
ENV['PYTHONHOME'] = BUNDLE
for _k, _tail in (('GI_TYPELIB_PATH', '/lib/girepository-1.0'),
                  ('GDK_PIXBUF_MODULE_FILE', '/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache'),
                  ('GDK_PIXBUF_MODULEDIR', '/lib/gdk-pixbuf-2.0/2.10.0/loaders'),
                  ('XDG_DATA_DIRS', '/share'),
                  ('GSETTINGS_SCHEMA_DIR', '/share/glib-2.0/schemas'),
                  ('OPENSSL_MODULES', '/lib/ossl-modules'),
                  ('OPENSSL_CONF', '/etc/ssl/openssl.cnf'),
                  ('SSL_CERT_FILE', '/etc/ssl/cert.pem')):
    ENV[_k] = BUNDLE + _tail
ENV['PYTHONDONTWRITEBYTECODE'] = '1'

QUIET_CORE = {'upnp': False, 'natpmp': False, 'dht': False, 'lsd': False,
              'new_release_check': False}
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print('%s  %s%s' % ('PASS' if ok else 'FAIL', name, ('  - ' + detail) if detail else ''),
          flush=True)
    return ok


def start(cmd, log, gui=False):
    flags = CREATE_SUSPENDED | (0 if gui else CREATE_NO_WINDOW)
    with open(log, 'w') as fh:
        p = subprocess.Popen(cmd, env=ENV, stdin=subprocess.DEVNULL, stdout=fh,
                             stderr=subprocess.STDOUT, creationflags=flags)
    if not k32.AssignProcessToJobObject(JOB, int(p._handle)):
        p.kill()
        sys.exit('AssignProcessToJobObject failed: %d' % ctypes.get_last_error())
    ntdll.NtResumeProcess(int(p._handle))
    return p


def job_pids():
    lst = PID_LIST()
    k32.QueryInformationJobObject(JOB, 3, ctypes.byref(lst), ctypes.sizeof(lst), None)
    return set(lst.Ids[:lst.InList])


def port_open(port):
    try:
        socket.create_connection(('127.0.0.1', port), 0.5).close()
        return True
    except OSError:
        return False


def wait_for(pred, timeout, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


def write_core_conf(cfg):
    """A partial core.conf; Deluge fills in defaults for everything else.

    The incoming port is pinned rather than left to Deluge, whose random port
    can fall inside a range Windows reserved at boot. libtorrent then cannot
    listen, and a session with no listen socket makes no outgoing connections
    either, so the magnet could never resolve.
    """
    port = free_tcp_udp_port()
    conf = dict(QUIET_CORE, random_port=False, listen_ports=[port, port],
                listen_interface='127.0.0.1')
    os.makedirs(cfg, exist_ok=True)
    with open(os.path.join(cfg, 'core.conf'), 'w') as fh:
        fh.write(json.dumps({'file': 1, 'format': 1}, indent=4))
        fh.write(json.dumps(conf, indent=4))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def find_window():
    pids = job_pids()
    found = []

    def cb(hwnd, _):
        pid = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and u32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(hwnd, buf, 256)
            if 'Deluge' in buf.value:
                found.append((hwnd, buf.value, pid.value))
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


def main():
    if port_open(RPC_PORT):
        sys.exit('127.0.0.1:%d is already in use (a running Deluge daemon?) - not touching it'
                 % RPC_PORT)
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)

    # 1. seeder
    mfile = os.path.join(HERE, 'magnet.txt')
    for f in (mfile, os.path.join(HERE, 'payload.sha256')):
        if os.path.exists(f):
            os.remove(f)
    start([PY, os.path.join(HERE, 'seeder.py'), '900'], os.path.join(WORK, 'seeder.log'))
    if not check('seeder (the folder\'s Python and libtorrent) is listening',
                 wait_for(lambda: os.path.exists(mfile) and os.path.getsize(mfile), 30)):
        return
    with open(mfile) as fh:
        magnet = fh.read().split()[0]

    # 2. daemon
    cfg = os.path.join(WORK, 'daemon-cfg')
    write_core_conf(cfg)
    daemon = start([os.path.join(BIN, 'deluged-debug.exe'), '-c', cfg, '-L', 'info',
                    '-l', os.path.join(WORK, 'deluged.log')], os.path.join(WORK, 'deluged.out'))
    auth = os.path.join(cfg, 'auth')
    if not check('deluged-debug.exe accepts connections on 127.0.0.1:%d' % RPC_PORT,
                 wait_for(lambda: port_open(RPC_PORT) and os.path.exists(auth), 60)):
        return
    with open(auth) as fh:
        pw = next(ln.split(':')[1] for ln in fh if ln.startswith('localclient:'))

    # 3. magnet -> metadata -> download -> seeding -> daemon shutdown
    dl = os.path.join(WORK, 'downloads')
    os.makedirs(dl)
    clog = os.path.join(WORK, 'client.log')
    client = start([PY, os.path.join(HERE, 'e2e_client.py'), pw, magnet, dl], clog)
    try:
        code = client.wait(240)
    except subprocess.TimeoutExpired:
        code = 'timeout'
    with open(clog) as fh:
        print(fh.read().rstrip(), flush=True)
    check('magnet resolved, downloaded and seeding', code == 0, 'client exit %s' % code)
    try:
        dcode = daemon.wait(60)
    except subprocess.TimeoutExpired:
        dcode = 'still running'
    check('daemon shut down cleanly', dcode == 0, 'exit %s' % dcode)

    # 4. data
    with open(os.path.join(HERE, 'payload.sha256')) as fh:
        want = fh.read().strip()
    got_path = os.path.join(dl, 'magnet-payload', 'data.bin')
    got = sha256(got_path) if os.path.exists(got_path) else 'missing'
    check('downloaded file has the seeded payload\'s SHA-256', got == want, got[:16])

    # 5. GTK client, standalone
    if args.no_gui:
        return
    gcfg = os.path.join(WORK, 'gtk-cfg')
    write_core_conf(gcfg)  # the standalone client runs its own core from this folder
    t0 = time.time()
    start([os.path.join(BIN, 'Deluge.exe'), '-c', gcfg, '-L', 'info',
           '-l', os.path.join(WORK, 'gtk.log')], os.path.join(WORK, 'gtk.out'), gui=True)
    win = wait_for(find_window, 60, 0.5)
    if not check('Deluge.exe opened its main window', win,
                 win and '"%s" after %.1f s' % (win[1], time.time() - t0)):
        return
    time.sleep(3)  # let the standalone core finish starting
    u32.PostMessageW(win[0], WM_CLOSE, 0, 0)
    check('GTK client exited after its window was closed',
          wait_for(lambda: win[2] not in job_pids(), 45, 0.5))


try:
    main()
finally:
    k32.TerminateJobObject(JOB, 1)  # the seeder, and anything that did not exit
    print('%d/%d checks passed (logs in %s)' % (sum(results), len(results), WORK), flush=True)
    sys.exit(0 if results and all(results) else 1)
