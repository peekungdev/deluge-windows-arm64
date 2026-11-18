Deluge 2.2.0 - native Windows 11 ARM64 (aarch64)
================================================

A self-contained build of the Deluge BitTorrent client for ARM64 Windows.
Everything here is native aarch64 - there is no x64 emulation anywhere in the
stack, including the interpreter, GTK and libtorrent.

    Deluge          2.2.0
    libtorrent      2.1.2   (built from source, linked statically)
    Python          3.14.10
    Twisted         26.10.0
    GTK             3.24.52 on GLib 2.90.1
    Toolchain       clang 23 (MSYS2 CLANGARM64), Boost 1.92, OpenSSL 3.6.5

    Last updated 2026-11-13.


Running it
----------

The folder is portable - unzip it anywhere and run it; nothing needs to be on
PATH and no MSYS2 installation is required.

    bin/Deluge.exe            the GTK client (this is the one you want)
    bin/deluged.exe           the daemon, no console window
    bin/deluge-web.exe        the Web UI, default http://localhost:8112
    bin/deluge-console.exe    the console client
    bin/deluged-debug.exe     daemon, keeps a console for log output
    bin/deluge-web-debug.exe  Web UI, keeps a console for log output

Config lives in %APPDATA%/deluge by default; pass -c <dir> to relocate it,
which is also how you keep a fully portable install.


Known issue: hybrid torrents added by a v1-only magnet
------------------------------------------------------

If a magnet link carries only a v1 hash (xt=urn:btih:...) and the torrent
turns out to be a hybrid v1+v2 torrent, Deluge loses track of it once the
metadata arrives: it downloads and seeds normally, but Deluge keeps showing it
as "Downloading" with no files. libtorrent's handle.info_hash() returns the
"best" hash, which switches from v1 to v2 when the metadata reveals a v2 hash,
and Deluge keys every torrent by that value.

This is a pre-existing Deluge 2.2.0 bug, NOT caused by libtorrent 2.1 - it
behaves identically on libtorrent 2.0.14, and upstream Deluge (develop,
2026-09) still keys torrents by info_hash() in 22 places. It is not fixed here
because a correct fix changes the IDs of hybrid torrents already saved in
people's state files, which needs a migration. The ID stays stable whenever
the metadata is known from the start - adding the .torrent file, or a magnet
that also carries the v2 hash (xt=urn:btmh:...).


What had to be changed to make this work
----------------------------------------

Deluge 2.2.0 predates Python 3.14, the current MSYS2 package set and libtorrent
2.1, and Twisted 26 has regressed its Windows GTK support, so six things needed
fixing. All are applied by the build scripts (see Rebuilding below) and are
idempotent.

1. libtorrent Python bindings did not exist for this platform.
   MSYS2 ships libtorrent without Python bindings, and no ARM64 wheel exists.
   libtorrent is compiled from source against MSYS2's Boost.Python (which
   already targets Python 3.14), producing
   libtorrent.cp314-mingw_aarch64_ucrt_llvm.pyd with libtorrent linked in
   statically. 2.1.2 is the newest libtorrent release - there is no 2.2 - and
   replaced the original 2.0.14 on 2026-09-28; see fix 6.

   clang 23's libc++ stopped pulling <algorithm> and <iterator> in
   transitively, and two files in the 2.1.2 tree relied on it
   (src/escape_string.cpp, and configuration.cpp in the bundled
   libdatachannel used for WebTorrent). Both are fixed upstream with exactly
   one #include each, but not yet in a tagged release, so
   patches/patch-libtorrent-libcxx-includes.py backports those two lines.
   Drop it once a libtorrent release ships them.

2. pywin32 cannot exist on this interpreter.
   Deluge imports six pywin32 modules on Windows, unguarded. pywin32's binary
   extensions are built for MSVC CPython and there is no win_arm64 wheel for
   this MinGW interpreter either. Every call Deluge makes is a thin wrapper
   over a documented Win32 API, so those are reimplemented with ctypes:
   SetConsoleCtrlHandler, GetFileAttributes, GetLastError, CloseHandle,
   CreateMutex, GetDiskFreeSpaceEx, EnumProcesses and the relevant constants.
   See lib/python3.14/site-packages/pywin32-306.dist-info/METADATA - it is
   deliberately explicit that this is a stand-in, not the real pywin32. The
   accompanying dist-info is required, not decoration: Deluge resolves its own
   declared dependencies through pkg_resources when loading UI entry points
   and when activating plugin eggs.

