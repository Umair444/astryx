#!/usr/bin/env python3
"""Oracle for triggers/steward/econ_provenance.py — v2 econ rows must come from reviewed code.

    venv/bin/python tests/test_econ_provenance.py   (ECON_PROV_SRC=<path> overrides the subject)

The subject is gitignored (triggers/), so it is path-loaded; absent → SKIP 77. Arms:
  1. classify (pure, injected ancestor fn): clean row → nothing; missing built_from → 'missing';
     sha None → 'unknown'; sha not on main → 'foreign'; dirty True → 'dirty'; dirty None →
     'dirty' (unknown is never clean); a JSON-string built_from parses; one ancestor call per sha.
  2. _is_ancestor (real git): main's HEAD → True; a sha no repo has → False; None → False.
  3. ENTRYPOINT through pulse_run's OWN Ctx against a sqlguard fixture DB (the real schema, never
     production): a v2.0 row without built_from is NOT flagged (pre-stamp rows are out of scope);
     a clean v2.1 row is not; a foreign and a missing v2.1 row are, each with its remedy; the same
     set on the next run is silent (dedup); lost state re-alarms; an all-clean table is silent.
Exit 0 pass · 1 fail · 77 could-not-run.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BODY = Path(os.environ.get("ECON_PROV_SRC") or REPO / "triggers" / "steward" / "econ_provenance.py")
if not BODY.exists():
    print("SKIP: econ_provenance body absent (gitignored triggers/) — nothing asserted.")
    sys.exit(77)
sys.path.insert(0, str(REPO))
try:
    _s = importlib.util.spec_from_file_location("econ_prov_under_test", BODY)
    m = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(m)
    m.REPO = REPO          # a STAGED body lives outside the repo; the live one resolves the same root
except Exception as e:  # noqa: BLE001
    print(f"SKIP: econ_provenance not importable ({type(e).__name__}: {e}).")
    sys.exit(77)

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


GOOD, BAD = "a" * 40, "b" * 40


def row(day, bf, version="v2.1"):
    return {"day": day, "computed_at": f"{day} 19:10:00", "version": version, "built_from": bf}


print("1. classify:")
calls = []


def anc(sha):
    calls.append(sha)
    return sha == GOOD


rows = [row("d1", {"sha": GOOD, "dirty": False}), row("d2", None), row("d3", {"sha": None, "dirty": None}),
        row("d4", {"sha": BAD, "dirty": False}), row("d5", {"sha": GOOD, "dirty": True}),
        row("d6", {"sha": GOOD, "dirty": None}), row("d7", json.dumps({"sha": GOOD, "dirty": False})),
        row("d8", {"sha": BAD, "dirty": False})]
got = {d: f for d, _c, f, _s in m.classify(rows, anc)}
check("clean row → not flagged", "d1" not in got, str(got))
check("missing built_from → 'missing'", got.get("d2") == "missing", str(got))
check("sha None → 'unknown'", got.get("d3") == "unknown", str(got))
check("sha not an ancestor of main → 'foreign'", got.get("d4") == "foreign", str(got))
check("dirty=True → 'dirty'", got.get("d5") == "dirty", str(got))
check("dirty=None → 'dirty' (unknown is never clean)", got.get("d6") == "dirty", str(got))
check("a JSON-string built_from parses (clean → not flagged)", "d7" not in got, str(got))
check("one ancestor lookup per distinct sha", sorted(calls) == sorted([GOOD, BAD]), str(calls))

print("\n2. git (a hermetic temp repo: a main commit, a side-branch commit, a missing object):")
import tempfile  # noqa: E402
_tmp = tempfile.TemporaryDirectory()
T = Path(_tmp.name) / "r"
G = ["git", "-C", str(T), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
subprocess.run(["git", "init", "-q", "-b", "main", str(T)], check=True)
subprocess.run(G + ["commit", "-q", "--allow-empty", "-m", "on main"], check=True)
on_main = subprocess.run(G + ["rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
subprocess.run(G + ["checkout", "-q", "-b", "side"], check=True)
subprocess.run(G + ["commit", "-q", "--allow-empty", "-m", "off main"], check=True)
off_main = subprocess.run(G + ["rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
check("a commit on main → ancestor", m._is_ancestor(on_main, T))
check("a REAL commit off main (side branch) → not an ancestor", not m._is_ancestor(off_main, T))
check("an object the repo lacks → not an ancestor", not m._is_ancestor("f" * 40, T))
check("None → not an ancestor", not m._is_ancestor(None, T))
check("git_blind: a healthy repo with main → None", m.git_blind(T) is None)
check("git_blind: a directory that is not a repo → a reason (the checker is blind)",
      bool(m.git_blind(Path(_tmp.name))))
head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "main"], capture_output=True, text=True).stdout.strip()

print("\n3. entrypoint (pulse_run.Ctx on a sqlguard fixture):")
try:
    _p = importlib.util.spec_from_file_location("pulse_run_prov", REPO / "nucleus" / "pulse_run.py")
    pr = importlib.util.module_from_spec(_p)
    _p.loader.exec_module(pr)
    import psycopg
    from nucleus.sqlguard.fixture import fixture_db
    _fx = fixture_db()
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"  SKIP  entrypoint arms — fixture/runner unavailable ({type(e).__name__}: {e})")
    fx = None

if fx is not None:
    conn = psycopg.connect(fx["dsn"], autocommit=True)
    try:
        def put(day, version, bf):
            v2 = {"version": version}
            metrics = {"v2": v2} | ({"built_from": bf} if bf is not None else {})
            conn.execute("INSERT INTO econ (day, metrics) VALUES (%s, %s::jsonb)", (day, json.dumps(metrics)))

        class TempCtx(pr.Ctx):
            def __init__(self, state, connection):
                super().__init__(state)
                self._conn = connection

        check("an EMPTY econ table → silent (the entrypoint's WHERE also sees 0 rows)",
              m.econ_provenance(TempCtx({}, conn)) is None)
        put("2026-01-01", "v2.0", None)                                   # pre-stamp: out of scope
        put("2026-01-02", "v2.1", {"sha": head, "dirty": False})          # clean
        put("2026-01-03", "v2.1", {"sha": "e" * 40, "dirty": False})      # foreign
        put("2026-01-04", "v2.1", None)                                   # missing

        st = {}
        out = m.econ_provenance(TempCtx(st, conn))
        check("the entrypoint's SQL executes and it reports", isinstance(out, str), repr(out))
        out = out or ""
        check("foreign v2.1 row flagged, with its remedy",
              "2026-01-03" in out and "foreign" in out and "find who ran rollup" in out, out)
        check("missing v2.1 row flagged", "2026-01-04" in out and "missing" in out, out)
        check("the clean row is not flagged", "2026-01-02" not in out, out)
        check("the v2.0 pre-stamp row is out of scope", "2026-01-01" not in out, out)
        check("same set next run → silent (dedup)", m.econ_provenance(TempCtx(st, conn)) is None)
        check("lost state → re-alarms (loud side)", isinstance(m.econ_provenance(TempCtx({}, conn)), str))
        # a BLIND checker (its repo is not a git repo) → ONE unverifiable line, zero per-row verdicts
        real = m.REPO
        m.REPO = Path(_tmp.name)
        blind = m.econ_provenance(TempCtx({}, conn)) or ""
        m.REPO = real
        check("blind checker → exactly one 'UNVERIFIABLE' line and NO 'foreign' verdict",
              blind.count("UNVERIFIABLE") == 1 and "foreign" not in blind and "2026-01-0" not in blind, blind)
        conn.execute("DELETE FROM econ WHERE day IN ('2026-01-03','2026-01-04')")
        st2 = {"nag": 1}
        check("an all-clean table is silent and clears the nag",
              m.econ_provenance(TempCtx(st2, conn)) is None and "nag" not in st2, str(st2))
    finally:
        conn.close()
        _fx.__exit__(None, None, None)

print()
if fails:
    print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    sys.exit(1)
if fx is None:
    print("SKIP (77): pure + git arms passed; the entrypoint arms need the fixture DB")
    sys.exit(77)
print("econ_provenance: missing/unknown/foreign/dirty rows flagged with their own remedies; all rows each run")
sys.exit(0)
