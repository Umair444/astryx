#!/usr/bin/env python3
"""Oracle for the CANVAS privacy pair: nucleus/canvas.py:share_blockers (the share GATE, tracked) and
triggers/steward/pii_sweep.py:pii_canvas (the SWEEP whose state it reads, gitignored).

    venv/bin/python tests/test_pii_canvas.py   (PII_SWEEP_SRC=<path> overrides the sweep body)

Everything runs on a stamped sqlguard fixture DB (the real schema.sql), never production. The GATE arms
run everywhere; the SWEEP arms need the gitignored body and otherwise SKIP 77 (partial), after the gate
arms have already run. Arms:
  G. the gate FAILS CLOSED: no sweep row → refused; a row with no completed scan → refused; content
     newer than the scan → refused ("retry within 5 minutes"); an open finding naming the canvas →
     refused, and the reason says republishing does NOT clear it (?v=N serves history); a scanned,
     clean canvas → allowed. A finding on ANOTHER canvas does not block this one.
  S. the sweep: an owner-PII shape in an OLD version of a SHARED canvas is found (history is
     guest-readable), tagged SHARED and rendered FIRST; an owner-only canvas is tagged owner-only; a
     live data value is scanned; the same state next run is silent; a canvas that becomes SHARED
     re-speaks; a pinned LOCATION is silent and never enters `open`; content written after the run's
     start is not scanned (and checked_at stays honest); deleting the row discharges the finding.
  E. end to end: the sweep's state, written to the trigger row, drives the real gate.
Exit 0 pass · 1 fail · 77 could-not-run (partial counts).
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

for _k in [k for k in os.environ if k.startswith("GIT_")]:
    del os.environ[_k]
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
FAKE_PHONE = "15555550123"          # the same synthetic shape test_pii_sweep_ledger uses
fails, skips = [], []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


try:
    import psycopg
    from nucleus import canvas as cv
    from nucleus.sqlguard.fixture import fixture_db
    _fx = fixture_db()
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"SKIP: fixture DB unavailable ({type(e).__name__}: {e}) — nothing asserted.")
    sys.exit(77)

conn = psycopg.connect(fx["dsn"], autocommit=True)


def canvas(user="owner", shared=()):
    return conn.execute("INSERT INTO canvases (title, agent, user_name, tier, shared_with) "
                        "VALUES ('t','painter',%s,'org',%s) RETURNING id", (user, list(shared))).fetchone()[0]


def version(cid, v, html, ago="1 hour"):
    conn.execute("INSERT INTO canvas_versions (canvas_id, version, html, author, ts) "
                 "VALUES (%s,%s,%s,'painter', now() - %s::interval)", (cid, v, html, ago))


def gate_row(state):
    conn.execute("DELETE FROM triggers WHERE agent='steward' AND name='pii_canvas'")
    if state is not None:
        conn.execute("INSERT INTO triggers (agent, name, schedule, kind, state) "
                     "VALUES ('steward','pii_canvas','*/5 * * * *','python',%s::jsonb)", (json.dumps(state),))


try:
    print("G. the share gate (tracked; fails closed):")
    c1 = canvas()
    version(c1, 1, "<p>clean</p>")
    gate_row(None)
    b = cv.share_blockers(conn, c1)
    check("no sweep row → refused (nothing has read this canvas)", b and "not registered" in b[0], str(b))
    gate_row({})
    b = cv.share_blockers(conn, c1)
    check("a sweep row with no completed scan → refused", b and "not completed a scan" in b[0], str(b))
    old = conn.execute("SELECT (now() - interval '2 hours')::text").fetchone()[0]
    gate_row({"checked_at": old.replace(" ", "T"), "open": {}})
    b = cv.share_blockers(conn, c1)
    check("content newer than the last scan → refused, retry within 5 minutes",
          b and "changed after the last privacy scan" in b[0], str(b))
    now_ = conn.execute("SELECT now()::text").fetchone()[0].replace(" ", "T")
    gate_row({"checked_at": now_, "open": {}})
    check("scanned and clean → allowed ([])", cv.share_blockers(conn, c1) == [], str(cv.share_blockers(conn, c1)))
    c2 = canvas()
    gate_row({"checked_at": now_, "open": {"h1": {"cid": c1, "loc": "x", "label": "phone-bare"}}})
    b = cv.share_blockers(conn, c1)
    check("an open finding on the canvas → refused, and the remedy says republishing does NOT clear it",
          b and "1 possible owner-PII" in b[0] and "?v=N" in b[0] and "does not clear" in b[0], str(b))
    check("a finding on ANOTHER canvas does not block this one", cv.share_blockers(conn, c2) == [],
          str(cv.share_blockers(conn, c2)))
    check("the gate's reasons carry no value (shapes only)",
          FAKE_PHONE not in json.dumps(cv.share_blockers(conn, c1)))

    print("\nS. the sweep (gitignored body):")
    BODY = Path(os.environ.get("PII_SWEEP_SRC") or REPO / "triggers" / "steward" / "pii_sweep.py")
    mod = None
    if BODY.exists():
        try:
            _s = importlib.util.spec_from_file_location("pii_canvas_under_test", BODY)
            mod = importlib.util.module_from_spec(_s)
            _s.loader.exec_module(mod)
            fire = mod.pii_canvas
            _p = importlib.util.spec_from_file_location("pulse_run_pc", REPO / "nucleus" / "pulse_run.py")
            pr = importlib.util.module_from_spec(_p)
            _p.loader.exec_module(pr)
        except Exception as e:  # noqa: BLE001
            print(f"  SKIP  sweep arms — body/runner not loadable ({type(e).__name__}: {e})")
            mod = None
    else:
        print(f"  SKIP  sweep arms — {BODY} absent (gitignored triggers/)")
    if mod is None:
        skips.append("sweep arms")
    else:
        class TempCtx(pr.Ctx):
            def __init__(self, state):
                super().__init__(state)
                self._conn = conn

        conn.execute("DELETE FROM canvas_versions"); conn.execute("DELETE FROM canvases")
        conn.execute("DELETE FROM canvas_data")
        st0 = {}
        check("EMPTY canvas tables → silent, and the scan still completes (checked_at set)",
              fire(TempCtx(st0)) is None and st0.get("checked_at"), str(st0))
        sh = canvas(shared=["guest1"])
        own = canvas()
        version(sh, 1, f"<p>call me on {FAKE_PHONE}</p>")       # an OLD version of a SHARED canvas
        version(sh, 2, "<p>cleaned up</p>")                      # the head is clean
        version(own, 1, f"<p>{FAKE_PHONE}</p>")
        conn.execute("INSERT INTO canvas_data (canvas_id, key, value, updated_by, updated_at) "
                     "VALUES (%s,'contact',%s::jsonb,'painter', now() - interval '1 hour')",
                     (own, json.dumps(FAKE_PHONE)))
        st = {}
        out = fire(TempCtx(st)) or ""
        check("a hit in an OLD version of a SHARED canvas is found (history is guest-readable)",
              f"canvas#{sh} v1" in out and "[SHARED]" in out, out)
        check("...and SHARED renders before owner-only", out.find("[SHARED]") < out.find("[owner-only]"), out)
        check("a live data VALUE is scanned too", f"canvas#{own} data[" in out, out)
        check("the report carries no value (shapes only)", FAKE_PHONE not in out, out)
        check("state records an honest checked_at and the cid of every open finding",
              st.get("checked_at") and all("cid" in r for r in st["open"].values()), str(st)[:300])
        check("the same content next run → silent", fire(TempCtx(st)) is None)
        conn.execute("UPDATE canvases SET shared_with = ARRAY['guest2'] WHERE id=%s", (own,))
        out2 = fire(TempCtx(st)) or ""
        check("a canvas that becomes SHARED re-speaks its findings (NOW SHARED)",
              "NOW SHARED" in out2 and f"canvas#{own}" in out2, out2)
        hsh = [h for h, r in st["open"].items() if r["cid"] == sh]
        st["pinned"] = {h: "fixture ruling" for h in hsh}
        fire(TempCtx(st))
        check("a pinned LOCATION is silent and never re-enters `open`",
              not any(r["cid"] == sh for r in st["open"].values()), str(st["open"]))
        version(sh, 3, f"<p>{FAKE_PHONE} again</p>", ago="-1 hour")   # written AFTER this run starts
        out3 = fire(TempCtx(st)) or ""
        check("content written after the run's start is not scanned this run", f"canvas#{sh} v3" not in out3, out3)

        print("\nE. end to end — the sweep's state drives the real gate:")
        gate_row(st)
        b_sh = cv.share_blockers(conn, sh)
        check("the shared canvas's future version (newer than the scan) still blocks it — fail closed",
              any("changed after" in x for x in b_sh), str(b_sh))
        b_own = cv.share_blockers(conn, own)
        check("the canvas with an open finding is refused", any("owner-PII" in x for x in b_own), str(b_own))
        conn.execute("DELETE FROM canvas_versions WHERE canvas_id=%s", (own,))
        conn.execute("DELETE FROM canvas_data WHERE canvas_id=%s", (own,))
        fire(TempCtx(st))
        gate_row(st)
        check("removing the rows discharges the finding, and the gate opens",
              cv.share_blockers(conn, own) == [], str(cv.share_blockers(conn, own)))
finally:
    conn.close()
    _fx.__exit__(None, None, None)

if fails:
    print(f"\nFAIL: {len(fails)} arm(s)")
    sys.exit(1)
if skips:
    print(f"\nSKIP (partial): {', '.join(skips)} — the gate arms passed")
    sys.exit(77)
print("\nALL PASS")
