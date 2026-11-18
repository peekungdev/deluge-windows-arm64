"""Import every Deluge module and entry point; report what fails.

deploy.sh builds the bundle's site-packages from an allowlist
(collect-site-packages.py). An allowlist that is too tight shows up as an
ImportError only when the one code path needing the missing package runs, so
this exercises all of them up front:

  - imports every module under deluge/ (except tests)
  - resolves Deluge's declared requirements through pkg_resources, as its UI
    loader and plugin manager do at runtime
  - loads every deluge.ui entry point and every plugin egg's core / gtk3ui /
    web entry points

Run it with the bundle's interpreter and with MSYS2's, and compare: a module
that fails only in the bundle is an allowlist gap. Prints one line per
failure, then a summary; exits non-zero if anything failed.
"""

import importlib
import os
import pkgutil
import sys
import warnings

warnings.filterwarnings('ignore')

# The GTK UI installs its reactor before anything imports twisted's default
# one; do the same, or importing gtk3 modules later raises
# ReactorAlreadyInstalledError for a reason that has nothing to do with
# packaging.
from twisted.internet import gtk3reactor  # noqa: E402

gtk3reactor.install()

import pkg_resources  # noqa: E402

import deluge  # noqa: E402
from deluge.i18n import setup_translation  # noqa: E402

setup_translation()

failures = []
modules = 0
for info in pkgutil.walk_packages(deluge.__path__, 'deluge.'):
    if '.tests' in info.name or info.name.endswith('.conftest'):
        continue
    modules += 1
    try:
        importlib.import_module(info.name)
    except Exception as ex:  # noqa: BLE001 - report every kind of failure
        failures.append(('module', info.name, '%s: %s' % (type(ex).__name__, ex)))

try:
    pkg_resources.require('deluge')
    required = 'ok'
except Exception as ex:  # noqa: BLE001
    required = '%s: %s' % (type(ex).__name__, ex)
    failures.append(('require', 'deluge', required))

entry_points = 0
for ep in pkg_resources.iter_entry_points('deluge.ui'):
    entry_points += 1
    try:
        ep.load()
    except Exception as ex:  # noqa: BLE001
        failures.append(('ui', ep.name, '%s: %s' % (type(ex).__name__, ex)))

plugin_dir = os.path.join(os.path.dirname(deluge.__file__), 'plugins')
eggs = sorted(f for f in os.listdir(plugin_dir) if f.endswith('.egg'))
for egg in eggs:
    pkg_resources.working_set.add_entry(os.path.join(plugin_dir, egg))
for group in ('deluge.plugin.core', 'deluge.plugin.gtk3ui', 'deluge.plugin.web'):
    for ep in pkg_resources.iter_entry_points(group):
        entry_points += 1
        try:
            ep.load()
        except Exception as ex:  # noqa: BLE001
            failures.append((group.rsplit('.', 1)[1], ep.name, '%s: %s' % (type(ex).__name__, ex)))

for kind, name, err in failures:
    print('FAIL  %-6s %-48s %s' % (kind, name, err[:110]))
print(
    'python %s | %d modules, %d entry points (%d plugin eggs), require(deluge): %s | %d failures'
    % (sys.version.split()[0], modules, entry_points, len(eggs), required, len(failures))
)
sys.exit(1 if failures else 0)
