"""Check every libtorrent API Deluge uses still exists in the built bindings.

A libtorrent upgrade can break Deluge in ways that only surface when a given
code path runs - and in alert handlers the exception is swallowed by
reactor.callLater, so the symptom is a hang, not a traceback. libtorrent 2.1
dropped everything under TORRENT_ABI_VERSION 1 and changed several return
types; Deluge 2.2.0 tripped over ~20 of those sites (see
patches/patch-deluge-libtorrent21.py).

This tokenizes the installed Deluge package - so comments, docstrings and
string literals can never produce a hit - and resolves every reference against
the libtorrent module actually installed:

  lt.X.Y...            module attributes
  handle.X(            torrent_handle methods
  session.X(           session methods
  status.X             torrent_status fields
  torrent_info.X       torrent_info members
  peer.X               peer_info fields
  tracker.X            announce_entry members
  alert.X              members of any *_alert class

It also scans the plugin .egg archives for module attributes.

The receiver names are heuristics, so a few Python-level names collide with
them; those are listed in ALLOWED with the reason, and nothing else is exempt.

Run after any libtorrent version change or Deluge patch:
    python verify-lt-api.py
Exits non-zero if anything Deluge references is missing.

Note this is a static check. It cannot see settings passed as strings (e.g.
'ignore_resume_timestamps', removed in 2.1) or changed return *types*
(wait_for_alert() now returns bool, not alert-or-None). Deluge's own test
suite - run-core-tests.sh - is what catches those.
"""

import io
import os
import sys
import tokenize
import zipfile

import deluge
import libtorrent as lt

ROOT = os.path.dirname(deluge.__file__)

ALERT_MEMBERS = set()
for _name in dir(lt):
    _cls = getattr(lt, _name)
    if isinstance(_cls, type) and _name.endswith('_alert'):
        ALERT_MEMBERS |= set(dir(_cls))

# receiver name -> (what it is in libtorrent, how to test a member)
RECEIVERS = {
    'handle': ('torrent_handle', lambda a: hasattr(lt.torrent_handle, a)),
    'session': ('session', lambda a: hasattr(lt.session, a)),
    'status': ('torrent_status', lambda a: hasattr(lt.torrent_status, a)),
    'torrent_info': ('torrent_info', lambda a: hasattr(lt.torrent_info, a)),
    'peer': ('peer_info', lambda a: hasattr(lt.peer_info, a)),
    'tracker': ('announce_entry', lambda a: hasattr(lt.announce_entry, a)),
    'alert': ('*_alert', lambda a: a in ALERT_MEMBERS),
}
# handle/session only count as libtorrent when called, to skip e.g.
# `self.session` attribute plumbing; field receivers count on any access.
CALL_ONLY = {'handle', 'session'}
# Real libtorrent objects only exist in the daemon (core/). The UIs receive
# plain dicts over RPC - and Deluge's own ui.common.TorrentInfo class - so a
# `status.x` or `torrent_info.x` there is never libtorrent.
FIELD_RECEIVERS = set(RECEIVERS) - CALL_ONLY

ALLOWED = {
    ('torrent_status', 'setter'): '@status.setter property decorator in torrent.py',
    ('torrent_status', 'update'): 'dict.update() on the status dict in core.py',
    ('peer_info', 'host'): 'Twisted transport address in rpcserver.py, not libtorrent',
    ('peer_info', 'port'): 'Twisted transport address in rpcserver.py, not libtorrent',
    ('announce_entry', 'replace'): 'str.replace() on a tracker URL in torrent.py',
}


def code_tokens(source):
    """Yield (type, string, row) for code tokens only."""
    skip = {
        tokenize.COMMENT,
        tokenize.STRING,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
    }
    for name in (
        'FSTRING_START',
        'FSTRING_MIDDLE',
        'FSTRING_END',
        'TSTRING_START',
        'TSTRING_MIDDLE',
        'TSTRING_END',
    ):
        if hasattr(tokenize, name):
            skip.add(getattr(tokenize, name))
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type not in skip:
            yield tok.type, tok.string, tok.start[0]


def scan(source, where, refs, fields=True):
    """Collect references; `fields` enables the torrent_status-style receivers."""
    toks = list(code_tokens(source))
    for i, (typ, s, row) in enumerate(toks):
        if typ != tokenize.NAME:
            continue
        prev = toks[i - 1][1] if i else ''
        # `lt` must start a chain, not be the tail of `foo.lt`.
        if s == 'lt' and prev != '.':
            chain, j = [], i + 1
            while (
                j + 1 < len(toks)
                and toks[j][1] == '.'
                and toks[j + 1][0] == tokenize.NAME
            ):
                chain.append(toks[j + 1][1])
                j += 2
            if chain:
                refs.setdefault(('module', '.'.join(chain)), []).append(
                    '%s:%d' % (where, row)
                )
            continue
        if (
            s in RECEIVERS
            and i + 2 < len(toks)
            and toks[i + 1][1] == '.'
            and toks[i + 2][0] == tokenize.NAME
        ):
            member = toks[i + 2][1]
            called = i + 3 < len(toks) and toks[i + 3][1] == '('
            if s in CALL_ONLY and not called:
                continue
            if s in FIELD_RECEIVERS and not fields:
                continue
            refs.setdefault((RECEIVERS[s][0], member), []).append(
                '%s:%d' % (where, row)
            )


def resolve_module(path):
    obj = lt
    for part in path.split('.'):
        if not hasattr(obj, part):
            return False
        obj = getattr(obj, part)
    return True


def main():
    refs = {}
    for dirpath, _, files in os.walk(ROOT):
        if os.sep + 'tests' in dirpath:
            continue
        for name in files:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT)
            if name.endswith('.py'):
                with open(path, encoding='utf-8') as fh:
                    in_core = rel.startswith('core' + os.sep)
                    scan(fh.read(), rel, refs, fields=in_core)
            elif name.endswith('.egg'):
                with zipfile.ZipFile(path) as z:
                    for member in z.namelist():
                        if not member.endswith('.py'):
                            continue
                        src = z.read(member).decode('utf-8', 'replace')
                        egg_refs = {}
                        scan(src, '%s!%s' % (rel, member), egg_refs)
                        # Plugins receive RPC dicts, not libtorrent objects;
                        # only their direct lt.* use is meaningful.
                        for key, where in egg_refs.items():
                            if key[0] == 'module':
                                refs.setdefault(key, []).extend(where)

    tests = {kind: test for kind, test in RECEIVERS.values()}
    missing, allowed_hits, by_kind = [], [], {}
    for (kind, member), where in sorted(refs.items()):
        by_kind[kind] = by_kind.get(kind, 0) + 1
        ok = resolve_module(member) if kind == 'module' else tests[kind](member)
        if ok:
            continue
        if (kind, member) in ALLOWED:
            allowed_hits.append('%s.%s' % (kind, member))
            continue
        missing.append((kind, member, where))

    print(
        'libtorrent %s: %d distinct references checked'
        % (lt.__version__, len(refs))
    )
    print('  ' + ', '.join('%s %d' % kv for kv in sorted(by_kind.items())))
    if allowed_hits:
        print('  allowed (not libtorrent): ' + ', '.join(allowed_hits))
    if missing:
        print('MISSING:')
        for kind, member, where in missing:
            more = ' (+%d more)' % (len(where) - 1) if len(where) > 1 else ''
            print('  %-40s %s%s' % ('%s.%s' % (kind, member), where[0], more))
        sys.exit(1)
    print('all present')


if __name__ == '__main__':
    main()
