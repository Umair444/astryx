"""Oracle for triggers/steward/owner_crisis.py: the owner wrote crisis-shaped words to an agent, and the owner-facing
lead must be woken, with ids only, and woken again if nobody answers (seed's ruling, conditions 1-3).

Three layers:
  * pure arms over hits/decide/wake_body, synthetic text only;
  * the trigger EXECUTED on a stamped fixture DB (never production): the baseline warning, the wake, guarded
    silence, what counts as SEEN (medic's ack probe), and a hit after SEEN waking again (medic's cap probe);
  * LIVE arms, READ-ONLY on the org's own DB: the pattern over every owner row matches exactly the pinned crisis
    rows, and the pinned benign match ("not ...") is among them, so negation stays unhandled on purpose; and the
    INSTALL arm: the registered trigger row carries premium>0, or its wake is held under quota pressure.

A SKIP is not a pass: with any layer skipped and nothing failed, this exits 77.

TIER: this file is public. It holds no owner text and no message ids. The live pins live in a gitignored file
(OWNER_CRISIS_PINS, default <estate>/var/steward/owner_crisis.pins.json, {"crisis": [ids], "benign": [ids]}).
With no pins, the live arms SKIP LOUDLY. The body is gitignored: OWNER_CRISIS_SRC names a staged copy. With
neither, the whole oracle SKIPS (77)."""
from __future__ import annotations

import json
import os
import runpy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402

def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)
sys.path.insert(0, str(REPO))
SRC = os.environ.get("OWNER_CRISIS_SRC") or str(ESTATE / "triggers" / "steward" / "owner_crisis.py")
if not Path(SRC).exists():
    print("SKIP: triggers/steward/owner_crisis.py not present (gitignored body): the owner-crisis guard was NOT "
          "verified this run")
    sys.exit(77)
M = runpy.run_path(SRC)
hits, decide, wake_body, thread_of = M["hits"], M["decide"], M["wake_body"], M["thread_of"]
owner_crisis, CAP_H, ACK_MIN, LEAD = M["owner_crisis"], M["CAP_H"], M["ACK_MIN"], M["LEAD"]

FAILS, SKIPS = [], []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILS.append(name)


T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
SECRET = "a body that must never be copied"

print("the matcher (synthetic text):")
rows = [{"id": 1, "to_agent": "x", "thread": "tx", "body": "I am so done with life"},
        {"id": 2, "to_agent": "x", "body": "ship the release tonight"},
        {"id": 3, "to_agent": "y", "body": "I'm not suicidal, just tired"},
        {"id": 4, "to_agent": "x", "body": None},
        {"id": 5, "to_agent": "x", "body": "I might HURT MYSELF"}]
h = hits(rows)
check("crisis words match, ordinary words don't, a NULL body doesn't crash", [r["id"] for r in h] == [1, 3, 5], h)
check("NEGATION IS NOT HANDLED: 'not suicidal' matches and wakes (a missed wake costs more than an extra one)",
      any(r["id"] == 3 for r in h), h)
check("a hit carries id, holder and thread, never the body", all(set(r) == {"id", "holder", "thread"} for r in h), h)

print("decide (pure):")
w, st = decide(hits(rows[:1]), {}, {"last": 0}, T0)
check("a first hit wakes once, for its holder", [x[0] for x in w] == ["x"], w)
check("the wake names the id and the holder", "#1" in w[0][1] and "x" in w[0][1], w)
w2, st2 = decide(hits([rows[4]]), {}, st, T0 + timedelta(minutes=10))
check("a second hit for the same holder inside the cap: no wake", w2 == [], w2)
check("...but its id is noted for the re-wake", st2["said"]["x"]["ids"] == [1, 5], st2)
w3, st3 = decide([], {"x": False}, st2, T0 + timedelta(minutes=ACK_MIN - 1))
check(f"no seed row, {ACK_MIN - 1} min after the wake: not yet", w3 == [], w3)
w4, st4 = decide([], {"x": False}, st3, T0 + timedelta(minutes=ACK_MIN))
check(f"no seed row at {ACK_MIN} min: ONE re-wake, naming every id", len(w4) == 1 and "#1, #5" in w4[0][1], w4)
w5, _ = decide([], {"x": False}, st4, T0 + timedelta(minutes=ACK_MIN + 30))
check("the re-wake happens once, then back to the cap", w5 == [], w5)
w6, _ = decide([], {"x": True}, st3, T0 + timedelta(minutes=ACK_MIN + 5))
check("a seed row landed: no re-wake", w6 == [], w6)
w7, _ = decide([{"id": 7, "holder": "x", "thread": "tx"}], {}, st4, T0 + timedelta(hours=1))
check("a hit AFTER the re-wake went out wakes again, as NEW ROWS SINCE SEEN, naming only the new id",
      len(w7) == 1 and "NEW ROWS SINCE SEEN" in w7[0][1] and "#7" in w7[0][1] and "#1" not in w7[0][1], w7)
