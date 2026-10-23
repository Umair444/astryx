#!/usr/bin/env python3
"""Oracle: plan-10224 B1, the pulse's astryx-import CANARY. When `import astryx` fails in every discover() child (a
checkout caught mid-write, a half-written astryx.py), reconcile used to read EVERY trigger file as broken: one "failed
to load … DISABLES" wake per file, then the retirement loop switched every python trigger off. The pulse's real
reconcile() and tick() run against a fixture database and a throwaway tree holding the shim, src/astryx/pulse/pulse.py and two
trigger files.

  C1  control: with src/astryx beside the shim, every trigger registers enabled, and no alarm
  C1b src/astryx gone (git writes astryx.py before src/astryx/): the shim alone still loads every trigger, no alarm
  C2  astryx.py half-written (the import fails): every trigger STAYS enabled, exactly ONE alarm (to the seed, naming
      the error), and zero per-file "failed to load" wakes
  C3  a second broken tick coalesces: still one pending alarm
  C4  tick() while broken leaves a DUE python check unclaimed (no "check crashed" wake, next_fire not advanced)
  C5  astryx imports again: reconcile registers, the due check is claimed
  C6  a premium=0 heartbeat due under 5h pressure (90%): tick() leaves it UNCLAIMED, next_fire and last_eval
      untouched, so it waits (R3) instead of losing its day (medic #62336)
  C7  the gauge drops (50%): the next tick claims the waiting heartbeat, and its clock advances
  C6b the gauge CROSSES the rung inside one tick (below at its first read, above at any later one): a heartbeat the
      claim took (clock advanced) is also EVALUATED (its wake sent), never claimed-and-dropped (a4 #62398 R1)

Needs a fixture database, else 77. Mutants: tests/mutants_pulse_import_canary.py.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


try:
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db
except ImportError as e:
    print(f"SKIP: deps ({e}). Nothing was verified here.")
    sys.exit(77)

TREE = Path(tempfile.mkdtemp(prefix="canary-oracle-"))
shutil.copy(REPO / "astryx.py", TREE / "astryx.py")
SRC = TREE / "src" / "astryx"
shutil.copytree(REPO / "src" / "astryx", SRC, ignore=shutil.ignore_patterns("__pycache__"))
(TREE / "nucleus").mkdir()
for _d in ("devtools", "scripts", "src/astryx/contrib", "src/astryx/core", "src/astryx/data", "src/astryx/econ", "src/astryx/federation", "src/astryx/hands", "src/astryx/hearing", "src/astryx/memory", "src/astryx/people", "src/astryx/pg", "src/astryx/pulse", "src/astryx/pulse/shipped_triggers", "src/astryx/security", "src/astryx/security/sqlguard", "src/astryx/security/sqlguard/shim", "src/astryx/sql"):  # goal 10224 S4: the moved tree's dirs
    (TREE / _d).mkdir(parents=True, exist_ok=True)
PULSE = TREE / "src" / "astryx" / "pulse" / "pulse.py"
shutil.copy(os.environ.get("PULSE_SRC") or REPO / "src" / "astryx" / "pulse" / "pulse.py", PULSE)
shutil.copy(REPO / "src" / "astryx" / "pulse" / "pulse_run.py", TREE / "src" / "astryx" / "pulse" / "pulse_run.py")
(TREE / "triggers" / "zzagent").mkdir(parents=True)
for fname, name in (("a.py", "zz_canary_a"), ("b.py", "zz_canary_b")):
    (TREE / "triggers" / "zzagent" / fname).write_text(
        f'from astryx import trigger\n\n\n@trigger("* * * * *", note="c")\ndef {name}(ctx):\n    return None\n')


def main():
    try:
        fxcm = fixture_db()
        fx = fxcm.__enter__()
    except Exception as e:
        print(f"SKIP: no fixture database ({type(e).__name__}). Nothing was verified here.")
        return 77
    try:
        os.environ["ASTRYX_DSN"] = fx["dsn"]
        import importlib.util
        spec = importlib.util.spec_from_file_location("pulse_canary_subject", PULSE)
        pulse = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pulse)                      # its REPO is the tree
        pulse.PY = sys.executable
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            def enabled():
                return {n: e for n, e in c.execute(
                    "SELECT name, enabled FROM triggers WHERE agent='zzagent' AND kind='python'").fetchall()}

            def msgs(pattern):
                return c.execute("SELECT count(*) FROM messages WHERE from_agent='pulse' AND body LIKE %s",
                                 (pattern,)).fetchone()[0]

            pulse.reconcile(c)
            arm("C1 control: both triggers register enabled, no alarm",
                enabled() == {"zz_canary_a": True, "zz_canary_b": True} and msgs("%astryx import%") == 0, str(enabled()))

            shutil.rmtree(TREE / "src")                     # mid-checkout: the shim written, src/astryx/ not yet
            ok = pulse.reconcile(c)
            arm("C1b the shim with NO src/astryx still loads every trigger: enabled, no alarm (the shim is "
                "self-sufficient)", ok is True and enabled() == {"zz_canary_a": True, "zz_canary_b": True}
                and msgs("%astryx import%") == 0 and msgs("[trigger file %") == 0, f"{enabled()} ok={ok}")

            good = (TREE / "astryx.py").read_bytes()        # a half-written astryx.py: the import itself fails
            (TREE / "astryx.py").write_bytes(good[: len(good) * 2 // 3])
            ok = pulse.reconcile(c)
            alarm = c.execute("SELECT to_agent, body FROM messages WHERE from_agent='pulse' "
                              "AND body LIKE '[trigger astryx import]%'").fetchall()
            arm("C2 astryx won't import: every trigger STAYS enabled",
                enabled() == {"zz_canary_a": True, "zz_canary_b": True} and ok is False, f"{enabled()} ok={ok}")
            arm("C2 ...exactly ONE alarm, to the seed, naming the import error",
                len(alarm) == 1 and alarm[0][0] == "seed" and "Error" in alarm[0][1] and "astryx.py" in alarm[0][1],
                str(alarm))
            arm("C2 ...and no per-file 'failed to load' wake", msgs("[trigger file %") == 0,
                str(msgs("[trigger file %")))
            pulse.reconcile(c)
            arm("C3 a second broken tick coalesces onto the pending alarm",
                msgs("[trigger astryx import]%") == 1, str(msgs("[trigger astryx import]%")))

            c.execute("UPDATE triggers SET next_fire = now() - interval '1 minute', last_eval = NULL "
                      "WHERE agent='zzagent' AND name='zz_canary_a'")
            pulse.tick()
            row = c.execute("SELECT last_eval, next_fire <= now() FROM triggers WHERE agent='zzagent' "
                            "AND name='zz_canary_a'").fetchone()
            arm("C4 tick() while broken leaves the due python check unclaimed, no 'check crashed' wake",
                row[0] is None and row[1] is True and msgs("%check crashed%") == 0, f"{row} crashed={msgs('%check crashed%')}")

            (TREE / "astryx.py").write_bytes(good)
            shutil.copytree(REPO / "src" / "astryx", SRC, ignore=shutil.ignore_patterns("__pycache__"))
            pulse.tick()
            row = c.execute("SELECT last_eval FROM triggers WHERE agent='zzagent' AND name='zz_canary_a'").fetchone()
            arm("C5 astryx imports again: still enabled, and the due check is claimed",
                enabled() == {"zz_canary_a": True, "zz_canary_b": True} and row[0] is not None, f"{enabled()} {row}")

            # C6/C7: a shed heartbeat waits. Its clock must not move while it is shed (medic #62336)
            def gauge(pct):
                import json
                from datetime import datetime
                c.execute("DELETE FROM usage_polls")
                c.execute("DELETE FROM turns WHERE usage_snapshot IS NOT NULL")
                snap = {"state": "fresh", "fetched_at": datetime.now().astimezone().isoformat(),
                        "data": {"five_hour_utilization": pct}}
                c.execute("INSERT INTO usage_polls (state, snapshot) VALUES ('fresh', %s::jsonb)", (json.dumps(snap),))

            c.execute("INSERT INTO triggers (agent, name, schedule, kind, state, enabled, note, premium, next_fire) "
                      "VALUES ('zzagent', 'zz_daily_hb', '0 3 * * *', 'heartbeat', '{}'::jsonb, true, 'daily', 0, "
                      "now() - interval '1 minute')")

            def hb():
                return c.execute("SELECT last_eval, next_fire <= now() FROM triggers WHERE agent='zzagent' "
                                 "AND name='zz_daily_hb'").fetchone()
            gauge(90)
            pulse.tick()
            row = hb()
            arm("C6 at 90% a due premium=0 heartbeat stays unclaimed: last_eval untouched, still due (it waits)",
                row is not None and row[0] is None and row[1] is True, str(row))
            gauge(50)
            pulse.tick()
            row = hb()
            arm("C7 at 50% the next tick claims it: last_eval set, next_fire moved to its next cron instant",
                row is not None and row[0] is not None and row[1] is False, str(row))

            # C6b: the gauge crosses the rung mid-tick. Reads after the first one say "hot"; a tick that reads it once
            # agrees with itself (claimed AND evaluated), one that re-reads it drops what it claimed
            c.execute("UPDATE triggers SET next_fire = now() - interval '1 minute', last_eval = NULL, last_fired = NULL "
                      "WHERE agent='zzagent' AND name='zz_daily_hb'")
            # evaluated = FIRED (last_fired stamped). say() coalesces onto a still-pending wake of the same trigger and
            # then stamps nothing, so C7's wake is marked delivered first: a fire here is this tick's own
            c.execute("UPDATE messages SET status='delivered' WHERE to_agent='zzagent' AND status='pending'")
            fired = lambda: c.execute("SELECT last_fired FROM triggers WHERE agent='zzagent' "
                                      "AND name='zz_daily_hb'").fetchone()[0]
            reads, real_pressure = [], pulse.pressure

            def crossing(conn):
                reads.append(1)
                return len(reads) > 1                       # below on the first read, above on every later one
            pulse.pressure = crossing
            try:
                pulse.tick()
            finally:
                pulse.pressure = real_pressure
            row = hb()
            claimed = row is not None and row[0] is not None
            arm("C6b a gauge crossing the rung mid-tick: a heartbeat the claim took is also evaluated (fired)",
                (not claimed) or fired() is not None, f"claimed={claimed} last_fired={fired()} reads={len(reads)}")
    finally:
        fxcm.__exit__(None, None, None)
        shutil.rmtree(TREE, ignore_errors=True)
    print(f"\n{'FAIL' if fails else 'ALL PASS'}: pulse import canary ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
