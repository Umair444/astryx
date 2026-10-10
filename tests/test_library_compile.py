#!/usr/bin/env python3
"""Oracle for triggers/memory/library_compile.py (the overnight-edition doorbell) and the compile_lag check in
memory/lints/drift.py: their SQL runs through pulse_run's OWN Ctx against a sqlguard fixture DB (steward #37335).

Both subjects are gitignored (triggers/, memory/), so they're path-loaded; either one absent → SKIP 77. Arms:
  1. an EMPTY wire → silent (the count site executes, nothing after it).
  2. only a canvas-chat (cv:) row → the count sees it, but the thread list and the goals come back EMPTY (0 rows):
     cv: is the owner's own chat surface and never an edition's pointer (steward #37116).
  3. org work + the owner's own rows inside an org thread + a WhatsApp session row → only the agent-to-agent
     thread is listed (≥1 row), the owner/wa- rows are neither listed nor counted (steward #37121), and the moved
     goal is listed (≥1 row).
  3b. a t- thread between a former personal-lane agent (canopus) and seed IS counted and listed: the owner dropped
     the lane exclusion on 2026-10-11 (steward #43244; it was a3 #37444 B1).
  4. the same day again → silent (once-per-day dedup).
  6. the watermark is CONTENT (a3 #37444 B2): the newest edition's `compiled_through:` line; touching the file's
     mtime doesn't move it; no line or an unparseable one → the start of the edition's date; no edition → None;
     and the wake hands memory the value to write.
  5. compile_lag on the same fixture: an empty wire → no finding; the raw >7 days past log.md's last compile →
     the finding; a compile on the newest raw's day → no finding.
Exit 0 pass · 1 fail · 77 could-not-run.
"""
import datetime as dt
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BODY = Path(os.environ.get("LIBRARY_COMPILE_SRC") or REPO / "triggers" / "memory" / "library_compile.py")
DRIFT = Path(os.environ.get("DRIFT_SRC") or REPO / "memory" / "lints" / "drift.py")
for p in (BODY, DRIFT):
    if not p.exists():
        print(f"SKIP: {p.relative_to(REPO) if p.is_relative_to(REPO) else p} absent (gitignored) — nothing asserted.")
        sys.exit(77)
sys.path.insert(0, str(REPO))
from nucleus.sqlguard.estate import gate  # noqa: E402
gate("test_library_compile", REPO, deps=("psycopg",))


def load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


