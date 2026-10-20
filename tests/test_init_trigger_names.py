#!/usr/bin/env python3
"""Oracle: init.sh's trigger installs ask src/astryx/core/trigger_names.py, by NAME (plan-9853 D3/D4; goal from #49101).
init.sh's own blocks (`# >>> trigger state` … `# <<< trigger reinstall`, and `# >>> trigger doctor`) run in throwaway
trees (tests/trigger_tree) against a fixture database, as the reconciler runs a node: chk; if red, act; chk again.

  N1 THE GOAL: an owner's copy under ANOTHER agent and filename → ccompact reads green, nothing added under seed;
     also in the submodule form (`from astryx.pulse.shipped_triggers import context_compact`, a2 R2)
  N2 nothing anywhere → the node installs seed's shim, then reads green; a second pass adds nothing (convergence)
  N3 seed's tombstone (trigger_rm) → green, nothing added
  N4 a3 BC-1: ANOTHER agent's tombstoned copy → seed's install still happens, once
  N5 a LEGACY row (a python row no file defines) → green and nothing installed; doctor names it, DEFERRED, with both exits
  N10 the org backup (seed #61526): no backup trigger at all → doctor ✗ for both names; the org's own pair → ✓; one
      name owned or retired → the other is a WARN naming it (never ✓ "not used"); one reinstall restores the pair
  N6 `--reinstall N` on a legacy name installs it (the owner's exit); on seed's tombstone it CLEARS it and installs (a3
     BC-2); when N is installed elsewhere it adds nothing; an unknown name is refused
  N7 the table unreadable → green, nothing installed; a file the model can't read (BLIND) → the same
  N8 doctor: installed → ✓ naming the file; absent with the node's gate off → "not used on this host"; absent with the
     gate on → ✗ "absent"; retired → ✓ naming the tombstone
  N9 census (a): every _chk_ that tests a trigger calls the helper; no `ls triggers/` glob remains
     census (b): every src/astryx/pulse/shipped_triggers/*.py has an init.sh install through the helper, or `# shipped-optional:`
Needs a fixture database, else 77.
"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
INIT = Path(os.environ.get("INIT_TRIGGERS_SRC") or REPO / "init.sh")
fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


try:
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db, FixtureUnavailable
except ImportError as e:
    print(f"SKIP: deps ({e}). Nothing was verified here.")
    sys.exit(77)
import trigger_tree  # noqa: E402

src = INIT.read_text()
nodes = re.search(r"^# >>> trigger state$.*?^# <<< trigger reinstall$", src, re.S | re.M)
doc = re.search(r"^  # >>> trigger doctor$.*?^  # <<< trigger doctor$", src, re.S | re.M)
want("init.sh carries the trigger-state … trigger-reinstall region and the trigger-doctor block", bool(nodes and doc))
if not (nodes and doc):
    sys.exit(1)
STUBS = ('say() { echo "say: $*"; }\ndie() { echo "die: $*"; exit 1; }\nok() { echo "OK $*"; }\n'
         'bad() { echo "BAD $*"; }\nwarn() { echo "WARN $*"; }\n')
NODSN = "postgresql://nobody@127.0.0.1:1/none"
SEED = Path("triggers/seed")


def tree():
    return trigger_tree.build(Path(tempfile.mkdtemp(prefix="init-tnames-")))


def bash(t: Path, body: str, dsn: str):
    env = {k: v for k, v in os.environ.items() if k not in ("ANDROID_ENABLED", "WINDOWS_CONTAINER", "ASTRYX_DSN")}
    env.update(ASTRYX_DSN=dsn, WINDOWS_CONTAINER="astryx-test-no-such-container")   # gates: off unless an arm says
    r = subprocess.run(["bash", "-c", STUBS + nodes.group(0) + "\n" + body], cwd=t, capture_output=True, text=True,
                       timeout=300, env=env)
    return r.returncode, r.stdout + r.stderr


def node(t: Path, n: str, dsn: str):
    """The reconciler's step for one interior node: (first chk, last chk)."""
    _, out = bash(t, f"_chk_{n}; a=$?\nif [ $a -ne 0 ]; then _act_{n}; fi\n_chk_{n}; b=$?\necho \"rc $a $b\"\n", dsn)
    m = re.search(r"^rc (\d+) (\d+)$", out, re.M)
    return (m.group(1), m.group(2)) if m else ("?", out[-300:])


