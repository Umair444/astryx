#!/usr/bin/env python3
"""sqlguard's asyncpg shim counts a fetchval's rows (goal 4243, a3 #61777). asyncpg's fetchval is "the first row's
column, or None"; the shim answered it as itself and recorded rows=-1, so a fetchval under a WHERE could never show
both sides and every such site was capped at EXECUTED (17 sites). The shim now answers fetchval through the UNWRAPPED
fetchrow and takes the column itself.

  F1 the value a fetchval returns under the shim equals plain asyncpg's, for a hit, a miss and column=1.
  F2 its trace records rows 1 for the hit and 0 for the miss (RED on the old shim: -1 for both).
  F3 one fetchval writes ONE trace record (fetchrow is called unwrapped: nothing is counted twice).
  F4 a hit whose value is NULL records rows=1: counting from the value would read it as a miss, a FALSE climb to
     RESPONSIVE (a site whose only "zero" was a NULL hit), the one direction sqlguard must never err in (a3 #61863).
Residual, named: asyncpg PreparedStatement methods (conn.prepare(...).fetch*) are unwrapped for every method, as
before; the one such site is the observatory's SQL console over user-typed SQL, which the inventory can't key.
Exit 0 pass · 1 fail · 77 no reachable server or asyncpg (nothing verified).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate, unavailable  # noqa: E402
gate("test_sqlguard_fetchval", REPO, deps=("psycopg", "asyncpg"), env=False)
from astryx.security.sqlguard.fixture import fixture_db, FixtureUnavailable  # noqa: E402

SHIM = str(REPO / "src" / "astryx" / "security" / "sqlguard" / "shim")   # the shim needs its package beside it: never a copy
CHILD = r'''
import asyncio, json, sys, asyncpg
async def main(dsn):
    c = await asyncpg.connect(dsn)
    await c.execute("CREATE TABLE fv_probe (i int, s text)")
    await c.execute("INSERT INTO fv_probe VALUES (1, 'one')")
    hit = await c.fetchval("SELECT i FROM fv_probe WHERE i = $1", 1)
    miss = await c.fetchval("SELECT i FROM fv_probe WHERE i = $1", 2)
    col = await c.fetchval("SELECT i, s FROM fv_probe WHERE i = $1", 1, column=1)
    nullhit = await c.fetchval("SELECT NULL::int AS v FROM fv_probe WHERE i = $1", 1)   # a HIT whose value is NULL
    await c.close()
    print(json.dumps({"hit": hit, "miss": miss, "col": col, "nullhit": nullhit}))
asyncio.run(main(sys.argv[1]))
'''
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  ({detail})"))
    if not ok:
        fails.append(name)


def run(dsn, traced: bool, tdir: str):
    env = {**os.environ}
    env.pop("ASTRYX_SQLGUARD_DIR", None)
    if traced:
        env["PYTHONPATH"] = SHIM + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["ASTRYX_SQLGUARD_DIR"] = tdir
        env["ASTRYX_SQLGUARD_GATE"] = "test_sqlguard_fetchval"
    p = subprocess.run([sys.executable, "-c", CHILD, dsn], env=env, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        return None, p.stderr.strip().splitlines()[-1:]
    return json.loads(p.stdout.strip().splitlines()[-1]), None


try:
    with tempfile.TemporaryDirectory(prefix="sqlguard-fv-") as tmp:
        with fixture_db() as fx:
            plain, err = run(fx["url"], False, tmp)
        with fixture_db() as fx:
            shimmed, err2 = run(fx["url"], True, tmp)
        check("F1 the shimmed fetchval returns plain asyncpg's values (hit, miss, column=1)",
              plain is not None and shimmed == plain == {"hit": 1, "miss": None, "col": "one", "nullhit": None},
              f"plain={plain or err} shimmed={shimmed or err2}")
        recs = []
        for f in Path(tmp).glob("trace-*.jsonl"):
            recs += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
        fv = [r for r in recs if "from fv_probe where" in r.get("t", "")]
        rows = sorted(r.get("rows") for r in fv if r.get("t", "").startswith("select i from"))
        check("F2 the trace counts a fetchval's rows: 1 for the hit, 0 for the miss", rows == [0, 1], str(rows))
        nulls = [r.get("rows") for r in fv if r.get("t", "").startswith("select null")]
        check("F4 a hit whose VALUE is NULL records rows=1, never 0 (rows come from the ROW, not the value: a3 #61863)",
              nulls == [1], str(nulls))
        check("F3 one record per fetchval (4 calls, 4 records: the unwrapped fetchrow is never counted twice)",
              len(fv) == 4, str([(r.get("t", "")[:40], r.get("rows")) for r in fv]))
except FixtureUnavailable as e:
    unavailable("test_sqlguard_fetchval", REPO, e, failed=fails)

print(f"\n{'FAIL' if fails else 'PASS'}: sqlguard fetchval ({len(fails)} failing)")
sys.exit(1 if fails else 0)
