#!/usr/bin/env python3
"""Oracle for triggers/memory/influence_compute.py (memory's nightly influence-graph compute, plan-11324 S2): its one
SQL site, the last-good-compute read on the FAILURE path, runs through pulse_run's OWN Ctx against a sqlguard fixture
DB (the people_essence pattern; medic #58586: the site was UNEXECUTED and unlisted).

The subject is gitignored (triggers/), so it's path-loaded; absent → SKIP 77. shell.connect / shell.compute are
replaced, so nothing here computes a graph or touches the live estate. Arms:
  1. compute raises, NO GLOBAL row in influence_value → loud, "no compute has ever succeeded", and state NOT marked
     (the next firing retries).
  2. compute raises, ≥1 GLOBAL row (plus a newer non-GLOBAL row that must not count) → loud, names the newest
     GLOBAL row's age, state not marked.
  3. compute succeeds → silent, state marked today.
  4. state already marked today → silent, and compute is NOT called (once per day).
Exit 0 pass · 1 fail · 77 could-not-run.
"""
import contextlib
import datetime as dt
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BODY = Path(os.environ.get("INFLUENCE_COMPUTE_SRC") or REPO / "triggers" / "memory" / "influence_compute.py")
if not BODY.exists():
    print(f"SKIP: {BODY.relative_to(REPO) if BODY.is_relative_to(REPO) else BODY} absent (gitignored) — nothing asserted.")
    sys.exit(77)
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_influence_compute", REPO, deps=("psycopg",))


def load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


try:
    ic = load("influence_compute_under_test", BODY)
    pr = load("pulse_run_ic", REPO / "src" / "astryx" / "pulse" / "pulse_run.py")
    import psycopg
    from astryx.influence import shell
    from astryx.core import charter
    from astryx.security.sqlguard.fixture import fixture_db
except Exception as e:  # noqa: BLE001
    print(f"SKIP: a subject isn't importable ({type(e).__name__}: {e}).")
    sys.exit(77)

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


_fx = fixture_db()
try:
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"SKIP: the fixture database couldn't be built ({type(e).__name__}: {e}).")
    sys.exit(77)

try:
    conn = psycopg.connect(fx["dsn"], autocommit=True)

    class TempCtx(pr.Ctx):
        def __init__(self, connection, state):
            super().__init__(state)
            self._conn = connection

    calls = []

    def boom(**kw):
        calls.append("connect")
        raise RuntimeError("compute refused: fixture")

    @contextlib.contextmanager
    def fake_conn(**kw):
        calls.append("connect")
        yield None

    shell.compute = lambda c, roster=None: calls.append("compute")
    charter.roster = lambda: ["a", "b"]

    def run(connect, state):
        calls.clear()
        shell.connect = connect
        return ic.influence_compute(TempCtx(conn, state))

    today = dt.date.today().isoformat()
    print("influence_compute:")

    st = {}
    out = run(boom, st) or ""
    check("1. raise, no GLOBAL row → loud", out.startswith("INFLUENCE COMPUTE FAILED (RuntimeError: compute refused"), repr(out))
    check("1. … says no compute ever succeeded", "no compute has ever succeeded" in out, repr(out))
    check("1. … state not marked (retried next firing)", "rang" not in st, repr(st))

    conn.execute("INSERT INTO influence_value (scope, view, agent, value, unmapped, computed_at) VALUES "
                 "('local', 'global', 'seed', 0.2, 0, '2026-10-16 02:45+00'), "
                 "('local', 'global', 'seed', 0.2, 0, '2026-10-15 02:45+00'), "
                 "('local', 'routing', 'seed', 0.2, 0, '2026-10-17 09:00+00')")
    st = {}
    out = run(boom, st) or ""
    check("2. raise, GLOBAL rows → names the NEWEST GLOBAL row's age (not the routing row)",
          "the last good compute was 2026-10-16 02:45Z" in out, repr(out))
    check("2. … state not marked", "rang" not in st, repr(st))

    st = {}
    out = run(fake_conn, st)
    check("3. compute succeeds → silent", out is None, repr(out))
    check("3. … compute was called", calls == ["connect", "compute"], repr(calls))
    check("3. … state marked today", st.get("rang") == today, repr(st))

    out = run(boom, st)
    check("4. already ran today → silent", out is None, repr(out))
    check("4. … compute not called", calls == [], repr(calls))
    conn.close()
finally:
    _fx.__exit__(None, None, None)

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
sys.exit(1 if fails else 0)