def doctor(t: Path, dsn: str):
    return bash(t, doc.group(0), dsn)[1]


def put(t, rel, text):
    p = t / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


CC = trigger_tree.shim("context_compact")
try:
    with fixture_db() as fx:
        DSN = fx["dsn"]
        with psycopg.connect(DSN, autocommit=True) as c:
            # N1 the goal
            for label, body in (("the shim", CC),
                                ("the submodule form", "from astryx.pulse.shipped_triggers import context_compact  # noqa\n")):
                t = tree()
                put(t, "triggers/umair/my_hygiene.py", body)
                a, b = node(t, "ccompact", DSN)
                want(f"N1 an owner's copy under another agent and filename ({label}) → green, nothing under seed",
                     a == "0" and not (t / SEED / "context_compact.py").exists(), f"chk={a},{b}")
            # N2 install, then converge
            t = tree()
            a, b = node(t, "ccompact", DSN)
            body = (t / SEED / "context_compact.py").read_text() if (t / SEED / "context_compact.py").exists() else ""
            want("N2 nothing anywhere → RED, the node installs seed's shim, then green",
                 a != "0" and b == "0" and "from astryx.pulse.shipped_triggers.context_compact import context_compact" in body,
                 f"chk={a},{b}")
            before = sorted(p.relative_to(t) for p in (t / "triggers").rglob("*"))
            a2, _ = node(t, "ccompact", DSN)
            want("N2 ...a second pass reads green first and adds nothing (convergence)",
                 a2 == "0" and sorted(p.relative_to(t) for p in (t / "triggers").rglob("*")) == before, f"chk={a2}")
            # N3 seed's tombstone
            t = tree()
            put(t, "triggers/seed/.retired/context_compact", "retired by trigger_rm\n")
            a, _ = node(t, "ccompact", DSN)
            want("N3 seed's tombstone → green, nothing added", a == "0" and not (t / SEED / "context_compact.py").exists(),
                 f"chk={a}")
            # N4 another agent's tombstoned copy
            t = tree()
            put(t, "triggers/memory/context_compact.py", CC)
            put(t, "triggers/memory/.retired/context_compact", "retired by trigger_rm\n")
            a, b = node(t, "ccompact", DSN)
            want("N4 another agent's TOMBSTONED copy → seed's install still happens, once (a3 BC-1)",
                 a != "0" and b == "0" and (t / SEED / "context_compact.py").exists(), f"chk={a},{b}")
            # N5 legacy
            c.execute("DELETE FROM triggers")
            c.execute("INSERT INTO triggers (agent, name, schedule, kind, check_src, next_fire) VALUES "
                      "('ghost', 'pr_review', '* * * * *', 'python', 'triggers/ghost/pr_review.py::pr_review', now())")
            t = tree()
            a, _ = node(t, "prreview", DSN)
            want("N5 a LEGACY row → green and nothing installed", a == "0" and not (t / SEED / "pr_review.py").exists(),
                 f"chk={a}")
            d = doctor(t, DSN)
            line = next((ln for ln in d.splitlines() if "pr_review" in ln), "")
            want("N5 ...doctor names it: DEFERRED, the agent, and both exits",
                 line.startswith("WARN") and "DEFERRED" in line and "ghost" in line and "trigger_rm pr_review" in line
                 and "./init.sh --reinstall pr_review" in line, line[:200])
            # N6 --reinstall
            rc, out = bash(t, "reinstall_trigger pr_review", DSN)
            want("N6 --reinstall on a legacy name installs it (the owner's exit)",
                 rc == 0 and (t / SEED / "pr_review.py").exists() and "installed triggers/seed/pr_review.py" in out,
                 out[-200:])
            c.execute("DELETE FROM triggers")
            t = tree()
            put(t, "triggers/seed/.retired/context_compact", "retired by trigger_rm\n")
            rc, out = bash(t, "reinstall_trigger context_compact", DSN)
            want("N6 --reinstall on seed's tombstone CLEARS it and installs (a3 BC-2)",
                 rc == 0 and not (t / "triggers/seed/.retired/context_compact").exists()
                 and (t / SEED / "context_compact.py").exists(), out[-200:])
            t = tree()
            put(t, "triggers/steward/review.py", trigger_tree.shim("pr_review"))
            rc, out = bash(t, "reinstall_trigger pr_review", DSN)
            want("N6 --reinstall when it's installed elsewhere adds nothing, and says where",
                 rc == 0 and not (t / SEED / "pr_review.py").exists() and "triggers/steward/review.py" in out, out[-200:])
            rc, out = bash(t, "reinstall_trigger no_such_trigger", DSN)
            want("N6 --reinstall of a name init.sh doesn't install is refused", rc != 0 and "die:" in out, out[-200:])
            # N7 unreadable / blind
            t = tree()
            a, _ = node(t, "ccompact", NODSN)
            want("N7 the table unreadable → green, nothing installed (deferred, never guessed absent)",
                 a == "0" and not (t / SEED / "context_compact.py").exists(), f"chk={a}")
            t = tree()
            put(t, "triggers/umair/odd.py", "try:\n    from astryx.pulse.shipped_triggers.context_compact import *  # noqa\n"
                                            "except ImportError:\n    pass\n")
            a, _ = node(t, "ccompact", DSN)
            want("N7 a file the model can't read (BLIND) → green, nothing installed",
                 a == "0" and not (t / SEED / "context_compact.py").exists(), f"chk={a}")
            # N8 doctor
            c.execute("DELETE FROM triggers")
            t = tree()
            put(t, "triggers/steward/review.py", trigger_tree.shim("pr_review"))
            put(t, "triggers/seed/.retired/windows_idle_stop", "retired by trigger_rm\n")
            d = doctor(t, DSN)
            ln = {n: next((x for x in d.splitlines() if f"trigger {n}" in x), "")
                  for n in ("context_compact", "pr_review", "phone_resume_sweep", "windows_idle_stop")}
            want("N8 doctor: installed → ✓ naming the file",
                 ln["pr_review"].startswith("OK") and "triggers/steward/review.py" in ln["pr_review"], ln["pr_review"])
            want("N8 doctor: absent with the gate on → ✗ absent",
                 ln["context_compact"].startswith("BAD") and "absent" in ln["context_compact"], ln["context_compact"])
            want("N8 doctor: absent with the gate off → not used on this host",
                 ln["phone_resume_sweep"].startswith("OK") and "not used" in ln["phone_resume_sweep"],
                 ln["phone_resume_sweep"])
            want("N8 doctor: retired → ✓ naming the tombstone",
                 ln["windows_idle_stop"].startswith("OK") and ".retired/windows_idle_stop" in ln["windows_idle_stop"],
                 ln["windows_idle_stop"])
            # N10 (seed #61526): the org backup's two names, in a fresh tree and beside the org's own pair
            t = tree()
            bk = ("run_backup", "run_restore_verify")
            d = doctor(t, DSN)
            bl = [next((x for x in d.splitlines() if f"trigger {n} " in x or f"trigger {n}:" in x), "") for n in bk]
            want("N10 doctor: no backup trigger at all → ✗ absent for BOTH names, naming ./init.sh",
                 all(x.startswith("BAD") and "absent" in x and "./init.sh" in x for x in bl), str(bl))
            put(t, "triggers/steward/runners.py", 'from astryx import trigger\n\n\n'
                + "".join(f'@trigger("0 4 * * *", note="x")\ndef {n}(ctx):\n    return None\n\n\n' for n in bk))
            d = doctor(t, DSN)
            bl = [next((x for x in d.splitlines() if f"trigger {n} " in x or f"trigger {n}:" in x), "") for n in bk]
            want("N10 ...the org's own pair under another agent → ✓ installed, naming its file, no ✗",
                 all(x.startswith("OK") and "triggers/steward/runners.py" in x for x in bl), str(bl))
            # a2 #61535 A-1: ONE name owned, its sibling absent, is never a green "not used on this host"
            def bline(d, n):
                return next((x for x in d.splitlines() if f"trigger {n} " in x or f"trigger {n}:" in x), "")
            t = tree()
            put(t, "triggers/steward/own.py", 'from astryx import trigger\n\n\n@trigger("0 4 * * *", note="x")\n'
                'def run_backup(ctx):\n    return None\n')
            ln = bline(doctor(t, DSN), "run_restore_verify")
            want("N10 ...only run_backup owned: run_restore_verify is a WARN naming its installed sibling and where to "
                 "define it (the shim would register a second run_backup), never ✓",
                 ln.startswith("WARN") and "run_backup" in ln and "installed" in ln and "beside it" in ln
                 and "not used on this host" not in ln, ln)
            t = tree()
            put(t, "triggers/seed/.retired/run_backup", "retired by trigger_rm\n")
            ln = bline(doctor(t, DSN), "run_restore_verify")
            want("N10 ...run_backup RETIRED at seed: run_restore_verify is a WARN naming the retirement and the pair's "
                 "reinstall", ln.startswith("WARN") and "retired" in ln and "--reinstall run_restore_verify" in ln, ln)
            put(t, "triggers/seed/.retired/run_restore_verify", "retired by trigger_rm\n")
            rc, out = bash(t, "reinstall_trigger run_backup", DSN)
            want("N10 ...both retired: ONE `--reinstall run_backup` clears BOTH tombstones and installs the pair's shim",
                 not (t / SEED / ".retired" / "run_backup").exists()
                 and not (t / SEED / ".retired" / "run_restore_verify").exists()
                 and (t / SEED / "org_backup.py").is_file(), out[-300:])
