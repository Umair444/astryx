#!/usr/bin/env python3
"""Oracle: plan-9853 D2, a python trigger's RETIREMENT survives the pulse. The pulse's real reconcile() runs against a
fixture database and a throwaway triggers/ tree; the tombstone is written by the SAME module trigger_rm uses
(channel/tombstone.mjs).

  R1 a file defining two triggers registers both, enabled (positive control)
  R2 trigger_rm's tombstone on one → reconcile keeps it DISABLED (on today's pulse the upsert re-enables it: RED)
  R3 ...while the other trigger in the SAME file stays enabled (retirement is per name, not per file)
  R4 per TARGET agent (a3 BC-1): another agent's trigger of the same name, in its own file, stays enabled
  R5 trigger_set writing the name again clears the tombstone → reconcile enables it again (a3 BC-2)
  W  tests/test_tombstone.mjs passes on the same module: its own arms, and server.mjs's wiring (trigger_rm retires a
     python trigger; trigger_set clears what it writes)
Needs a fixture database and node, else 77.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


try:
    import psycopg
    from nucleus.sqlguard.fixture import fixture_db
except ImportError as e:
    print(f"SKIP: deps ({e}). Nothing was verified here.")
    sys.exit(77)
if not shutil.which("node"):
    print("SKIP: no node (the tombstone's writer is channel/tombstone.mjs). Nothing was verified here.")
    sys.exit(77)

TREE = Path(tempfile.mkdtemp(prefix="tomb-oracle-"))
shutil.copy(REPO / "astryx.py", TREE / "astryx.py")
FILE = '''from astryx import trigger


@trigger("*/5 * * * *", note="first")
def zz_watch_one(ctx):
    return None


@trigger("*/5 * * * *", note="second")
def zz_watch_two(ctx):
    return None
'''
# The tombstone module under test (a mutant, under the probe), STAGED beside trigger_name.mjs so its relative import
# resolves: a mutant alone in /tmp would fail to IMPORT, and that would read as caught.
STAGE = TREE / "channel"
STAGE.mkdir()
shutil.copy(REPO / "channel" / "trigger_name.mjs", STAGE / "trigger_name.mjs")
shutil.copy(os.environ.get("TOMBSTONE_SRC") or REPO / "channel" / "tombstone.mjs", STAGE / "tombstone.mjs")
for agent in ("zzagent", "zzother"):
    (TREE / "triggers" / agent).mkdir(parents=True)
(TREE / "triggers" / "zzagent" / "watch.py").write_text(FILE)
(TREE / "triggers" / "zzother" / "watch.py").write_text(FILE)


def node(fn, agent, names):
    """Call channel/tombstone.mjs's retire/clear on the throwaway tree: the module trigger_rm/trigger_set use."""
    js = (f"import('{(STAGE / 'tombstone.mjs').as_uri()}').then(async m => "
          f"{{ const root = new URL('{(TREE / 'triggers').as_uri()}/'); "
          + (f"await m.retire(root, '{agent}', '{names[0]}')" if fn == "retire" else
             f"await m.clear(root, '{agent}', {list(names)!r})") + " })")
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


try:
    with fixture_db() as fx:
        os.environ["ASTRYX_DSN"] = fx["dsn"]                   # the pulse binds its DSN from the env first
        import importlib.util
        spec = importlib.util.spec_from_file_location("pulse", os.environ.get("PULSE_SRC") or REPO / "nucleus/pulse.py")
        pulse = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pulse)
        pulse.REPO = TREE                                       # its triggers/ tree
        pulse.PY = sys.executable                               # the interpreter running this oracle (a worktree has
                                                                # no venv/ of its own)
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            def enabled():
                return {(a, n): e for a, n, e in c.execute(
                    "SELECT agent, name, enabled FROM triggers WHERE kind='python'").fetchall()}
            pulse.reconcile(c)
            e = enabled()
            want("R1 a file with two triggers registers both, enabled (control)",
                 e.get(("zzagent", "zz_watch_one")) and e.get(("zzagent", "zz_watch_two")), str(e))
            c.execute("UPDATE triggers SET enabled=false WHERE agent='zzagent' AND name='zz_watch_one'")
            node("retire", "zzagent", ["zz_watch_one"])
            pulse.reconcile(c)
            pulse.reconcile(c)                                  # a second pass: still retired
            e = enabled()
            want("R2 trigger_rm's tombstone: reconcile keeps it DISABLED, pass after pass",
                 e.get(("zzagent", "zz_watch_one")) is False, str(e))
            want("R3 ...and the other trigger in the SAME file stays enabled", e.get(("zzagent", "zz_watch_two")) is True)
            want("R4 another agent's trigger of the same name stays enabled (per target agent)",
                 e.get(("zzother", "zz_watch_one")) is True, str(e))
            node("clear", "zzagent", ["zz_watch_one"])
            pulse.reconcile(c)
            want("R5 trigger_set writing it again clears the tombstone → enabled again",
                 enabled().get(("zzagent", "zz_watch_one")) is True)
    # a2 R1 (#49115): nothing tells an agent to retire a trigger by DELETING its file (init.sh would reinstall it;
    # only trigger_rm's tombstone retires)
    import re as _re
    advice = _re.compile(r"delete (?:this|the) file.{0,60}retire|retires? it.{0,20}(?:delete|remov)", _re.I | _re.S)
    hits = [str(f.relative_to(REPO)) for f in [REPO / "init.sh", *sorted((REPO / "docs").glob("*.md")),
                                              *sorted((REPO / "nucleus/shipped_triggers").glob("*.py"))]
            if advice.search(f.read_text())]
    want("R6 no shim or doc advises retiring a trigger by deleting its file (control: the pattern catches it)",
         not hits and advice.search("delete this file and the pulse retires it"), str(hits))
    # the module's own arms and server.mjs's WIRING (tests/test_tombstone.mjs), on the SAME staged module
    r = subprocess.run(["node", str(REPO / "tests" / "test_tombstone.mjs")], capture_output=True, text=True,
                       timeout=60, env={**os.environ, "TOMBSTONE_SRC": str(STAGE / "tombstone.mjs"),
                                        "SERVER_SRC": os.environ.get("SERVER_SRC") or str(REPO / "channel/server.mjs")})
    want("W the tombstone module's arms and server.mjs's wiring pass (tests/test_tombstone.mjs)", r.returncode == 0,
         (r.stdout + r.stderr)[-400:])
finally:
    shutil.rmtree(TREE, ignore_errors=True)

if fails:
    print(f"FAIL: {len(fails)} arm(s)")
    sys.exit(1)
print("PASS: a retired python trigger stays retired through the pulse, per agent and name")
