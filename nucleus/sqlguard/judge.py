#!/usr/bin/env python3
"""The sqlguard judge: joins the static inventory with the runtime trace and grades every site (goal 4243).

    venv/bin/python -m nucleus.sqlguard.judge <trace_dir>        # REPORT-ONLY (exit 0); enforce.py decides

ATTRIBUTION (#21519, fixes V2 + V3). Walk a statement's repo frames innermost-first. The site is the first frame
whose function's inventoried literal set CONTAINS the executed text, keyed (function, text). Otherwise it's the
first frame whose function holds an unresolved site, at FUNCTION level (FALLBACK).
- Only SQL SITES are subjects: DDL, SET and COMMENT (e.g. the applier's whole-file apply) are not.
- An oracle's OWN statement is not a subject: innermost repo frame in tests/, no inventoried function on the
  stack.
- Anything else with no SQL-bearing function on its stack is BLIND: reverse agreement, the inventory missed it.

RUNGS. UNEXECUTED → EXECUTED → RESPONSIVE (CORRECT belongs to the mutant battery). NOT SEARCHED is orthogonal.
- Credit: a READ counts from the live DB's `public` or a fixture relation with a valid stamp. A WRITE counts
  toward EXECUTED from live `public` but reaches RESPONSIVE only in stamped fixtures (#21938).
- Anything else is FIXTURE-DDL: EXECUTED at most.
- (W): row count took both 0 and ≥1. N/A without WHERE/HAVING; NOT-EVALUATED for an aggregate without
  GROUP BY.
- (P): every computed bool column took two values.
- Evidence is ASYMMETRIC (#21522): a positive counts from any gate's rc. A negative verdict (UNEXECUTED,
  NOT-RESPONSIVE) stands only if every COVERING gate of the site exited 0 (C1); otherwise the site is
  NOT SEARCHED.
- The covering map comes from the last clean run (stored beside the ledger). With no stored map, this run's
  own trace is the map, and the report says so.
"""
import collections
import glob
import json
import os
import re
import sys
from pathlib import Path

from nucleus.sqlguard import drivers, inventory
from nucleus.sqlguard.normalize import is_site, is_write

REPO = inventory.REPO
_WHERE = re.compile(r"\b(where|having)\b")
# ANYWHERE in the statement, not anchored: a test's hand DDL batch often leads with a comment, a DROP or a SET,
# and an anchored match silently under-derives the extractor list. (It also makes the applier exclusion below
# load-bearing by STRUCTURE: schema.sql leads with a comment, so an anchored match only skipped the applier by luck.)
_CREATE = re.compile(r"\bcreate\s+(?:temp\s+|temporary\s+|unlogged\s+)?table\b")
APPLIER = "nucleus/sqlguard/fixture.py"
_AGG = re.compile(r"\b(count|sum|max|min|avg|bool_or|bool_and|array_agg|string_agg|jsonb_agg)\s*\(")


def _live_db():
    from psycopg.conninfo import conninfo_to_dict
    from nucleus.sqlguard.fixture import live_dsn
    return conninfo_to_dict(live_dsn()).get("dbname")


def load_traces(d, untraced=None):
    recs, shim_errors = [], 0
    for f in sorted(glob.glob(os.path.join(d, "trace-*.jsonl"))):
        for line in open(f, errors="replace"):
            try:
                r = json.loads(line)
            except ValueError:
                shim_errors += 1
                continue
            if "shim_error" in r:
                shim_errors += 1
            elif "untraced_child" in r:
                if untraced is not None:
                    untraced.setdefault(r["untraced_child"], set()).add(r.get("gate", ""))
            else:
                recs.append(r)
    return recs, shim_errors


def load_gates(d):
    out = {}
    p = os.path.join(d, "gates.tsv")
    if os.path.exists(p):
        for line in open(p):
            label, _, rc = line.rstrip("\n").rpartition("\t")
            if label:
                out[label] = int(rc)
    return out


def attribute(rec, fns, oracle=None):
    """(site_key, text, kind), kind in {'site','fallback','oracle','blind'}. ONE rule, TEXT PROVENANCE: the owner
    is the first frame (innermost out) whose function's literal set CONTAINS the executed text. A production
    owner makes it a site; a tests/ owner makes it the oracle's own. That holds even when the probe is routed
    through a production helper like Ctx.sql, which no frame-position guess can see. With no text owner,
    fall back to the first frame holding an unresolved site (production → FALLBACK, test → oracle). With
    neither, it's BLIND: runtime saw SQL the inventory doesn't know."""
    oracle = oracle or {}
    t = rec["t"]
    frames = rec.get("frames") or []
    for rel, qn, _ in frames:
        key = f"{rel}::{qn}"
        if key in fns and t in fns[key]["sites"]:
            return key, t, "site"
        if key in oracle and t in oracle[key]["sites"]:
            return None, t, "oracle"
    for rel, qn, _ in frames:
        key = f"{rel}::{qn}"
        if key in fns and fns[key]["unresolved"]:
            return key, "*", "fallback"
        if key in oracle and oracle[key]["unresolved"]:
            return None, t, "oracle"
    if any(t in f["sites"] for f in fns.values()):
        return None, t, "direct"          # a KNOWN subject text, run with no owning function on the stack
    return None, t, "blind"


