#!/usr/bin/env python3
"""Make Deluge 2.2.0 work with libtorrent 2.1.

libtorrent 2.1 builds with TORRENT_ABI_VERSION=2 by default (2.0 used 1), which
drops everything deprecated in libtorrent 1.1 and earlier, and it removes a
batch of settings outright. Unpatched, Deluge cannot even create its session:

    KeyError: 'unknown name in settings_pack: ignore_resume_timestamps'

and 64 of Deluge's own core tests error at setup. Upstream Deluge (develop, as
of 2026-09) has not fixed any of this. Every replacement below also exists in
libtorrent 2.0, so the patched code works on both series.

API removed with ABI version 1:
  lt.enc_level.plaintext/rc4/both     -> lt.enc_level.pe_plaintext/pe_rc4/pe_both
      (the short names were ABI-1-only aliases; applied at every daemon start)
  torrent_handle.get_torrent_info()   -> torrent_handle.torrent_file()
      (two sites, both on the magnet path: metadata received, and the metadata
       prefetch the Add Torrent dialog uses - every magnet add would crash)
  torrent_handle.is_paused()          -> handle.flags() & lt.torrent_flags.paused
      (saving state while the session is paused - would lose torrents.state)

Fields on objects libtorrent returns, also ABI-1-only (found by running
Deluge's own test suite - an alert handler raising here is swallowed by
reactor.callLater, so adding any torrent simply never completed):
  torrent_status.paused/auto_managed  -> _is_paused(status)/_is_auto_managed(status)
      (9 sites in torrent.py, rewritten by regex so none can be missed)
  torrent_status.seed_mode/super_seeding
                                      -> bool(status.flags & lt.torrent_flags.X)
  torrent_status.active_time/seeding_time/finished_time
                                      -> int(status.X_duration.total_seconds())
  torrent_status.time_since_download/time_since_upload
                                      -> _seconds_since(status.last_download/..)
      (int seconds, -1 if never - libtorrent 2.0's own formula; see helper)
  torrent_info.file_at(0).path        -> torrent_info.files().file_path(0)
  tracker alert .url                  -> alert.tracker_url()
  Each replacement was checked against 2.0.14, where old and new coexist, and
  returns the identical value.

Changed return value:
  session.wait_for_alert()            returned an alert or None in 2.0; returns
      a bool in 2.1. Deluge's alert poller tested `is None`, which can never be
      true on 2.1, so the timeout guard never fires. Testing truthiness is
      correct for both (None/alert on 2.0, False/True on 2.1).

Settings removed in 2.1:
  ignore_resume_timestamps, cache_size, cache_expiry, half_open_limit,
  force_proxy
      Already TORRENT_DEPRECATED_ENUM in 2.0.14 and never read anywhere in its
      source - libtorrent accepted and ignored them. Not forwarding them is
      behaviour-preserving. Deluge's own config keys are kept so existing
      configs load and the preference widgets still work (as the no-ops they
      already were).
  ignore_limits_on_local_network
      This one WAS live in 2.0.14: it switched session_impl between two
      peer-class filters. It is reproduced exactly through the public
      set_peer_class_filter() API, using the same ranges and classes as
      libtorrent's own init_peer_class_filter() (identical in 2.0.14 and
      2.1.2). With the default (True) this matches libtorrent's own default.
      libtorrent's IPv6 link-local entry is a malformed address that it
      silently skips, so it is omitted here too (see PEER_CLASS_HANDLER).

Idempotent: safe to re-run.
"""

import argparse
import os
import re
import shutil
import sys
import sysconfig

