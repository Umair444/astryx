#!/usr/bin/env python3
"""Oracle: who the owner's message goes to by default on an existing conversation (iteration 11 fix).
An agent is a recipient only when it exchanged a message WITH THE OWNER on the thread (owner→agent or agent→owner).
An agent→agent row on an owner thread (seed's correction to finance on cv:0b7661abb9, a handoff) stays in the history
but never makes its sender a recipient; otherwise the composer read "Message Finance, Seed" and the owner's next reply
silently copied seed in. Two places derive the set, both covered here:
  - workspace.py build_rows → /api/ws/threads `agents` (the list's faces, "Finance +1"): `partners`, from SQL
  - web/src/chat/model.ts participants() → the composer's recipients (tests/web/ws_recipients_cases.ts, esbuild+node)
WS_SRC names another workspace.py (a mutant) to run the python arms against."""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
SUBJECT = Path(os.environ.get("WS_SRC") or REPO / "observatory" / "api" / "workspace.py")
sys.path.insert(0, str(REPO / "src"))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_ws_recipients", REPO, deps=('fastapi', 'asyncpg', 'psycopg'), env=False)   # a clean clone (no venv): 77, not an import crash
spec = importlib.util.spec_from_file_location("ws_subject_recipients", SUBJECT)
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)
fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


ROSTER = {"seed", "finance", "db", "lending"}


def agg(thread, parties, partners=..., last_ts="2099-12-31T10:00:00"):
    a = {"thread": thread, "parties": parties, "last_ts": last_ts, "first_owner": "hello", "last_body": "reply",
         "last_from": "finance", "count": 3}
    if partners is not ...:
        a["partners"] = partners
    return a


def main():
    print("list agents = the owner's partners")
    rows = W.build_rows([agg("cv:0b7661abb9", ["owner", "finance", "seed", "finance", "owner"], ["finance", "finance", "finance"])], {}, [], ROSTER)
    arm("seed→finance correction: the row's agents are [finance] only", rows and rows[0]["agents"] == ["finance"], rows)
    rows = W.build_rows([agg("chat:1-a", ["owner", "db", "seed"], ["db", "seed", "db"])], {}, [], ROSTER)
    arm("two agents the owner talked to, first-seen order", rows[0]["agents"] == ["db", "seed"], rows)
    rows = W.build_rows([agg("obs:seed", ["owner", "db", "seed"], ["seed"])], {}, [], ROSTER)
    arm("a desk names its agent; a handoff into it (db) does not join", rows[0]["agents"] == ["seed"], rows)
    rows = W.build_rows([agg("cv:aaa", ["owner", "lending", "canvas-1"], None)], {}, [], ROSTER)
    arm("no partners at all (NULL from SQL) → no crash, no agents", rows[0]["agents"] == [], rows)
    rows = W.build_rows([agg("chat:old", ["owner", "db", "seed"])], {}, [], ROSTER)
    arm("an aggregate without `partners` (an older caller) keeps the parties rule", rows[0]["agents"] == ["db", "seed"], rows)
    rows = W.build_rows([agg("cv:x", ["seed", "finance"], [])], {}, [], ROSTER)
    arm("listing still needs the owner as a party", rows == [], rows)

    print("the SQL computes partners from owner rows only")
    sql = re.sub(r"\s+", " ", W.THREADS_SQL)
    arm("THREADS_SQL selects partners", " AS partners" in sql, sql)
    # cog-who: "the owner" is the VIEWER ($1, 'owner' for him) or, in the everyone view ($2), any web human
    hf = "(from_agent = $1 OR ($2 AND (from_agent = 'owner' OR from_agent LIKE 'cv-%')))"
    ht = "(to_agent = $1 OR ($2 AND (to_agent = 'owner' OR to_agent LIKE 'cv-%')))"
    arm("partners: owner→X gives X, X→owner gives X",
        f"CASE WHEN {hf} THEN to_agent ELSE from_agent END" in sql, sql)
    arm("partners filtered to rows with the owner on one end",
        f"FILTER (WHERE {hf} OR {ht}) AS partners" in sql, sql)

    print("the composer's recipients (model.ts participants, esbuild + node)")
    esb = REPO / "observatory/web/node_modules/.bin/esbuild"
    if not esb.exists():
        print("  SKIP: esbuild missing (npm ci in observatory/web)")
        return
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "cases.cjs"
        subprocess.run([str(esb), str(REPO / "tests/web/ws_recipients_cases.ts"), "--bundle", "--platform=node",
                        f"--outfile={out}", "--log-level=error"], check=True, cwd=REPO / "observatory/web")
        r = subprocess.run(["node", str(out)], capture_output=True, text=True)
        print(r.stdout, end="")
        print(r.stderr, end="", file=sys.stderr)
        arm("frontend cases pass", r.returncode == 0, r.returncode)


if __name__ == "__main__":
    print(f"test_ws_recipients: {SUBJECT}")
    main()
    print(f"\n{'FAIL' if fails else 'PASS'}: {fails} failing arm(s)")
    sys.exit(1 if fails else 0)