3. Twisted 26 broke the GTK reactor on Windows, in two separate ways.

   a) twisted/internet/_glibbase.py hardcodes GlibWaker's base class to
      _UnixWaker, which is built on os.pipe() and twisted.internet.fdesc - and
      fdesc is only imported on POSIX. Any glib/gtk3 reactor therefore died at
      startup with "NameError: name 'fdesc' is not defined". _signals.py
      already selects the correct waker per platform as _Waker, so the patch
      uses that.

   b) More seriously, PortableGIReactor is no longer portable. It now derives
      from the same GlibReactorBase as the POSIX reactor, which watches
      descriptors through GLib IO watches - and a Windows SOCKET is not a
      GLib-watchable file descriptor, so read and write events are never
      delivered. Sockets connect and then nothing moves:

          Sent 30 B (0.0 KiB/s) Recv 0 B (0.0 KiB/s)

      This is what breaks thin-client mode: the GTK UI talks to deluged over
      Twisted, so the RPC never completes and the Connection Manager reports
      every daemon as Offline with Connect greyed out. Standalone mode is
      unaffected only because libtorrent does its own networking in C++.
      Twisted used to ship the fix - PortableGlibReactorBase, a SelectReactor
      subclass that keeps Twisted's select() loop for sockets and merely pumps
      the glib main loop on a timer. It was dropped; the vestigial no-op
      PortableGIReactor.simulate() is still there as evidence. The patch
      restores that class and points PortableGIReactor at it.
      Re-run verify-reactor.py after any Twisted, GLib or GTK update;
      it must print PONG:PING. Twisted 26.10 still ships both defects
      unchanged (unpatched it dies with the fdesc NameError); verified with
      the patches against Twisted 26.10 and GLib 2.90.1.

4. pyOpenSSL 26 removed the API Deluge used to make its daemon certificate.
   OpenSSL.crypto.X509Req is gone, so deluged died on first run with
   "module 'OpenSSL.crypto' has no attribute 'X509Req'". The CSR was pointless
   anyway - it only carried the subject name into a self-signed certificate -
   so generate_ssl_keys() was rewritten on `cryptography`, which pyOpenSSL is
   itself built on. Same PEM formats out, so Twisted still loads them.

5. The single-instance IPC socket picked a random, possibly illegal port.
   ipcinterface.py bound random.randrange(20000, 65535) directly. Windows
   reserves large blocks of that range for Hyper-V, WSL and Docker (see
   "netsh interface ipv4 show excludedportrange protocol=tcp"), and landing in
   one fails the bind with WinError 10013, killing Deluge before the UI
   appears - intermittently, so it reads as "Deluge randomly won't start".
   It now binds port 0 and asks the OS for the port it got. The same patch
   stops Deluge dying with FileNotFoundError when the global mutex outlives
   its socket file, which is what happens after an instance is killed.