# The ranges libtorrent's init_peer_class_filter() puts in the local peer class,
# taken from session_impl.cpp (identical in 2.0.14 and 2.1.2).
#
# One entry is deliberately left out. libtorrent's IPv6 link-local rule ends at
# "febf::ffff:ffff:ffff:ffff:ffff:ffff:ffff" - "febf", "::" and seven more
# groups, more than IPv6's eight - which is not a valid address. libtorrent's
# C++ loop does `if (ec) continue;` on a parse error, so that rule has never
# actually been applied by libtorrent. The Python binding's add_rule() raises
# instead (WinError 10022), which in an earlier revision of this patch aborted
# the rest of PreferencesManager.start() and hung Deluge. Omitting it reproduces
# the filter libtorrent really builds. (The range it evidently intended is
# fe80::/10, i.e. up to febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff - adding that
# would be a deliberate behaviour change, not a compatibility fix.)
PEER_CLASS_HANDLER = '''    def _on_set_ignore_limits_on_local_network(self, key, value):
        # libtorrent 2.1 removed the ignore_limits_on_local_network setting. It
        # only ever chose between two peer-class filters, so build the same
        # filter libtorrent's init_peer_class_filter() does: everything in the
        # global (rate-limited) class, plus - when enabled - private, link-local
        # and loopback ranges in the local (unlimited) class. libtorrent's own
        # IPv6 link-local entry is malformed and it silently skips it, so it is
        # omitted here too; see patches/patch-deluge-libtorrent21.py.
        global_class = 1 << lt.session.global_peer_class_id
        local_class = 1 << lt.session.local_peer_class_id
        peer_class_filter = lt.ip_filter()
        peer_class_filter.add_rule('0.0.0.0', '255.255.255.255', global_class)
        peer_class_filter.add_rule(
            '::0', 'ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff', global_class
        )
        if value:
            for first, last in (
                ('10.0.0.0', '10.255.255.255'),
                ('172.16.0.0', '172.31.255.255'),
                ('192.168.0.0', '192.168.255.255'),
                ('169.254.0.0', '169.254.255.255'),
                ('127.0.0.0', '127.255.255.255'),
                ('fc00::', 'fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff'),
                ('::1', '::1'),
            ):
                peer_class_filter.add_rule(first, last, local_class)
        self.core.session.set_peer_class_filter(peer_class_filter)
'''

TORRENT_HELPERS = '''

def _is_paused(status):
    """torrent_status.paused, which libtorrent 2.1 removed (ABI 1 only)."""
    return bool(status.flags & lt.torrent_flags.paused)


def _is_auto_managed(status):
    """torrent_status.auto_managed, which libtorrent 2.1 removed (ABI 1 only)."""
    return bool(status.flags & lt.torrent_flags.auto_managed)


def _seconds_since(time_point):
    """Seconds since a libtorrent time point, or -1 if it was never set.

    Reproduces torrent_status.time_since_download/time_since_upload, which
    libtorrent 2.1 removed (ABI 1 only). The bindings expose last_download and
    last_upload as naive local-time datetimes, or None when unset, and
    libtorrent 2.0 computed the old value as int(now - last) seconds.
    """
    if time_point is None:
        return -1
    return int((datetime.datetime.now() - time_point).total_seconds())
'''

NOOP_NOTE = (
    '        # libtorrent 2.1 removed this setting; it was already deprecated and\n'
    '        # never read by libtorrent 2.0, so there is nothing to forward.\n'
    '        pass\n'
)

