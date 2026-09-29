#!/usr/bin/env python3
"""The sqlguard judge: joins the static inventory with the runtime trace and grades every site (goal 4243).

    venv/bin/python -m nucleus.sqlguard.judge <trace_dir>        # B0: REPORT-ONLY (exit 0; status printed)

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

from nucleus.sqlguard import inventory
from nucleus.sqlguard.normalize import is_site, is_write

REPO = inventory.REPO
_WHERE = re.compile(r"\b(where|having)\b")
_CREATE = re.compile(r"^\s*create\s+(?:temp\s+|temporary\s+|unlogged\s+)?table\b")
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


def judge(trace_dir, inv=None, covering=None):
    inv = inv or inventory.build()
    fns = inv["functions"]
    live = _live_db()
    untraced = {}
    recs, shim_errors = load_traces(trace_dir, untraced)
    gates = load_gates(trace_dir)
    ev = collections.defaultdict(lambda: {"ok": 0, "credited": 0, "fixture_ddl": 0, "zero": False, "pos": False,
                                          "p": {}, "gates": set(), "fallback": False, "write": False})
    blind, direct, oracle_own = [], [], 0
    extractors = {}                                  # F-b: test file -> gates, derived from the trace
    for r in recs:
        if _CREATE.match(r["t"]) and r.get("ok"):
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

    covering = covering if covering is not None else {f"{k}\x1f{t}": sorted(e["gates"]) for (k, t), e in ev.items()}
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
            sites[f"{key}\x1f{t}"] = {"rung": rung, "fallback": t == "*",
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
            "run_not_searched": run_not_searched, "covering": covering, "gates": gates,
            "untraced_children": {k: sorted(v) for k, v in untraced.items()},
            "extractors": {k: sorted(v) for k, v in extractors.items()},
            "extractors_static": inv["extractors"], "exempt": inv["exempt"], "records": len(recs)}


REMAINDER = ("CEILING: RESPONSIVE = the WHERE and every computed bool responded. It never means CORRECT (that's the "
             "mutant battery). Non-bool predicates aren't witnessed; asyncpg (P) is NOT-EVALUATED; live-public DML "
             "is observed, never exercised; stamps and the ledger are DETECTION-grade against a same-uid actor.")


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ASTRYX_SQLGUARD_DIR", "")
    rep = judge(d)
    c = rep["counts"]
    print(f"sqlguard (B0, report-only): {rep['records']} traced statements · sites " +
          ", ".join(f"{k}={v}" for k, v in sorted(c.items())) +
          f" · blind={len(rep['blind'])} · direct={len(rep['direct'])} · oracle-own={rep['oracle_own']}")
    for n in rep["run_not_searched"]:
        print(f"  NOT SEARCHED (run): {n}")
    for script, gs in sorted(rep["untraced_children"].items()):
        print(f"  NOT SEARCHED (untraced child): {script} was launched with a cleared env by {gs}")
    for b in rep["blind"][:10]:
        print(f"  BLIND (reverse agreement): {b['frame']} ran {b['t']!r}")
    print(f"  extractors (static list, until migrated): {len(rep['extractors_static'])}; exempt: {rep['exempt']}")
    print("  " + REMAINDER)
    with open(os.path.join(d, "report.json"), "w") as f:
        json.dump(rep, f, indent=1, default=sorted)