6. Deluge 2.2.0 does not work with libtorrent 2.1 at all.
   libtorrent 2.1 builds with TORRENT_ABI_VERSION=2 (2.0 used 1), dropping
   everything deprecated in 1.1 and earlier, and it removes several settings
   outright. Unpatched, Deluge cannot even create its session:

       KeyError: 'unknown name in settings_pack: ignore_resume_timestamps'

   and past that, alert handlers raise on removed attributes - silently,
   because Deluge runs them via reactor.callLater - so adding any torrent
   never completes and magnets never resolve. Upstream Deluge has not fixed
   any of this. patches/patch-deluge-libtorrent21.py rewrites ~20 sites:
   removed ABI-1 API (enc_level aliases, get_torrent_info, handle.is_paused,
   file_at, tracker alert .url, and the torrent_status paused / auto_managed
   / seed_mode / super_seeding / *_time / time_since_* fields), the
   wait_for_alert() return value (now a bool, not alert-or-None), and six
   removed settings. Five of those settings were already never read by
   libtorrent 2.0, so dropping them changes nothing; the sixth,
   ignore_limits_on_local_network, was live and is reproduced exactly through
   set_peer_class_filter(). (libtorrent's own IPv6 link-local range there is a
   malformed address it silently skips, so it is skipped here too.)

   Every replacement also exists in libtorrent 2.0, and each was checked to
   return the identical value there. Deluge's own core test suite:

                              Deluge unpatched     Deluge patched
       libtorrent 2.0.14      119 pass, 1 fail     119 pass, 1 fail
       libtorrent 2.1.2       64 errors, hangs     119 pass, 1 fail

   (The one failure is test_test_listen_port, which asks an external service
   whether this machine's port is reachable - environmental.) Also verified
   end to end: a bare v1 magnet fetched its metadata from a peer and downloaded
   byte-identical data, shown correctly in the GTK thin client.

Separately, setuptools 83 no longer ships pkg_resources, which Deluge's plugin
loader needs. Rather than downgrade the whole toolchain, pkg_resources from
setuptools 80.9.0 is installed alongside; it is unvendored in that release and
runs against the current `packaging` and `jaraco.text`.

One cosmetic upstream bug is also fixed: ConsoleUI.start() fired
self.started_deferred before start_console() created it, so every non-
interactive "deluge-console connect ..." printed an AttributeError traceback.


Rebuilding
----------

Everything needed is in the build repository,
https://github.com/peekungdev/deluge-windows-arm64 . In an MSYS2 CLANGARM64
shell, from a checkout of it:

    ./build-libtorrent.sh                    libtorrent + Python bindings
    ./install-deluge.sh                      deps, shim, Deluge, patches
    ./deploy.sh                              assemble this folder in dist/
    makensis installer/deluge.nsi            the installer, also in dist/

    patches/                                 the source patches (six for Deluge
                                             and Twisted, one for libtorrent)
    launcher/deluge-launcher.c               the bin/*.exe launchers

What goes into lib/python3.14/site-packages is an allowlist, not a copy of
MSYS2's: collect-site-packages.py walks the requirement closure of Deluge (with
its "all" extra), PyGObject, pycairo and what pkg_resources needs, and copies
the files each distribution's RECORD lists. prune-pixbuf-loaders.py does the
same for gdk-pixbuf's image loaders. Until 2026-11 the bundle took everything
installed in MSYS2 minus a short exclude list, which quietly shipped 44 MB of
unrelated packages (OpenEXR's imath, VapourSynth, Meson) plus the DLLs behind
them once those appeared in MSYS2. deploy.sh is also reproducible: two
consecutive runs produce byte-identical bundles, so a fresh build can be
proven identical to the one that was tested.

Checks - run after any libtorrent, Twisted, GLib or GTK change:

    verify-lt-api.py                         every libtorrent API Deluge uses
                                             still exists (static; exit 1 if not)
    verify-reactor.py                        GTK reactor socket I/O (fix 3b)
    verify-bundle-imports.py                 imports all 152 Deluge modules and
                                             loads all 32 UI and plugin entry
                                             points; run it with the bundle's
                                             python and MSYS2's - a failure only
                                             in the bundle is an allowlist gap
    stage-tests.sh +                         Deluge's own core test suite
      run-core-tests.sh                      against the installed, patched
                                             Deluge, in an isolated venv
    magtest/seeder.py                        local seeder for a real magnet test;
                                             binds an OS-chosen port, because a
                                             fixed one can fall inside a range
                                             Windows reserved at boot

The launchers are custom because pip's generated .exe stubs embed an absolute
path to the interpreter that built them, which makes them non-relocatable.
These resolve their own location instead and set PYTHONHOME, GI_TYPELIB_PATH,
GDK_PIXBUF_MODULE_FILE, XDG_DATA_DIRS, GSETTINGS_SCHEMA_DIR and the OpenSSL
module/config paths before handing off to lib/deluge-scripts/<name>.

Deluge is GPL-3.0-or-later; see the LICENSE under
lib/python3.14/site-packages/deluge-2.2.0.dist-info/licenses/.
