#!/usr/bin/env python3
"""Oracle: plan-9853 D2, a python trigger's RETIREMENT survives the pulse. The pulse's real reconcile() runs against a
fixture database and a throwaway triggers/ tree; the tombstone is written and cleared by the SAME module trigger_rm and
trigger_set use (channel/tombstone.mjs), and trigger_set's names come from the pulse under test (`pulse.py --names`).

  R1 every file shape registers, enabled (positive control): a one-line pair, a multi-line decorator, a shim
  R2 trigger_rm's tombstone on one → reconcile keeps it DISABLED (on today's pulse the upsert re-enables it: RED)
  R3 ...while the other trigger in the SAME file stays enabled (retirement is per name, not per file)
  R4 per TARGET agent (a3 BC-1): another agent's trigger of the same name, in its own file, stays enabled
  R5 trigger_set writing the file again clears the tombstone → reconcile enables it again (a3 BC-2), through
     trigger_set's own path (tombstone.definedNames → `pulse.py --names`, then clear), for every real file shape:
     R5 a one-line decorator; R5b a MULTI-LINE decorator; R5c an import-only SHIM (its trigger comes in through the
     import closure). a4 #49496: a source regex missed 40 of 49 live defs and every shim.
  R6 no shim or doc advises retiring a trigger by deleting its file (a2 R1), with a pattern control
  R7 a tombstone that holds off a defined name is SAID to its agent once (not again a minute later, even once the
     first notice was delivered), never for a live name; a fresh trigger_rm earns a fresh notice (a4 #49496)
  W  tests/test_tombstone.mjs passes on the same module: its own arms, and server.mjs's wiring (trigger_rm retires a
     python trigger; trigger_set clears what the pulse says the file defines)
Needs a fixture database and node, else 77.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
    from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db
    from astryx.security.sqlguard import estate
except ImportError as e:
    print(f"SKIP: deps ({e}). Nothing was verified here.")
    sys.exit(77)
if not shutil.which("node"):
    print("SKIP: no node (the tombstone's writer is channel/tombstone.mjs). Nothing was verified here.")
    sys.exit(77)

TREE = Path(tempfile.mkdtemp(prefix="tomb-oracle-"))
shutil.copy(REPO / "astryx.py", TREE / "astryx.py")                 # the shim, and the package it becomes
shutil.copytree(REPO / "src" / "astryx", TREE / "src" / "astryx", ignore=shutil.ignore_patterns("__pycache__"))
FILE = '''from astryx import trigger


@trigger("*/5 * * * *", note="first")
def zz_watch_one(ctx):
    return None


@trigger("*/5 * * * *", note="second")
def zz_watch_two(ctx):
    return None
'''
# the shapes a source regex can't see: a decorator that wraps (most live ones), and a SHIM whose trigger is imported
MULTI = '''from astryx import trigger


@trigger(
    "*/5 * * * *",
    note="a decorator that wraps",
)
def zz_multi(ctx):
    return None
'''
SHIPPED = '''from astryx import trigger


@trigger("*/5 * * * *", note="shipped")
def zz_shipped(ctx):
    return None
'''
SHIM = "from zzlib.shipped import zz_shipped  # noqa: F401\n"
# The tombstone module under test (a mutant, under the probe), STAGED beside trigger_name.mjs so its relative import
# resolves: a mutant alone in /tmp would fail to IMPORT, and that would read as caught.
STAGE = TREE / "channel"
STAGE.mkdir()
shutil.copy(REPO / "channel" / "trigger_name.mjs", STAGE / "trigger_name.mjs")
shutil.copy(os.environ.get("TOMBSTONE_SRC") or REPO / "channel" / "tombstone.mjs", STAGE / "tombstone.mjs")
# the pulse under test, placed IN the tree so its REPO is the tree (its triggers/, its zzlib), as trigger_set runs it
(TREE / "nucleus").mkdir()
for _d in ("devtools", "scripts", "src/astryx/contrib", "src/astryx/core", "src/astryx/data", "src/astryx/econ", "src/astryx/federation", "src/astryx/hands", "src/astryx/hearing", "src/astryx/memory", "src/astryx/people", "src/astryx/pg", "src/astryx/pulse", "src/astryx/pulse/shipped_triggers", "src/astryx/security", "src/astryx/security/sqlguard", "src/astryx/security/sqlguard/shim", "src/astryx/sql"):  # goal 10224 S4: the moved tree's dirs
    (TREE / _d).mkdir(parents=True, exist_ok=True)
PULSE = TREE / "src" / "astryx" / "pulse" / "pulse.py"
shutil.copy(os.environ.get("PULSE_SRC") or REPO / "src/astryx/pulse/pulse.py", PULSE)
(TREE / "zzlib").mkdir()
(TREE / "zzlib" / "__init__.py").write_text("")
(TREE / "zzlib" / "shipped.py").write_text(SHIPPED)
for agent in ("zzagent", "zzother"):
    (TREE / "triggers" / agent).mkdir(parents=True)
(TREE / "triggers" / "zzagent" / "watch.py").write_text(FILE)
(TREE / "triggers" / "zzagent" / "multi.py").write_text(MULTI)
(TREE / "triggers" / "zzagent" / "shim.py").write_text(SHIM)
(TREE / "triggers" / "zzother" / "watch.py").write_text(FILE)


def node(js):
    """Run `js` with m = channel/tombstone.mjs (the module trigger_rm/trigger_set use), root = the tree's triggers/."""
    js = (f"import('{(STAGE / 'tombstone.mjs').as_uri()}').then(async m => "
          f"{{ const root = new URL('{(TREE / 'triggers').as_uri()}/'); {js} }})")
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def set_file(agent, fname, body):
    """trigger_set python, as server.mjs runs it: write the file, ask definedNames (the pulse's discover), clear those."""
    f = TREE / "triggers" / agent / fname
    f.write_text(body)
    return node(f"const n = await m.definedNames('{f}', {{ py: '{sys.executable}', pulse: '{PULSE}' }}); "
                f"await m.clear(root, '{agent}', n); console.log(JSON.stringify(n))")