EDITS = {
    'core/alertmanager.py': [
        (
            '            if self.session.wait_for_alert(1000) is None:\n',
            '            # libtorrent 2.1 removed the alert-or-None return; it returns a\n'
            '            # bool now. Truthiness is correct for both series.\n'
            '            if not self.session.wait_for_alert(1000):\n',
        ),
    ],
    'core/core.py': [
        (
            "            'user_agent': user_agent,\n"
            "            'ignore_resume_timestamps': True,\n",
            "            'user_agent': user_agent,\n"
            "            # ignore_resume_timestamps: libtorrent 2.1 removed the setting;\n"
            "            # libtorrent 2.0 accepted but never read it.\n",
        ),
    ],
    'core/preferencesmanager.py': [
        (
            '            0: lt.enc_level.plaintext,\n'
            '            1: lt.enc_level.rc4,\n'
            '            2: lt.enc_level.both,\n',
            '            # The short plaintext/rc4/both aliases were ABI-1-only and\n'
            '            # libtorrent 2.1 removed them; the pe_ names exist in both.\n'
            '            0: lt.enc_level.pe_plaintext,\n'
            '            1: lt.enc_level.pe_rc4,\n'
            '            2: lt.enc_level.pe_both,\n',
        ),
        (
            '    def _on_set_max_half_open_connections(self, key, value):\n'
            "        self.core.apply_session_setting('half_open_limit', value)\n",
            '    def _on_set_max_half_open_connections(self, key, value):\n'
            + NOOP_NOTE,
        ),
        (
            '    def _on_set_ignore_limits_on_local_network(self, key, value):\n'
            "        self.core.apply_session_setting('ignore_limits_on_local_network', value)\n",
            PEER_CLASS_HANDLER,
        ),
        (
            "            'force_proxy': value['force_proxy'],\n",
            "            # force_proxy: libtorrent 2.1 removed the setting; libtorrent\n"
            "            # 2.0 accepted but never read it.\n",
        ),
        (
            '    def _on_set_cache_size(self, key, value):\n'
            "        self.core.apply_session_setting('cache_size', value)\n",
            '    def _on_set_cache_size(self, key, value):\n' + NOOP_NOTE,
        ),
        (
            '    def _on_set_cache_expiry(self, key, value):\n'
            "        self.core.apply_session_setting('cache_expiry', value)\n",
            '    def _on_set_cache_expiry(self, key, value):\n' + NOOP_NOTE,
        ),
    ],
    'core/torrent.py': [
        (
            '        self.torrent_info = self.handle.get_torrent_info()\n',
            '        # get_torrent_info() was ABI-1-only; libtorrent 2.1 removed it.\n'
            '        self.torrent_info = self.handle.torrent_file()\n',
        ),
        (
            'import logging\nimport os\n',
            'import datetime\nimport logging\nimport os\n',
        ),
        (
            'log = logging.getLogger(__name__)\n',
            'log = logging.getLogger(__name__)\n' + TORRENT_HELPERS,
        ),
        (
            '        time_since = (self.status.time_since_download, self.status.time_since_upload)\n',
            '        # time_since_download/_upload were ABI-1-only; libtorrent 2.1\n'
            '        # removed them.\n'
            '        time_since = (\n'
            '            _seconds_since(self.status.last_download),\n'
            '            _seconds_since(self.status.last_upload),\n'
            '        )\n',
        ),
        (
            "            'active_time': lambda: self.status.active_time,\n"
            "            'seeding_time': lambda: self.status.seeding_time,\n"
            "            'finished_time': lambda: self.status.finished_time,\n",
            "            # The *_time fields were ABI-1-only; libtorrent 2.1 removed them\n"
            "            # in favour of the *_duration timedeltas.\n"
            "            'active_time': lambda: int(\n"
            "                self.status.active_duration.total_seconds()\n"
            "            ),\n"
            "            'seeding_time': lambda: int(\n"
            "                self.status.seeding_duration.total_seconds()\n"
            "            ),\n"
            "            'finished_time': lambda: int(\n"
            "                self.status.finished_duration.total_seconds()\n"
            "            ),\n",
        ),
        (
            "            'seed_mode': lambda: self.status.seed_mode,\n"
            "            'super_seeding': lambda: self.status.super_seeding,\n"
            "            'time_since_download': lambda: self.status.time_since_download,\n"
            "            'time_since_upload': lambda: self.status.time_since_upload,\n",
            "            # seed_mode/super_seeding and time_since_* were ABI-1-only;\n"
            "            # libtorrent 2.1 removed them.\n"
            "            'seed_mode': lambda: bool(\n"
            "                self.status.flags & lt.torrent_flags.seed_mode\n"
            "            ),\n"
            "            'super_seeding': lambda: bool(\n"
            "                self.status.flags & lt.torrent_flags.super_seeding\n"
            "            ),\n"
            "            'time_since_download': lambda: _seconds_since(\n"
            "                self.status.last_download\n"
            "            ),\n"
            "            'time_since_upload': lambda: _seconds_since(\n"
            "                self.status.last_upload\n"
            "            ),\n",
        ),
    ],
    'core/torrentmanager.py': [
        (
            '                paused = torrent.handle.is_paused()\n',
            '                # is_paused() was ABI-1-only; libtorrent 2.1 removed it.\n'
            '                paused = bool(torrent.handle.flags() & lt.torrent_flags.paused)\n',
        ),
        (
            '            torrent_info = alert.handle.get_torrent_info()\n',
            '            # get_torrent_info() was ABI-1-only; libtorrent 2.1 removed it.\n'
            '            torrent_info = alert.handle.torrent_file()\n',
        ),
        (
            '                name = (\n'
            '                    torrent_info.file_at(0).path',
            '                # file_at() was ABI-1-only; libtorrent 2.1 removed it.\n'
            '                name = (\n'
            '                    torrent_info.files().file_path(0)',
        ),
        (
            "            if tracker['url'] == alert.url:\n",
            '            # alert.url was ABI-1-only; libtorrent 2.1 removed it.\n'
            "            if tracker['url'] == alert.tracker_url():\n",
        ),
    ],
}


