#!/usr/bin/env python3
"""sqlguard ENFORCEMENT (goal 4243, B1). judge.py grades; this decides. Kept apart so each can be tested alone.

    venv/bin/python -m nucleus.sqlguard.enforce <trace_dir>    # rc 0 pass · 1 RED · 77 NOT SEARCHED (run level)

RED:
  R-NEW     a site below RESPONSIVE that the ledger doesn't list (growth is only via `ledger admit`, whose reason
            then prints every run). EXCEPT EX3: a site capped at FIXTURE-DDL
            SOLELY because every covering gate belongs to a LISTED extractor still inside its window is REPORTED.
  R-STALE   a ledger row whose site climbed to RESPONSIVE, or no longer exists. This forces the shrink.
  R-BLIND   reverse agreement: runtime saw SQL the inventory doesn't know.
  R-CLOCK   a site NOT SEARCHED for more than NS_RUNS runs AND more than NS_DAYS days (per site, in
            sqlguard_seen).
  R-LEAK    this run's astryx_fx_<run> database is still present; or a foreign astryx_fx_* has been present
            ≥ LEAK_RUNS runs AND ≥ LEAK_AGE since first seen (pg_database records no creation time).
  R-EXTRACT an extractor derived from the trace that isn't listed; a listed one whose gate COMPLETED rc=0 without
            building an unstamped fixture (stale: shrink it); a listed one past EX_DAYS (EX2 clock).
            A listed extractor whose gate skipped or failed is left alone (the F-b absence rule).
NOT SEARCHED (run level, rc 77, never a pass): shim internal errors; triggers/ absent; the canary site not
RESPONSIVE; the state table absent (apply schema.sql).
Every answer prints judge.REMAINDER, the ceiling of what RESPONSIVE certifies.
"""
import datetime
import json
import os
import sys

import psycopg

from nucleus.sqlguard import judge
from nucleus.sqlguard.fixture import live_dsn, run_id
from nucleus.sqlguard.privacy import handle, label, ledger_key, ignored

NS_RUNS, NS_DAYS = 7, 3                    # the per-site NOT SEARCHED clock (declared)
LEAK_RUNS, LEAK_AGE = 3, datetime.timedelta(hours=1)
EX_DAYS = 30                               # EX2: a listed extractor's migration window (declared)
CANARY = "nucleus/sqlguard/canary.py::canary"


def load_ledger(path=None):
    p = path or (judge.REPO / "nucleus" / "sqlguard" / "ledger.json")
    return json.loads(open(p).read()) if os.path.exists(p) else None


def _clock(conn, kind, keys):
    """Upsert the keys seen this run, delete resolved ones, and return {key: (first_seen, runs)}."""
    now = datetime.datetime.now(datetime.UTC)
    out = {}
    for k in keys:
        r = conn.execute("INSERT INTO sqlguard_seen (kind, key) VALUES (%s,%s) ON CONFLICT (kind, key) DO UPDATE "
                         "SET last_seen=now(), runs=sqlguard_seen.runs+1 RETURNING first_seen, runs",
                         (kind, k)).fetchone()
        out[k] = r
    conn.execute("DELETE FROM sqlguard_seen WHERE kind=%s AND NOT (key = ANY(%s))", (kind, list(keys)))
    return out, now


