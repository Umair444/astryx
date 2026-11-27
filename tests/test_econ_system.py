#!/usr/bin/env python3
"""Oracle: the Economy tab's one read (src/astryx/econ/system.py read()) runs against this tree's schema.

    venv/bin/python tests/test_econ_system.py

A fixture database (this tree's schema.sql), fixture rows only. Medic 12299: a renamed column must turn a test red,
not blank the owner's page.
  S1 an EMPTY org: read() returns every key the page draws, no exception, and an absent number is None, never invented
  S2 a little life (turns, steps, messages): flows, thermo and commons count it, and every equation carries its
Exit 0 · 1 · 77 (no database)."""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_econ_system", REPO, deps=("psycopg",), env=False)
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402
from astryx.econ import system as S  # noqa: E402
from astryx.mind import mind as M  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {str(detail)[:400]}"))
    if not ok:
        fails.append(name)


KEYS = {"energy", "equations", "objectives", "flows", "projection", "market", "commons", "thermo", "game", "mind"}
M._org_agents = lambda c: {"a", "b"}
os.environ.pop("ASTRYX_AGENT", None)


def main():
    import psycopg
    from psycopg.rows import dict_row
    with fixture_db() as d, psycopg.connect(d["url"], autocommit=True, row_factory=dict_row) as c:
        S.market = lambda c: {"gdp": {"value": None, "status": "NOT_EVALUATED: fixture", "coverage": 0}, "tools": [], "mirror": {}, "trade": [], "days": 7}
        print("S1 an empty org")
        o = S.read(c)
        arm("S1 every key the page draws is there", KEYS <= set(o), sorted(o))
        arm("S1 it is JSON (the route returns it as is)", bool(json.dumps(o, default=str)))
        arm("S1 no reading of the limits: energy unknown, tiredness absent, never 0", o["energy"].get("known") is False and o["equations"][0]["value"] is None, o["energy"])
        arm("S1 heat and G absent with no energy spent", o["thermo"]["heat_share"] is None and o["thermo"]["g"] is None, o["thermo"])
        print("S2 a little life")
        c.execute("""INSERT INTO turns (agent, started_at, ended_at, tokens_in, tokens_out) VALUES
                     ('a', now() - interval '2 hours', now() - interval '110 minutes', 0, 1000),
                     ('b', now() - interval '1 hour', now() - interval '50 minutes', 0, 3000)""")
        c.execute("INSERT INTO steps (agent, kind, content, ts) VALUES ('a', 'tool', 'Bash: x', now() - interval '2 hours'), ('a', 'tool', 'Read: y', now() - interval '2 hours')")
        o = S.read(c)
        tot = o["flows"]["total"]
        arm("S2 flows count the turns' energy by who started them (no opening message: the terminal)", tot["terminal"]["tokens"] == 4000 and tot["terminal"]["turns"] == 2, tot)
        arm("S2 thermo: flux, and heat (both turns left no trace)", o["thermo"]["flux"] == 4000 and o["thermo"]["heat_share"] == 1.0, o["thermo"])
        arm("S2 thermo: one bit of entropy over two equally used tools", any(x["entropy_bits"] == 1.0 for x in o["thermo"]["series"]), o["thermo"]["series"])
        arm("S2 commons: each agent's share of the energy", {r["agent"]: r["share"] for r in o["commons"]} == {"a": 0.25, "b": 0.75}, o["commons"])
        arm("S2 every equation has a name, a formula and a reading", all(e["name"] and e["formula"] and e["reads"] for e in o["equations"]))


try:
    main()
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    fails.append(f"crashed: {type(e).__name__}")
print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: the Economy tab's one read runs on this tree's schema")
sys.exit(1 if fails else 0)
