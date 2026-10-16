#!/usr/bin/env python3
"""Oracle for triggers/memory/people_essence.py (memory's daily people-essence launcher): its one SQL site runs
through pulse_run's OWN Ctx against a sqlguard fixture DB (steward #39184, the library_compile remedy).

The subject is gitignored (triggers/), so it's path-loaded; absent → SKIP 77. The launch is recorded, never run
(subprocess.Popen is replaced), and the report/log paths point into a temp dir. Arms:
  1a. 0 folded rows (no social_relation row has `through`) and NO report → silent, and NOTHING is launched: the
      first backfill is memory's own, by hand.
  1b. 0 folded rows but a report counting some → LOUD ("watermarks LOST") and relaunched: "never backfilled" and
      "backfilled, then lost" must not read the same (a3 #39200).
  1c. PARTIAL loss: the table holds fewer folded rows than the last report counted → LOUD.
  2. ≥1 folded row and a fresh healthy report → silent, and `essence.py daily` is launched detached.
  3. ≥1 folded row and NO report → loud ("no essence run has ever reported"): a lost report never reads healthy.
  4. ≥1 folded row and a report with fetch-failed → loud (a2 #38791 B3: an unread chat is never "nothing new").
  5. ≥1 folded row and a report older than two days → loud (stale).
  Every loud arm also asserts the relaunch: a stall is the recovery path, never a stop (a3 #39200 M2).
Exit 0 pass · 1 fail · 77 could-not-run.
"""
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BODY = Path(os.environ.get("PEOPLE_ESSENCE_SRC") or REPO / "triggers" / "memory" / "people_essence.py")
if not BODY.exists():
    print(f"SKIP: {BODY.relative_to(REPO) if BODY.is_relative_to(REPO) else BODY} absent (gitignored) — nothing asserted.")
    sys.exit(77)
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_people_essence", REPO, deps=("psycopg",))


def load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


try:
    pe = load("people_essence_under_test", BODY)
    pr = load("pulse_run_pe", REPO / "src" / "astryx" / "pulse" / "pulse_run.py")
    import psycopg
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
        def __init__(self, connection):
            super().__init__({})
            self._conn = connection

    tmp = Path(tempfile.mkdtemp(prefix="pe_oracle_"))
    pe.REPORT, pe.LOG = tmp / "_last_run.json", tmp / "_run.log"
    launched = []

    class FakePopen:
        def __init__(self, argv, **kw):
            launched.append((argv, kw.get("start_new_session")))

    pe.subprocess.Popen = FakePopen

    def run(report):
        launched.clear()
        if report is None:
            pe.REPORT.unlink(missing_ok=True)
        else:
            pe.REPORT.write_text(json.dumps(report))
        return pe.people_essence(TempCtx(conn))

    now = time.time()
    print("people_essence:")
    def relaunched():
        return len(launched) == 1 and launched[0][0][-1] == "daily"

    out = run(None)
    check("1a. 0 folded, no report → silent", out is None, repr(out))
    check("1a. 0 folded, no report → nothing launched", launched == [], repr(launched))

    out = run({"at": now, "folded": 5, "stats": {"ok": 1}}) or ""
    check("1b. 0 folded but a report counted 5 → loud (LOST)", "watermarks LOST" in out, repr(out))
    check("1b. … and relaunched", relaunched(), repr(launched))

    conn.execute("INSERT INTO social_relation (org, pid, through) VALUES ('fx', 'p1', now())")
    out = run({"at": now, "folded": 5, "stats": {"ok": 1}}) or ""
    check("1c. 1 folded where the report counted 5 → loud (partial loss)", "watermarks LOST" in out, repr(out))
    check("1c. … and relaunched", relaunched(), repr(launched))

    out = run({"at": now, "todo": 2, "folded": 1, "stats": {"ok": 2}})
    check("2. ≥1 folded + healthy report → silent", out is None, repr(out))
    check("2. ≥1 folded → `essence.py daily` launched detached",
          len(launched) == 1 and launched[0][0][-1] == "daily" and launched[0][0][-2].endswith("essence.py")
          and launched[0][1] is True, repr(launched))

    out = run(None) or ""
    check("3. ≥1 folded + no report → loud", "no essence run has ever reported" in out, repr(out))
    check("3. ≥1 folded + no report → relaunched", relaunched(), repr(launched))

    out = run({"at": now, "todo": 3, "stats": {"ok": 2, "fetch-failed": 1}}) or ""
    check("4. fetch-failed → loud", "could not be read from WhatsApp" in out, repr(out))
    check("4. fetch-failed → relaunched", relaunched(), repr(launched))

    out = run({"at": now - 3 * 86400, "todo": 1, "stats": {"ok": 1}}) or ""
    check("5. a report older than two days → loud", "no run has finished for 3.0 days" in out, repr(out))
    check("5. a report older than two days → relaunched", relaunched(), repr(launched))
    conn.close()
finally:
    _fx.__exit__(None, None, None)

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
sys.exit(1 if fails else 0)
