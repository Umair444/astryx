#!/usr/bin/env python3
"""Oracle: nucleus/trigger_names.py, "is trigger N installed?" (plan-9853 D1/D3; a4 #49108, a1 BC-1, a2 R2, a3 BC-1).
The helper runs as init.sh runs it (`venv/bin/python -m nucleus.trigger_names …` in a throwaway tree, tests/trigger_tree)
and is checked against the PULSE's own discover() (`pulse.py --names`), the semantics it models.

  C  the closure, each by its own module so the file that installs it is named: C1 an own def under any filename;
     C2 (i) `from M import a` registers ALL of M; C3 (ii) an alias registers the def's name, never the alias;
     C4 (iii) `import M`; C5 transitive; C6 `from pkg import submodule` (a2 R2), and the real shim in that form;
     C7 the sys.path idiom (nucleus/android.py's: insert a dir built from __file__, import from it); C8 an
     `if __name__ == "__main__":` block is dead under discover, not blind; C9 the init.sh shim under another name
  S  states: S1 absent (control) exit 2; S2 RETIRED per TARGET agent (a3 BC-1): another agent's tombstoned copy
     doesn't retire seed's, seed's own tombstone does (exit 1); an untombstoned copy elsewhere is installed (exit 0)
  L  legacy: a python row with no file and no tombstone → DEFERRED (exit 3) naming the agent and BOTH exits; its
     tombstone → absent; a non-python row is never legacy (a2 G3)
  D  the table unreadable → would-be-absent names DEFER; installed ones still read installed
  E  import-safe with no .env and no ASTRYX_DSN (a4 #49617): it answers (deferred), never crashes
  B  a1 BC-1: every construct the model doesn't positively understand makes the file BLIND → DEFERRED (17 fixtures,
     one at a time, each named in the detail; `names` exits 3), with a fully-understood control beside them
  P  parity: names == discover for every non-blind fixture AND for the live corpus (triggers/*/*.py, where present)
Needs a fixture database, else 77.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


try:
    import psycopg
    from nucleus.sqlguard.fixture import fixture_db, FixtureUnavailable
except ImportError as e:
    print(f"SKIP: deps ({e}). Nothing was verified here.")
    sys.exit(77)
import trigger_tree  # noqa: E402

T = Path(tempfile.mkdtemp(prefix="tnames-oracle-"))
trigger_tree.build(T, os.environ.get("TRIGGER_NAMES_SRC"))   # the seam: a mutant under the probe
PY = str(T / "venv/bin/python")
NODSN = "postgresql://nobody@127.0.0.1:1/none"


def put(rel, text):
    p = T / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def state(name, target="seed", dsn=None, env=None):
    e = {k: v for k, v in os.environ.items() if k != "ASTRYX_DSN"} if env is None else env
    if dsn:
        e["ASTRYX_DSN"] = dsn
    r = subprocess.run([PY, "-m", "nucleus.trigger_names", "state", name, "--target", target], cwd=T,
                       capture_output=True, text=True, timeout=120, env=e)
    return r.returncode, r.stdout.strip(), r.stderr.strip()[-300:]


def names_cli(path):
    r = subprocess.run([PY, "-m", "nucleus.trigger_names", "names", str(path)], cwd=T, capture_output=True, text=True,
                       timeout=60, env={**os.environ, "ASTRYX_DSN": NODSN})
    try:
        return r.returncode, set(json.loads(r.stdout))
    except ValueError:
        return r.returncode, None


def discover(path, repo=T):
    """The pulse's own answer: `pulse.py --names` (the tree's pulse discovers the tree)."""
    r = subprocess.run([PY, str(repo / "nucleus/pulse.py"), "--names", str(path)], cwd=repo, capture_output=True,
                       text=True, timeout=60, env={**os.environ, "ASTRYX_DSN": NODSN})
    return set(json.loads(r.stdout)) if r.returncode == 0 else None


TRIG = 'from astryx import trigger\n\n\n'
DEF = '@trigger("*/5 * * * *", note="x")\ndef {}(ctx):\n    return None\n\n\n'
# the modules the closure arms import (one per arm, so the installing file is attributable)
put("zzpkg/__init__.py", "")
put("zzpkg/mod_i.py", TRIG + DEF.format("zz_i1") + DEF.format("zz_i2"))
put("zzpkg/mod_ii.py", TRIG + DEF.format("zz_ii"))
put("zzpkg/mod_iii.py", TRIG + DEF.format("zz_iii"))
put("zzpkg/deep.py", TRIG + DEF.format("zz_deep") + "X = 1\n")
put("zzpkg/mid.py", "from zzpkg.deep import X  # noqa: F401\n")
put("zzpkg/sub/__init__.py", "")
put("zzpkg/sub/leaf.py", TRIG + DEF.format("zz_leaf"))
put("zzside/zzside_mod.py", TRIG + DEF.format("zz_side"))
put("zzpkg/pathy.py", 'import sys\nfrom pathlib import Path\n\nHERE = Path(__file__).resolve().parents[1]\n'
                      'if str(HERE / "zzside") not in sys.path:\n    sys.path.insert(0, str(HERE / "zzside"))\n'
                      'import zzside_mod  # noqa: E402,F401\n')
GOOD = {
    "owner/anything_named.py": TRIG + DEF.format("zz_own"),
    "a_i/i.py": "from zzpkg.mod_i import zz_i1  # noqa: F401\n",
    "a_ii/ii.py": "from zzpkg.mod_ii import zz_ii as zz_alias  # noqa: F401\n",
    "a_iii/iii.py": "import zzpkg.mod_iii  # noqa: F401\n",
    "a_t/t.py": "import zzpkg.mid  # noqa: F401\n",
    "a_sub/sub.py": "from zzpkg.sub import leaf  # noqa: F401\n",
    "a_sub/cc_submodule_form.py": "from nucleus.shipped_triggers import context_compact  # noqa: F401\n",
    "a_path/p.py": "import zzpkg.pathy  # noqa: F401\n",
    "a_main/m.py": TRIG + DEF.format("zz_main") + 'if __name__ == "__main__":\n    import zzpkg.never  # noqa\n',
    "umair/my_review.py": trigger_tree.shim("pr_review"),
    "memory/m.py": TRIG + DEF.format("zz_mem"),
}
for rel, body in GOOD.items():
    put(f"triggers/{rel}", body)
BLIND = {
    "b1 an import inside a top-level try": "try:\n    from zzpkg.mod_i import *  # noqa\nexcept ImportError:\n    pass\n",
    "b2 a decorated def inside a top-level if": TRIG + 'if True:\n    @trigger("* * * * *")\n    def zz_b2(ctx):\n'
                                                      '        return None\n',
    "b3 a decorated method in a class": TRIG + 'class K:\n    @trigger("* * * * *")\n    def zz_b3(self):\n'
                                               '        return None\n',
    "b4 `from astryx import trigger as T`, used by call": 'from astryx import trigger as T\n\n\ndef zz_b4(ctx):\n'
                                                          '    return None\n\n\nT("* * * * *")(zz_b4)\n',
    "b5 an alias of the decorator": TRIG + 't = trigger\n\n\n@t("* * * * *")\ndef zz_b5(ctx):\n    return None\n',
    "b6 an attribute-chain decorator": 'import astryx\nx = astryx\n\n\n@x.trigger("* * * * *")\ndef zz_b6(ctx):\n'
                                       '    return None\n',
    "b7 a call-result decorator": TRIG + 'def make():\n    return trigger\n\n\n@make()("* * * * *")\n'
                                         'def zz_b7(ctx):\n    return None\n',
    "b8 exec at top level": 'exec("from zzpkg.mod_i import zz_i1")\n',
    "b9 importlib at top level": 'import importlib\nimportlib.import_module("zzpkg.mod_i")\n',
    "b10 __import__ at top level": '__import__("zzpkg.mod_i")\n',
    "b11 runpy at top level": 'import runpy\nrunpy.run_path("zzpkg/mod_i.py")\n',
    "b12 a star-import that doesn't resolve": "from zzpkg.nothere import *  # noqa\n",
    "b13 an in-repo import that doesn't resolve": "import zzpkg.nothere  # noqa\n",
    "b14 a relative import": "from . import x  # noqa\n",
    "b15 a file that doesn't parse": "def zz_b15(ctx:\n    return None\n",
    "b16 sys.path other than the idiom": 'import sys\nsys.path.append("/elsewhere")\nimport zzelsewhere  # noqa\n',
    "b17 the trigger used other than as a decorator": TRIG + 'def f(ctx):\n    return None\n\n\n'
                                                             'trigger("* * * * *")(f)\n',
}

try:
    with fixture_db() as fx:
        DSN = fx["dsn"]
        with psycopg.connect(DSN, autocommit=True) as c:
            # ── C: the closure ────────────────────────────────────────────────────────────────────────────────────
            for label, name, where in (
                    ("C1 an own def under any filename", "zz_own", "triggers/owner/anything_named.py"),
                    ("C2 (i) `from M import a` registers ALL of M (the other def too)", "zz_i2", "triggers/a_i/i.py"),
                    ("C3 (ii) an alias registers the def's name", "zz_ii", "triggers/a_ii/ii.py"),
                    ("C4 (iii) `import M` registers M's triggers", "zz_iii", "triggers/a_iii/iii.py"),
                    ("C5 transitive: file → mid → deep", "zz_deep", "triggers/a_t/t.py"),
                    ("C6 `from pkg import submodule` imports the submodule (a2 R2)", "zz_leaf", "triggers/a_sub/sub.py"),
                    ("C6 ...the real shim in that form: `from nucleus.shipped_triggers import context_compact`",
                     "context_compact", "triggers/a_sub/cc_submodule_form.py"),
                    ("C7 the sys.path idiom: an inserted dir is searched first, as at runtime", "zz_side",
                     "triggers/a_path/p.py"),
                    ("C8 an `if __name__ == \"__main__\":` block is dead under discover, not blind", "zz_main",
                     "triggers/a_main/m.py"),
                    ("C9 the init.sh shim under another agent and filename", "pr_review", "triggers/umair/my_review.py")):
                rc, out, err = state(name, dsn=DSN)
                want(f"{label} → installed (exit 0), naming {where}", rc == 0 and out == f"installed {where}",
                     f"rc={rc} {out} {err}")
            rc, out, _ = state("zz_alias", dsn=DSN)
            want("C3 ...and the ALIAS is not a trigger name (absent)", rc == 2 and out.startswith("absent"), out)
            # ── S: states, retirement per target ───────────────────────────────────────────────────────────────────
            rc, out, err = state("zz_none", dsn=DSN)
            want("S1 a name nothing defines → absent, exit 2 (control)", rc == 2 and out.startswith("absent"),
                 f"{rc} {out} {err}")
            put("triggers/memory/.retired/zz_mem", "retired by trigger_rm\n")
            rc, out, _ = state("zz_mem", dsn=DSN)
            want("S2 another agent's tombstoned copy retires only THAT copy: seed's answer is absent (a3 BC-1)",
                 rc == 2 and out.startswith("absent"), f"{rc} {out}")
            put("triggers/seed/.retired/zz_mem", "retired by trigger_rm\n")
            rc, out, _ = state("zz_mem", dsn=DSN)
            want("S2 ...seed's own tombstone → retired, exit 1, naming it",
                 rc == 1 and "triggers/seed/.retired/zz_mem" in out, f"{rc} {out}")
            put("triggers/umair/mem_copy.py", TRIG + DEF.format("zz_mem"))
            rc, out, _ = state("zz_mem", dsn=DSN)
            want("S2 ...an untombstoned copy anywhere → installed (the duplicate check stays global)",
                 rc == 0 and out == "installed triggers/umair/mem_copy.py", f"{rc} {out}")
            # ── L: legacy rows ──────────────────────────────────────────────────────────────────────────────────────
            c.execute("INSERT INTO triggers (agent, name, schedule, kind, check_src, next_fire) VALUES "
                      "('ghost', 'zz_legacy', '* * * * *', 'python', 'triggers/ghost/gone.py::zz_legacy', now()), "
                      "('ghost', 'zz_hb', '* * * * *', 'heartbeat', NULL, now())")
            rc, out, _ = state("zz_legacy", dsn=DSN)
            want("L1 a python row with no file and no tombstone → DEFERRED (exit 3), naming the agent and both exits",
                 rc == 3 and "LEGACY" in out and "ghost" in out and "trigger_rm zz_legacy" in out
                 and "./init.sh --reinstall zz_legacy" in out, f"{rc} {out}")
            put("triggers/ghost/.retired/zz_legacy", "retired by trigger_rm\n")
            rc, out, _ = state("zz_legacy", dsn=DSN)
            want("L1 ...its tombstone settles it: absent", rc == 2 and out.startswith("absent"), f"{rc} {out}")
            rc, out, _ = state("zz_hb", dsn=DSN)
            want("L2 a NON-python row is never legacy (a2 G3): absent", rc == 2 and out.startswith("absent"), f"{rc} {out}")
            # ── D: the table unreadable ────────────────────────────────────────────────────────────────────────────
            rc, out, _ = state("zz_none", dsn=NODSN)
            want("D1 the table unreadable → a would-be-absent name DEFERS", rc == 3 and "can't be read" in out,
                 f"{rc} {out}")
            rc, out, _ = state("zz_own", dsn=NODSN)
            want("D1 ...an installed one still reads installed", rc == 0, f"{rc} {out}")
            # ── E: no .env, no DSN ──────────────────────────────────────────────────────────────────────────────────
            bare = {k: v for k, v in os.environ.items() if k != "ASTRYX_DSN"}
            rc, out, err = state("zz_none", env=bare)
            want("E1 no .env and no ASTRYX_DSN: it answers (deferred), never a crash (a4 #49617)",
                 not (T / ".env").exists() and rc == 3 and out.startswith("deferred"), f"{rc} {out} {err}")
            # ── B: blind → deferred (a1 BC-1), one at a time ───────────────────────────────────────────────────────
            put("zzpkg/never_imported.py", "")
            for i, (label, body) in enumerate(BLIND.items()):
                f = put(f"triggers/blind/b{i}.py", body)
                rc, out, _ = state("zz_none", dsn=DSN)
                nrc, _n = names_cli(f)
                want(f"B {label} → BLIND: zz_none DEFERS naming the file, and `names` exits 3",
                     rc == 3 and f"triggers/blind/b{i}.py" in out and nrc == 3, f"rc={rc} names_rc={nrc} {out[:160]}")
                f.unlink()
            rc, out, _ = state("zz_none", dsn=DSN)
            want("B control: with the blind file gone, zz_none is absent again", rc == 2, f"{rc} {out}")
            rc, out, _ = state("zz_b15", dsn=DSN)
            put("triggers/blind/b15.py", BLIND["b15 a file that doesn't parse"])
            rc, out, _ = state("zz_b15", dsn=DSN)
            want("B15 ...a file that doesn't parse still counts its own `def` names (F2): installed",
                 rc == 0 and "triggers/blind/b15.py" in out, f"{rc} {out}")
            (T / "triggers/blind/b15.py").unlink()
    # ── P: parity with discover() ──────────────────────────────────────────────────────────────────────────────
    bad = []
    for f in sorted((T / "triggers").glob("*/*.py")):
        nrc, mine = names_cli(f)
        theirs = discover(f)
        if nrc != 0 or mine != theirs:
            bad.append(f"{f.relative_to(T)}: model {sorted(mine or [])} rc={nrc}, discover {sorted(theirs or [])}")
    want(f"P1 names == discover for every fixture file ({len(list((T / 'triggers').glob('*/*.py')))})", not bad,
         "; ".join(bad[:4]))
    live = sorted((REPO / "triggers").glob("*/*.py"))
    if live:
        import importlib.util
        spec = importlib.util.spec_from_file_location("tn_under_test", T / "nucleus/trigger_names.py")
        tn = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tn)
        bad, blind = [], []
        for f in live:
            r = tn.names(f, REPO)
            if r.blind:
                blind.append(f"{f.relative_to(REPO)}: {r.blind[0]}")
                continue
            theirs = discover(f, REPO)
            if theirs is not None and r.names != theirs:
                bad.append(f"{f.relative_to(REPO)}: model {sorted(r.names)} discover {sorted(theirs)}")
        print(f"  ..  live corpus: {len(live)} files, {len(blind)} blind" + (f" ({'; '.join(blind[:3])})" if blind else ""))
        want(f"P2 names == discover over the LIVE corpus ({len(live)} files; blind ones defer, never mis-read)", not bad,
             "; ".join(bad[:4]))
    else:
        print("  ..  P2 not run: no live triggers/ here (the fixture parity P1 still ran)")
except FixtureUnavailable as e:
    print(f"SKIP: no fixture database ({e}). Nothing was verified here.")
    sys.exit(77)
finally:
    import shutil
    shutil.rmtree(T, ignore_errors=True)

if fails:
    print(f"FAIL: {len(fails)} arm(s)")
    sys.exit(1)
print("PASS: trigger names are the pulse's (closure, alias, submodule, sys.path idiom), retired per target, legacy and "
      "the unreadable defer, and the model matches discover()")