except FixtureUnavailable as e:
    print(f"SKIP: no fixture database ({e}). Nothing was verified here.")
    sys.exit(77)

# N9 census, over init.sh itself and the shipped modules
chks = dict(re.findall(r"^(_chk_\w+)\(\) \{(.*?)\}[ \t]*$", src, re.M | re.S))   # each body, to its first line-final }
shipped = sorted(p.stem for p in (REPO / "src/astryx/pulse/shipped_triggers").glob("*.py") if p.stem != "__init__")
testing = {k: v for k, v in chks.items() if "triggers/" in v or any(s in v for s in shipped)}
want(f"N9 (a) every _chk_ that tests a trigger ({len(testing)}) calls the helper (_trigger_chk)",
     len(testing) >= 4 and all("_trigger_chk" in v for v in testing.values()),
     str({k: v.strip()[:60] for k, v in testing.items() if "_trigger_chk" not in v}))
want("N9 (a) no filename glob over triggers/ decides an install any more", not re.search(r"ls triggers/\*", src))
# a module's trigger NAMES, read by the one helper's own reader (org_backup's are run_backup and run_restore_verify, not
# its stem): it installs through the helper when init.sh asks _trigger_chk about any of them
_tn = importlib.util.spec_from_file_location("tn_n9", REPO / "src/astryx/core/trigger_names.py")
_tnm = importlib.util.module_from_spec(_tn)
_tn.loader.exec_module(_tnm)
def _names(s):
    return _tnm.names(REPO / f"src/astryx/pulse/shipped_triggers/{s}.py", REPO).names or {s}
missing = [s for s in shipped if not any(re.search(rf"_trigger_chk {n}\b", src) for n in _names(s))
           and "# shipped-optional:" not in (REPO / f"src/astryx/pulse/shipped_triggers/{s}.py").read_text()]
want(f"N9 (b) every shipped trigger ({len(shipped)}) installs through the helper or declares # shipped-optional:",
     not missing, str(missing))

if fails:
    print(f"FAIL: {len(fails)} arm(s)")
    sys.exit(1)
print("PASS: init.sh installs a shipped trigger only when the pulse would find it nowhere by NAME, never over a "
      "retirement, a legacy row or what it can't read; --reinstall is the owner's exit; doctor says which")