# Attribute reads with many call sites, rewritten mechanically so none can be
# missed (an earlier revision hand-patched one of nine `status.paused` sites).
# Applied to code lines only - never comments - after EDITS.
REGEX_EDITS = {
    'core/torrent.py': [
        (re.compile(r'\b((?:self\.)?status)\.paused\b'), r'_is_paused(\1)'),
        (re.compile(r'\b((?:self\.)?status)\.auto_managed\b'), r'_is_auto_managed(\1)'),
    ],
}


def already_applied(src, old, new):
    """True if `new` is already in `src`.

    For an insertion (old survives inside new) the full `new` text can stop
    matching if the inserted block is later revised, which would insert it a
    second time; so for insertions, test for the first inserted line instead.
    """
    if new in src:
        return True
    if old in new:
        inserted = [ln for ln in new.replace(old, '', 1).splitlines() if ln.strip()]
        return bool(inserted) and inserted[0] in src
    return False


def regex_rewrite(src, rules):
    """Apply regex rules to non-comment lines; return (new_src, n_changes)."""
    out, changes = [], 0
    for line in src.splitlines(keepends=True):
        if not line.lstrip().startswith('#'):
            for pattern, repl in rules:
                line, n = pattern.subn(repl, line)
                changes += n
        out.append(line)
    return ''.join(out), changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site-packages', default=sysconfig.get_path('platlib'))
    args = ap.parse_args()
    root = os.path.join(args.site_packages, 'deluge')

    sources = {}
    for rel in set(EDITS) | set(REGEX_EDITS):
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            sys.exit('not found: %s' % path)
        with open(path, encoding='utf-8') as fh:
            sources[rel] = fh.read()

    # Idempotent per edit rather than per file, so adding an edit to this
    # script later still applies cleanly on top of an earlier run. Everything
    # is validated before anything is written, so a mismatch never leaves
    # Deluge half-patched.
    pending = {}
    for rel, edits in EDITS.items():
        for old, new in edits:
            if already_applied(sources[rel], old, new):
                continue
            n = sources[rel].count(old)
            if n != 1:
                sys.exit(
                    'unexpected %s: %d matches for %r' % (rel, n, old.strip()[:60])
                )
            pending.setdefault(rel, []).append((old, new))

    new_sources, n_edits = {}, 0
    for rel, edits in pending.items():
        src = sources[rel]
        for old, new in edits:
            src = src.replace(old, new, 1)
        new_sources[rel] = src
        n_edits += len(edits)
    n_rewrites = 0
    for rel, rules in REGEX_EDITS.items():
        src, n = regex_rewrite(new_sources.get(rel, sources[rel]), rules)
        if n:
            new_sources[rel] = src
            n_rewrites += n

    if not new_sources:
        print('deluge libtorrent 2.1 compatibility: already patched')
        return

    for rel, src in new_sources.items():
        path = os.path.join(root, rel)
        if not os.path.exists(path + '.pre-lt21'):
            shutil.copyfile(path, path + '.pre-lt21')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(src)

    cache = os.path.join(root, 'core', '__pycache__')
    if os.path.isdir(cache):
        stems = {os.path.splitext(os.path.basename(rel))[0] for rel in new_sources}
        for f in os.listdir(cache):
            if f.split('.')[0] in stems:
                os.remove(os.path.join(cache, f))

    print(
        'deluge libtorrent 2.1 compatibility: patched OK '
        '(%d edits, %d attribute rewrites, %d files)'
        % (n_edits, n_rewrites, len(new_sources))
    )


if __name__ == '__main__':
    main()