# medic's cap probe, pure: crisis #1 wakes, seed sees it at 40 min, crisis #9 at 3h must wake
_, sa = decide([{"id": 1, "holder": "x", "thread": "tx"}], {}, {"last": 0}, T0)
wa, sa = decide([], {"x": True}, sa, T0 + timedelta(minutes=40))
wb, sb = decide([{"id": 9, "holder": "x", "thread": "tx"}], {}, sa, T0 + timedelta(hours=3))
check("medic cap probe: seen at 40 min, a second crisis at 3h wakes (NEW, #9), not swallowed by a cap",
      wa == [] and len(wb) == 1 and "NEW ROWS SINCE SEEN" in wb[0][1] and "#9" in wb[0][1], (wa, wb))
wc, _ = decide([], {}, sb, T0 + timedelta(hours=3, minutes=ACK_MIN))
check("...and that new wake is guarded too: unseen at 30 min, one re-wake", len(wc) == 1 and "#9" in wc[0][1], wc)
wd, sd = decide([], {}, sb, T0 + timedelta(hours=3 + CAP_H))
check(f"an overdue unseen wake is never pruned away silently: at {CAP_H}h it still re-wakes, then its state goes",
      len(wd) == 1 and "#9" in wd[0][1] and "x" not in sd["said"], (wd, sd))
w8, _ = decide(hits(rows), {}, {"last": 0}, T0)
check("two holders, two wakes, one each", sorted(x[0] for x in w8) == ["x", "y"], w8)

print("the trigger EXECUTED on a fixture DB:")
try:
    import importlib.util as _ilu
    _p = _ilu.spec_from_file_location("pulse_run_oc", REPO / "src" / "astryx" / "pulse" / "pulse_run.py")
    _pr = _ilu.module_from_spec(_p)
    _p.loader.exec_module(_pr)
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db
    _fx = fixture_db()
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"  SKIP  fixture arms: fixture/runner unavailable ({type(e).__name__}: {e})")
    SKIPS.append("fixture")
    fx = None
if fx is not None:
    conn = psycopg.connect(fx["dsn"], autocommit=True)
    try:
        class TempCtx(_pr.Ctx):
            def __init__(self, state, connection):
                super().__init__(state)
                self._conn = connection

        def run(state):
            c = TempCtx(state, conn)
            out = owner_crisis(c)
            return out, c.wakes, c.state

        def ins(frm, to, body, thread=None, ago="0 minutes"):
            return conn.execute("INSERT INTO messages (from_agent, to_agent, thread, body, ts) VALUES "
                                "(%s,%s,%s,%s, now() - %s::interval) RETURNING id",
                                (frm, to, thread, body, ago)).fetchone()[0]

        ins("owner", "holder-a", "done with life " + SECRET, ago="1 day")
        out, wk, st = run({})
        check("REAL SQL: the first run baselines, and TELLS seed once (a reset state would otherwise be silent)",
              out is None and len(wk) == 1 and wk[0]["to_agent"] == LEAD and "baselined at id" in wk[0]["body"]
              and SECRET not in wk[0]["body"] and st.get("last") is not None, (out, wk, st))
        out, wk, st = run(st)
        check("REAL SQL: nothing new, nothing woken", wk == [], wk)
        a = ins("owner", "holder-a", "I want to die " + SECRET, thread="crisis-a")
        ins("owner", "holder-a", "ordinary chat")
        out, wk, st = run(st)
        check("REAL SQL: a new crisis row wakes seed, on the holder's thread, from steward",
              len(wk) == 1 and wk[0]["to_agent"] == LEAD and wk[0]["thread"] == thread_of("holder-a")
              and wk[0]["from_agent"] == "steward", wk)
        check("REAL SQL: the wake names the id, and copies NO body text",
              bool(wk) and f"#{a}" in wk[0]["body"] and SECRET not in wk[0]["body"], wk)
        check("REAL SQL: the trigger returns None (its only output is the wake to seed)", out is None, out)
        st["said"]["holder-a"]["at"] = (datetime.now(timezone.utc) - timedelta(minutes=ACK_MIN + 1)).isoformat()
        ins("seed", "someone-else", "unrelated", thread="t-other")
        ins("seed", "owner", "routine digest", thread="t-digest")       # medic's ack probe: must NOT count as seen
        ins("seed", "holder-a", "routine chat", thread="t-misc")        # nor a seed row to the holder elsewhere
        out, wk, st = run(st)
        check(f"medic ack probe, REAL SQL: unrelated seed->owner and seed->holder rows don't count; at {ACK_MIN} min, "
              f"ONE re-wake", len(wk) == 1 and "NOT SEEN YET" in wk[0]["body"] and f"#{a}" in wk[0]["body"], wk)
        out, wk, st = run(st)
        check("REAL SQL: the re-wake is not repeated", wk == [], wk)
        b = ins("owner", "holder-b", "thinking about self-harm " + SECRET, thread="crisis-b")
        out, wk, st = run(st)
        st["said"]["holder-b"]["at"] = (datetime.now(timezone.utc) - timedelta(minutes=ACK_MIN + 1)).isoformat()
        ins("seed", "holder-b", "I see it", thread="crisis-b")
        out, wk2, st = run(st)
        check("REAL SQL: a seed row on the thread the crisis came in on counts as seen: no re-wake",
              len(wk) == 1 and f"#{b}" in wk[0]["body"] and wk2 == [], (wk, wk2))
        c = ins("owner", "holder-c", "no point living " + SECRET, thread="crisis-c")
        out, wk, st = run(st)
        st["said"]["holder-c"]["at"] = (datetime.now(timezone.utc) - timedelta(minutes=ACK_MIN + 1)).isoformat()
        ins("seed", "canopus", "on it", thread=thread_of("holder-c"))
        out, wk2, st = run(st)
        check("REAL SQL: a seed row on t-owner-crisis-<holder> counts as seen: no re-wake", len(wk) == 1 and wk2 == [],
              (wk, wk2))
        d = ins("owner", "holder-c", "want to die " + SECRET, thread="crisis-c")
        out, wk3, st = run(st)
        check("medic cap probe, REAL SQL: a second crisis after SEEN wakes again, as NEW, naming only the new row",
              len(wk3) == 1 and "NEW ROWS SINCE SEEN" in wk3[0]["body"] and f"#{d}" in wk3[0]["body"]
              and f"#{c}" not in wk3[0]["body"], wk3)
    finally:
        conn.close()
        _fx.__exit__(None, None, None)