def judge(trace_dir, inv=None, covering=None, stored_covering=None):
    """covering REPLACES the map (tests); stored_covering (the ledger's, from the last clean run, keyed by
    privacy.ledger_key) is UNIONED with this run's. That's what lets a site whose covering gate crashed before
    reaching it grade NOT SEARCHED instead of a false UNEXECUTED: this run's trace alone never names a gate for
    a statement it didn't execute."""
    inv = inv or inventory.build()
    fns = inv["functions"]
    live = _live_db()
    untraced = {}
    recs, shim_errors = load_traces(trace_dir, untraced)
    gates = load_gates(trace_dir)
    ev = collections.defaultdict(lambda: {"ok": 0, "credited": 0, "fixture_ddl": 0, "zero": False, "pos": False,
                                          "p": {}, "gates": set(), "fallback": False, "write": False,
                                          "fx_zero": False, "fx_pos": False, "fx_p": {}})
    blind, direct, oracle_own = [], [], 0
    driver_internal = collections.Counter()         # "name@version" -> n: after tiers 1+2, never above them
    extractors = {}                                  # F-b: test file -> gates, derived from the trace
    for r in recs:
        if _CREATE.search(r["t"]) and r.get("ok"):
            fr = r.get("frames") or []
            if not any(f[0] == APPLIER for f in fr):
                tf = next((f[0] for f in fr if f[0].startswith("tests/")), None)
                if tf:
                    extractors.setdefault(tf, set()).add(r.get("gate", ""))
    for r in recs:
        if not is_site(r["t"]):
            continue
        key, text, kind = attribute(r, fns, inv.get("oracle"))
        if kind == "oracle":
            oracle_own += 1
            continue
        if kind == "direct":
            # e.g. a test executing esc.ORG_SILENCE_EPISODES_SQL itself. Crediting the owning site would be
            # text-only credit (V3, the false-credit direction), so it earns nothing, and it isn't blind.
            direct.append({"t": r["t"][:120], "frame": (r.get("frames") or [["?", "?", 0]])[0]})
            continue
        if kind == "blind":
            drv = r.get("driver") or "psycopg"
            if drivers.is_internal(r["t"], drv):
                driver_internal[f"{drv}@{drivers.version(drv)}"] += 1     # no credit, not blind, COUNTED
                continue
            blind.append({"t": r["t"][:120], "frame": (r.get("frames") or [["?", "?", 0]])[0]})
            continue
        e = ev[(key, text)]
        e["fallback"] = kind == "fallback"
        e["write"] = is_write(r["t"])
        if r.get("gate"):
            e["gates"].add(r["gate"])
        if not r.get("ok"):
            continue
        e["ok"] += 1
        stamped_fx = str(r.get("db", "")).startswith("astryx_fx_") and r.get("stamped") is True
        live_public = r.get("db") == live and r.get("schema") == "public"
        if not (stamped_fx or live_public):
            e["fixture_ddl"] += 1
            continue
        e["credited"] += 1
        if e["write"] and not stamped_fx:
            continue                                  # live DML is observed, never exercised for credit (#21938)
        rows = r.get("rows", -1)
        if rows == 0:
            e["zero"] = True
        elif rows and rows > 0:
            e["pos"] = True
        for col, vals in (r.get("p") or {}).items():
            e["p"].setdefault(col, set()).update(v if v is not None else "\0NULL" for v in vals)
        if stamped_fx:                                # the REPRODUCIBLE half: a fixture's data is the oracle's own
            e["fx_zero"] |= rows == 0
            e["fx_pos"] |= bool(rows and rows > 0)
            for col, vals in (r.get("p") or {}).items():
                e["fx_p"].setdefault(col, set()).update(v if v is not None else "\0NULL" for v in vals)

    if covering is None:
        covering = {f"{k}\x1f{t}": sorted(e["gates"]) for (k, t), e in ev.items()}
        if stored_covering:
            from nucleus.sqlguard.privacy import ledger_key
            for key, fn in fns.items():
                for t in list(fn["sites"]) + (["*"] if fn["unresolved"] else []):
                    k = f"{key}\x1f{t}"
                    old = stored_covering.get(ledger_key(k))
                    if old:
                        covering[k] = sorted(set(covering.get(k, [])) | set(old))
    sites = {}
    for key, fn in fns.items():
        texts = list(fn["sites"]) + (["*"] if fn["unresolved"] else [])
        for t in texts:
            e = ev.get((key, t))
            cov = covering.get(f"{key}\x1f{t}", [])
            complete = all(gates.get(g, 0) == 0 for g in cov)          # empty set = vacuously complete
            if not e or e["ok"] == 0:
                # a script launched untraced (cleared env) WAS run, just not observed: that's absence of
                # evidence, never evidence of absence
                rung = "NOT SEARCHED" if key.split("::")[0] in untraced or not complete else "UNEXECUTED"
            elif e["credited"] == 0:
                rung = "EXECUTED/FIXTURE-DDL"
            else:
                w_need = bool(_WHERE.search(t)) and not (_AGG.search(t) and "group by" not in t)
                w_ok = (not w_need) or (e["zero"] and e["pos"])
                p_ok = all(len(v) >= 2 for v in e["p"].values())
                write_live_only = e["write"] and not (e["zero"] or e["pos"]) and not e["p"]
                if w_ok and p_ok and not write_live_only:
                    rung = "RESPONSIVE"
                else:
                    rung = "EXECUTED" if complete else "NOT SEARCHED"
            # live_only: RESPONSIVE, but the stamped-fixture evidence ALONE wouldn't be. The witnesses came from
            # whatever live data held during the run (a now()-relative window over live messages), so the next run
            # can read EXECUTED. The ledger only moves on reproducible evidence (seed #26453: plan_verdict_due flap).
            live_only = False
            if rung == "RESPONSIVE":
                fw = (not w_need) or (e["fx_zero"] and e["fx_pos"])
                fp = set(e["fx_p"]) == set(e["p"]) and all(len(v) >= 2 for v in e["fx_p"].values())
                live_only = not (fw and fp)
            sites[f"{key}\x1f{t}"] = {"rung": rung, "fallback": t == "*", "live_only": live_only,
                                     "write": fn["sites"].get(t, {}).get("write", False) if t != "*" else None}
    counts = collections.Counter(s["rung"] for s in sites.values())
    run_not_searched = []
    if inv["triggers_absent"]:
        run_not_searched.append("triggers/ absent (gitignored estate not present): the class's home was not searched")
    if inv["unparseable"]:
        run_not_searched.append(f"unparseable files: {inv['unparseable']}")
    if shim_errors:
        run_not_searched.append(f"shim internal errors: {shim_errors}")
    return {"counts": dict(counts), "sites": sites, "blind": blind, "direct": direct, "oracle_own": oracle_own,
            "driver_internal": dict(driver_internal),
            "run_not_searched": run_not_searched, "covering": covering, "gates": gates,
            "untraced_children": {k: sorted(v) for k, v in untraced.items()},
            "extractors": {k: sorted(v) for k, v in extractors.items()},
            "extractors_static": inv["extractors"], "exempt": inv["exempt"], "excluded": inv.get("excluded", []), "records": len(recs)}