try:
    lc = load("library_compile_under_test", BODY)
    drift = load("drift_under_test", DRIFT)
    pr = load("pulse_run_lc", REPO / "nucleus" / "pulse_run.py")
    import psycopg
    from nucleus.sqlguard.fixture import fixture_db
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
        def __init__(self, state, connection):
            super().__init__(state)
            self._conn = connection

    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat()
    real_last_edition = lc._last_edition
    lc._last_edition = lambda: since                     # pin the window; the watermark has its own arms (6)

    def put(frm, to, thread, body="x"):
        conn.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES (%s,%s,%s,'chat',%s)",
                     (frm, to, thread, body))

    def threads_of(out):
        return out.split("Busiest threads:")[1].split("Goals that moved:")[0]

    print("library_compile:")
    check("1. an empty wire → silent", lc.library_compile(TempCtx({}, conn)) is None)

    put("canvas", "painter", "cv:0a1b2c")
    out = lc.library_compile(TempCtx({}, conn)) or ""
    check("2. a cv: row alone still rings (the count sees work)", out.startswith("OVERNIGHT EDITION DUE: 1 "), out[:80])
    check("2. …but lists NO thread (cv: is the owner's chat)", "cv:" not in threads_of(out) and
          threads_of(out).strip() == "", threads_of(out))
    check("2. …and no goal moved", "Goals that moved:\n  - (none)" in out, out)

    put("seed", "memory", "plan-9999")
    put("seed", "memory", "plan-9999")
    put("owner", "steward", "t-localmd-x", "an owner reply in an org thread")
    put("steward", "owner", "t-localmd-x", "an amendment to the owner")
    put("wa-147", "gemini", "t-family-x")
    conn.execute("INSERT INTO goals (title, owner, state) VALUES ('a goal that moved', 'seed', 'active')")
    st = {}
    out = lc.library_compile(TempCtx(st, conn)) or ""
    tl = threads_of(out)
    check("3. the agent-to-agent org thread is listed", "plan-9999: 2 rows" in tl, tl)
    check("3. owner/wa- rows in org threads are NOT listed", "t-localmd-x" not in tl and "t-family-x" not in tl, tl)
    check("3. …nor counted (cv 1 + plan 2 = 3)", out.startswith("OVERNIGHT EDITION DUE: 3 "), out[:80])
    check("3. the moved goal is listed", "a goal that moved" in out, out)

    lane = "canopus"
    put(lane, "seed", "t-lane-x", "a career-lane request")
    put("seed", lane, "t-lane-x", "seed's answer")
    out = lc.library_compile(TempCtx({}, conn)) or ""
    check(f"3b. a {lane}<->seed t- thread IS listed", "t-lane-x: 2 rows" in threads_of(out), threads_of(out))
    check("3b. …and counted (3 + 2 = 5)", out.startswith("OVERNIGHT EDITION DUE: 5 "), out[:80])
    check("3b. …and named in the who", lane in threads_of(out), threads_of(out))
    check("3b. the owner/wa- rows are still NOT listed", "t-localmd-x" not in threads_of(out)
          and "t-family-x" not in threads_of(out), threads_of(out))
    check("4. the same day again → silent (dedup)", lc.library_compile(TempCtx(st, conn)) is None)

    print("watermark:")
    with tempfile.TemporaryDirectory() as d:
        ch = Path(d)
        check("6. no edition → None", real_last_edition(ch) is None)
        ed = ch / "2026-10-09.md"
        ed.write_text('---\ntitle: "x"\ncompiled_through: "2026-10-09T10:59:03+00:00"\n---\n# x\n')
        (ch / "2026-10-08.md").write_text('---\ntitle: "y"\ncompiled_through: "2026-10-09T00:00:00+00:00"\n---\n')
        check("6. the newest edition's compiled_through is the watermark",
              real_last_edition(ch) == "2026-10-09T10:59:03+00:00", str(real_last_edition(ch)))
        os.utime(ed, (2_000_000_000, 2_000_000_000))       # a correction / restore / re-copy touches the file
        check("6. an mtime touch doesn't move it", real_last_edition(ch) == "2026-10-09T10:59:03+00:00",
              str(real_last_edition(ch)))
        ed.write_text('---\ntitle: "x"\n---\n# x\ncompiled_through: "2099-01-01T00:00:00+00:00"\n')
        check("6. no frontmatter line → the start of its date (a body line doesn't count)",
              real_last_edition(ch) == "2026-10-09T00:00:00+00:00", str(real_last_edition(ch)))
        ed.write_text('---\ncompiled_through: "yesterday-ish"\n---\n')
        check("6. an unparseable line → the start of its date", real_last_edition(ch) == "2026-10-09T00:00:00+00:00",
              str(real_last_edition(ch)))
    lc._last_edition = lambda: since
    out = lc.library_compile(TempCtx({}, conn)) or ""
    check("6. the wake hands memory the compiled_through value to write",
          "compiled_through: 20" in out and "{now}" not in out, out[-300:])

    print("compile_lag (drift.py):")
    ctx = TempCtx({}, conn)
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "log.md"
        conn.execute("DELETE FROM messages")
        log.write_text("2020-01-01 · compile · ancient\n")
        check("5. an empty wire → no finding", drift._compile_lag_findings(ctx.sql, log) == [])
        put("seed", "memory", "plan-9999")
        got = drift._compile_lag_findings(ctx.sql, log)
        check("5. raw >7d past the last compile → the finding", len(got) == 1 and "[compile-lag]" in got[0], str(got))
        log.write_text(f"{dt.date.today().isoformat()} · compile · tonight\n")
        check("5. a compile on the newest raw's day → no finding", drift._compile_lag_findings(ctx.sql, log) == [])
finally:
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    _fx.__exit__(None, None, None)

if fails:
    print(f"\nFAIL: {len(fails)} arm(s)")
    sys.exit(1)
print("\nPASS: library_compile + compile_lag, every SQL site run at 0 and ≥1 rows in a stamped fixture")
sys.exit(0)