def enforce(trace_dir, ledger=None, dsn=None, rep=None):
    ledger = ledger if ledger is not None else load_ledger()
    # The ledger's covering map (the last clean run) is unioned in, so a gate that crashed before reaching a
    # site still COVERS it and the site grades NOT SEARCHED, never a false UNEXECUTED (C1).
    rep = rep or judge.judge(trace_dir, stored_covering=(ledger or {}).get("covering"))
    red, report, not_searched = [], [], list(rep["run_not_searched"])
    if ledger is None:
        not_searched.append("no ledger.json: seed it first (ledger seed)")
        return {"rc": 77, "red": red, "report": report, "not_searched": not_searched}
    rows = ledger.get("rows", {})
    listed = ledger.get("extractors", {})
    gates = rep["gates"]
    today = datetime.date.today()

    canary = [v for k, v in rep["sites"].items() if k.startswith(CANARY + "\x1f")]
    if not canary or any(v["rung"] != "RESPONSIVE" for v in canary):
        not_searched.append(f"canary not RESPONSIVE ({[v['rung'] for v in canary] or 'absent'}): "
                            f"the shim can't be trusted this run")

    # EX2 window: a listed extractor inside its window shields its sites (EX3); past it → RED.
    open_gates = set()
    for f, meta in listed.items():
        since = datetime.date.fromisoformat(meta.get("listed_since", str(today)))
        if (today - since).days > EX_DAYS:
            red.append(f"R-EXTRACT {f}: listed {(today - since).days}d > {EX_DAYS}d (trip: {meta.get('trip')})")
        else:
            open_gates.update(meta.get("gates", []))
    derived = rep["extractors"]
    for f, gs in derived.items():
        if f not in listed:
            red.append(f"R-EXTRACT {f} builds an UNSTAMPED fixture and isn't listed: migrate it to "
                       f"nucleus/sqlguard/fixture.py, or list it with a reason and a trip")
    for f, meta in listed.items():
        if f not in derived:
            gs = meta.get("gates", [])
            if gs and all(gates.get(g) == 0 for g in gs):
                red.append(f"R-EXTRACT {f} no longer builds an unstamped fixture (its gate completed rc=0): "
                           f"remove it from the list (shrink)")
            # else: a skipped or failed gate says nothing about absence (F-b), so leave it listed

    ns_keys = []
    for key, s in rep["sites"].items():
        fn, _, text = key.partition("\x1f")
        row = rows.get(ledger_key(key))
        if s["rung"] == "RESPONSIVE":
            if row:
                red.append(f"R-STALE {label(key)}: now RESPONSIVE but still listed as {row['debt']} (shrink)")
            continue
        if s["rung"] == "NOT SEARCHED":
            ns_keys.append(key)
            continue
        if row:
            if row.get("reason", "seed") != "seed":             # an ADMITTED row: its reason prints every run
                report.append(f"ADMITTED {label(key)} ({row['debt']}, {row.get('admitted', '?')}): {row['reason']}")
            continue                                            # known debt, with its address
        cov = rep["covering"].get(key, [])
        if s["rung"] == "EXECUTED/FIXTURE-DDL" and cov and set(cov) <= open_gates:
            report.append(f"EX3 {label(key)}: capped at FIXTURE-DDL by a LISTED extractor (reported, not RED)")
            continue
        red.append(f"R-NEW {label(key)}: {s['rung']} and not in the ledger. Make it RESPONSIVE, or admit it: "
                   f"ledger admit <trace_dir> {handle(key)} '<reason>'")
    live_keys = {ledger_key(k) for k in rep["sites"]}
    for key in rows:
        if key not in live_keys:
            shown = "a hashed (gitignored-origin) site" if key.startswith("sha256:") else label(key)
            red.append(f"R-STALE {shown}: listed, but the site no longer exists (shrink)")
    for b in rep["blind"]:
        path = b["frame"][0]
        what = "" if (path.startswith("tier/") or ignored(path)) else f": {b['t'][:70]!r}"
        red.append(f"R-BLIND {path}::{b['frame'][1]} ran SQL the inventory doesn't know{what}")

    try:
        with psycopg.connect(dsn or live_dsn(), autocommit=True, connect_timeout=5) as c:
            if not c.execute("SELECT to_regclass('sqlguard_seen')").fetchone()[0]:
                not_searched.append("state table sqlguard_seen absent: apply nucleus/schema.sql")
            else:
                seen, now = _clock(c, "ns_site", [ledger_key(k) for k in ns_keys])   # P1: digests at rest too
                for k, (first, runs) in seen.items():
                    age = now - first
                    if runs > NS_RUNS and age.days >= NS_DAYS:
                        red.append(f"R-CLOCK {label(k)}: NOT SEARCHED for {runs} runs / {age.days}d")
                for f, meta in listed.items():                  # P2: machine-checkable trips
                    trip = meta.get("trip") or {}
                    if isinstance(trip, dict) and trip.get("goal") and c.execute(
                            "SELECT 1 FROM goals WHERE id=%s AND state=%s", (trip["goal"], trip.get("state", "done"))
                    ).fetchone():
                        red.append(f"R-EXTRACT {f}: its trip fired (goal {trip['goal']} is "
                                   f"{trip.get('state', 'done')}), so migrate it to nucleus/sqlguard/fixture.py")
                fx = [r[0] for r in c.execute("SELECT datname FROM pg_database WHERE datname LIKE 'astryx_fx_%'")]
                mine = f"astryx_fx_{run_id()}_".lower()
                for d in fx:
                    if d.startswith(mine):
                        red.append(f"R-LEAK {d}: this run's fixture DB is still present")
                foreign = [d for d in fx if not d.startswith(mine)]
                fseen, now = _clock(c, "fx_db", foreign)
                for d, (first, runs) in fseen.items():
                    if runs >= LEAK_RUNS and now - first >= LEAK_AGE:
                        red.append(f"R-LEAK {d}: a foreign fixture DB present for {runs} runs since {first:%F %T}")
    except psycopg.Error as e:
        not_searched.append(f"state/leak checks couldn't run: {type(e).__name__}")

    from nucleus.sqlguard import privacy
    if privacy.ERRORS:                                             # a3 D-P: the privacy authority couldn't answer
        not_searched.append(f"privacy classification failed ({len(privacy.ERRORS)}); findings for those "
                            f"sites were redacted, never printed in plaintext")
    rc = 77 if not_searched else (1 if red else 0)
    return {"rc": rc, "red": red, "report": report, "not_searched": not_searched}


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ASTRYX_SQLGUARD_DIR", "")
    led = load_ledger()
    rep = judge.judge(d, stored_covering=(led or {}).get("covering"))
    judge.print_report(rep)
    judge.write_report(d, rep)                  # ledger admit reads it
    out = enforce(d, ledger=led, rep=rep)
    for n in out["not_searched"]:
        print(f"  NOT SEARCHED: {n}")
    for r in out["red"]:
        print(f"  \033[31m✗\033[0m {r}")
    for r in out["report"]:
        print(f"  ○ {r}")
    print(f"sqlguard enforce: rc={out['rc']} · RED {len(out['red'])} · reported {len(out['report'])} · "
          f"not-searched {len(out['not_searched'])}")
    print("  " + judge.REMAINDER)
    sys.exit(out["rc"])