REMAINDER = ("CEILING: RESPONSIVE = the WHERE and every computed bool responded. It never means CORRECT (that's the "
             "mutant battery). Non-bool predicates aren't witnessed; asyncpg (P) is NOT-EVALUATED; live-public DML "
             "is observed, never exercised; stamps and the ledger are DETECTION-grade against a same-uid actor.")


def print_report(rep):
    c = rep["counts"]
    print(f"sqlguard: {rep['records']} traced statements · sites " +
          ", ".join(f"{k}={v}" for k, v in sorted(c.items())) +
          f" · blind={len(rep['blind'])} · direct={len(rep['direct'])} · oracle-own={rep['oracle_own']}")
    for n in rep["run_not_searched"]:
        print(f"  NOT SEARCHED (run): {n}")
    for script, gs in sorted(rep["untraced_children"].items()):
        print(f"  NOT SEARCHED (untraced child): {script} was launched with a cleared env by {gs}")
    from nucleus.sqlguard.privacy import ignored
    if rep.get("driver_internal"):
        print(f"  driver-internal (no credit; composed of the driver's own source constants): {rep['driver_internal']}"
              f". A repo text equal to a driver constant would also count, so this is not proof only the driver spoke")
    for b in rep["blind"][:10]:
        p = b["frame"][0]
        what = "" if (p.startswith("tier/") or ignored(p)) else f" ran {b['t']!r}"   # P1: no gitignored SQL text
        print(f"  BLIND (reverse agreement): {p}::{b['frame'][1]}{what}")
    print(f"  extractors (static list, until migrated): {len(rep['extractors_static'])}; exempt: {rep['exempt']}; "
          f"excluded roots: {rep.get('excluded', [])}")


def write_report(d, rep):
    with open(os.path.join(d, "report.json"), "w") as f:
        json.dump(rep, f, indent=1, default=sorted)


if __name__ == "__main__":                            # report-only; check.sh runs enforce, which calls judge()
    d = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ASTRYX_SQLGUARD_DIR", "")
    rep = judge(d)
    print_report(rep)
    print("  " + REMAINDER)
    write_report(d, rep)