print("LIVE, read-only, on the org's own DB:")
pins_path = Path(os.environ.get("OWNER_CRISIS_PINS") or ESTATE / "var" / "steward" / "owner_crisis.pins.json")
try:
    dsn = _astryx("config", "dsn", ESTATE / ".env")   # the resolver: the environment first, else the HOME's .env
except LookupError:
    dsn = None
if dsn and _astryx("orgs", "is_fixture", dsn):
    print("  SKIP  live arms: the DSN names a fixture database, not the org's own (its owner history is not there)")
    dsn = None
if not pins_path.exists() or not dsn:
    print(f"  SKIP  live arms: {'no pins file' if not pins_path.exists() else 'no DSN'} (gitignored): the pattern "
          f"was NOT checked against the real owner history this run")
    SKIPS.append("live")
else:
    import psycopg
    pins = json.loads(pins_path.read_text())
    crisis, benign = set(pins.get("crisis") or []), set(pins.get("benign") or [])
    with psycopg.connect(dsn, autocommit=True) as lc:
        lc.execute("SET default_transaction_read_only = on")
        live = lc.execute("SELECT id, to_agent, body FROM messages WHERE from_agent='owner'").fetchall()
    got = {r["id"] for r in hits([{"id": i, "to_agent": t, "body": b} for i, t, b in live])}
    check(f"LIVE: over {len(live)} owner rows the pattern hits exactly the pinned crisis rows "
          f"(0 outside them, all of them inside)", got == crisis,
          f"outside={len(got - crisis)} missed={len(crisis - got)}")
    check("LIVE: the pinned benign match ('not ...') is a hit, so it wakes", bool(benign) and benign <= got,
          f"benign={len(benign)} hit={len(benign & got)}")

print("INSTALL, read-only: the registered trigger row")
if not dsn:
    print("  SKIP  install arm: no DSN: premium NOT verified")
    SKIPS.append("install")
else:
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as lc:
        lc.execute("SET default_transaction_read_only = on")
        row = lc.execute("SELECT premium, enabled FROM triggers WHERE agent='steward' AND name='owner_crisis'").fetchone()
    if row is None:
        print("  SKIP  install arm: steward/owner_crisis is not registered yet (not landed): premium NOT verified")
        SKIPS.append("install")
    else:
        check("INSTALL: the trigger row carries premium>0, so its wake is never held under quota pressure",
              int(row[0] or 0) > 0, f"premium={row[0]}")
        check("INSTALL: the trigger row is enabled", bool(row[1]), f"enabled={row[1]}")

print(f"\n{'FAIL' if FAILS else 'OK'}: {len(FAILS)} failed" + (f"; skipped: {', '.join(SKIPS)}" if SKIPS else ""))
sys.exit(1 if FAILS else 77 if SKIPS else 0)