try:
    with fixture_db() as fx:
        os.environ["ASTRYX_DSN"] = fx["dsn"]                   # the pulse binds its DSN from the env first
        import importlib.util
        spec = importlib.util.spec_from_file_location("pulse", PULSE)
        pulse = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pulse)                          # its REPO is the tree
        pulse.PY = sys.executable                               # the interpreter running this oracle (a worktree has
                                                                # no venv/ of its own)
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            def enabled():
                return {(a, n): e for a, n, e in c.execute(
                    "SELECT agent, name, enabled FROM triggers WHERE kind='python'").fetchall()}

            def notices(agent, name):
                return c.execute("SELECT count(*) FROM messages WHERE to_agent=%s AND from_agent='pulse' "
                                 "AND body LIKE %s", (agent, f"[trigger retired {name}]%")).fetchone()[0]

            def rm(agent, name):
                """trigger_rm on a python trigger: the row disabled, then the tombstone (server.mjs's order)."""
                c.execute("UPDATE triggers SET enabled=false WHERE agent=%s AND name=%s", (agent, name))
                node(f"await m.retire(root, '{agent}', '{name}')")

            pulse.reconcile(c)
            e = enabled()
            want("R1 every file shape registers, enabled (control: one-line pair, multi-line, shim)",
                 all(e.get(("zzagent", n)) for n in ("zz_watch_one", "zz_watch_two", "zz_multi", "zz_shipped")), str(e))
            rm("zzagent", "zz_watch_one")
            pulse.reconcile(c)
            pulse.reconcile(c)                                  # a second pass: still retired
            e = enabled()
            want("R2 trigger_rm's tombstone: reconcile keeps it DISABLED, pass after pass",
                 e.get(("zzagent", "zz_watch_one")) is False, str(e))
            want("R3 ...and the other trigger in the SAME file stays enabled", e.get(("zzagent", "zz_watch_two")) is True)
            want("R4 another agent's trigger of the same name stays enabled (per target agent)",
                 e.get(("zzother", "zz_watch_one")) is True, str(e))
            # R7: once, then not again even after delivery (coalescing alone would repeat it every minute)
            n1 = notices("zzagent", "zz_watch_one")
            c.execute("UPDATE messages SET status='delivered' WHERE to_agent='zzagent'")
            pulse.reconcile(c)
            n2 = notices("zzagent", "zz_watch_one")
            want("R7 the held-off name is SAID to its agent once, and not again a minute later (delivered or not)",
                 n1 == 1 and n2 == 1, f"{n1} then {n2}")
            want("R7 ...never for a live name, nor for another agent's same name (control)",
                 notices("zzagent", "zz_watch_two") == 0 and notices("zzother", "zz_watch_one") == 0)
            time.sleep(1.1)                                     # a later trigger_rm: a newer tombstone
            node("await m.retire(root, 'zzagent', 'zz_watch_one')")
            pulse.reconcile(c)
            want("R7 ...and a fresh trigger_rm earns a fresh notice", notices("zzagent", "zz_watch_one") == 2,
                 str(notices("zzagent", "zz_watch_one")))
            for arm, shape, fname, body, name in (("R5", "one-line", "watch.py", FILE, "zz_watch_one"),
                                                  ("R5b", "MULTI-LINE decorator", "multi.py", MULTI, "zz_multi"),
                                                  ("R5c", "import-only SHIM", "shim.py", SHIM, "zz_shipped")):
                if name != "zz_watch_one":
                    rm("zzagent", name)
                    pulse.reconcile(c)
                    if enabled().get(("zzagent", name)) is not False:
                        want(f"{arm} (setup) trigger_rm retired {name}", False, str(enabled()))
                        continue
                got = set_file("zzagent", fname, body)
                pulse.reconcile(c)
                want(f"{arm} trigger_set of the {shape} file clears {name}'s tombstone → enabled again",
                     enabled().get(("zzagent", name)) is True
                     and not (TREE / "triggers" / "zzagent" / ".retired" / name).exists(), f"definedNames → {got}")
    # a2 R1 (#49115): nothing tells an agent to retire a trigger by DELETING its file (init.sh would reinstall it;
    # only trigger_rm's tombstone retires)
    import re as _re
    advice = _re.compile(r"delete (?:this|the) file.{0,60}retire|retires? it.{0,20}(?:delete|remov)", _re.I | _re.S)
    hits = [str(f.relative_to(REPO)) for f in [REPO / "init.sh", *sorted((REPO / "docs").glob("*.md")),
                                              *sorted((REPO / "src/astryx/pulse/shipped_triggers").glob("*.py"))]
            if advice.search(f.read_text())]
    want("R6 no shim or doc advises retiring a trigger by deleting its file (control: the pattern catches it)",
         not hits and advice.search("delete this file and the pulse retires it"), str(hits))
    # the module's own arms and server.mjs's WIRING (tests/test_tombstone.mjs), on the SAME staged module
    r = subprocess.run(["node", str(REPO / "tests" / "test_tombstone.mjs")], capture_output=True, text=True,
                       timeout=60, env={**os.environ, "TOMBSTONE_SRC": str(STAGE / "tombstone.mjs"),
                                        "SERVER_SRC": os.environ.get("SERVER_SRC") or str(REPO / "channel/server.mjs")})
    want("W the tombstone module's arms and server.mjs's wiring pass (tests/test_tombstone.mjs)", r.returncode == 0,
         (r.stdout + r.stderr)[-400:])
except FixtureUnavailable as e:                                 # no postgres here: 77 on CI, 1 on a live host
    shutil.rmtree(TREE, ignore_errors=True)
    estate.unavailable("test_trigger_tombstone", REPO, e, fails)
finally:
    shutil.rmtree(TREE, ignore_errors=True)

if fails:
    print(f"FAIL: {len(fails)} arm(s)")
    sys.exit(1)
print("PASS: a retired python trigger stays retired through the pulse (and says so once), per agent and name; "
      "trigger_set revives every file shape")
