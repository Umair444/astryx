#!/usr/bin/env python3
"""Known-answer oracle for devtools/tool_census.py (goal 11324 S1's Done instrument), on a stamped fixture database.

One fixture, one discriminator per row:
  r1 script:nucleus/check.sh, v1, caller fx-a; its Write recorded at the NEW path (devtools/check.sh): unknown to the
     pre-S1 toolreg (no canonical), resolved by this tree's → MOVED.
  r2 script:devtools/review_range.sh, caller fx-b; its only Write is legacy content at a removed checkout's
     nucleus/ path → RESIDUAL, cause "legacy content at a path outside the live tree".
  r3 mcp:memory/fx_recall, caller fx-b, content mcp__memory__fx_recall: no Write of its server → RESIDUAL, cause
     "no Write or Edit"; and the one row B1 counts.
  r4 mcp:astryx/fx_send and r5 mcp:tools/fx_find, caller fx-a: core → outside the domain ((a) in: 5, out: 3). tools
     is IN registry.json, so B1 must subtract CORE_SERVERS to drop it.
  r6 script:nucleus/check.sh, caller fx-c, stamped now on a turn that ENDED 3 days ago: in A's window, outside
     B's (the by-turn bucket reads it), and a second MOVED row.
  r7 mcp:astryx/fx_ping, caller fx-c, on a turn with no goal and no input: demand-UNqualified (core, so the
     domain doesn't move; it gives the dq column its second value).
  r8 mcp:tools/run, the door's catch-all for an id it couldn't resolve: core, counted on its own line (a3 #58277).
  transcript: Bash `devtools/check.sh` (named AND at an execution position), Bash `cat devtools/check.sh` (named
     only), mcp__memory__fx_recall → B2 named 2, B2x 1, of 3 tool calls.
Expected (d): unresolved before 4 = moved 2 + residual 2 · regressions 0.
A second run with --until before every row reads the same queries back EMPTY (rc 0): sqlguard grades a WHERE
RESPONSIVE only when its row count took both 0 and >=1.
Exit 0 pass · 1 fail · 77 no DB, or the pre-S1 ref is absent from this clone.
"""
import contextlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
PRE_S1 = "7c30828b"   # main before goal 11324 S1: toolreg with no canonical() and no MOVED fold on Write events

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def main():
    if subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", PRE_S1 + "^{commit}"], capture_output=True).returncode:
        print(f"SKIP (77): {PRE_S1} isn't in this clone")
        return 77
    try:
        import psycopg
        from astryx.econ.econ import _dsn
        live = psycopg.connect(_dsn(), autocommit=True, connect_timeout=5)
    except Exception as e:  # noqa: BLE001
        print(f"SKIP (77): no DB ({type(e).__name__})")
        return 77
    from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db
    stack = contextlib.ExitStack()
    try:
        try:
            fx = stack.enter_context(fixture_db())
        except FixtureUnavailable as e:
            check("the census has a fixture database", False, str(e))
            return 1
        c = stack.enter_context(psycopg.connect(fx["dsn"], autocommit=True, connect_timeout=5))
        blocks = [{"type": "tool_use", "name": "Bash", "input": {"command": "devtools/check.sh"}},
                  {"type": "tool_use", "name": "Bash", "input": {"command": "cat devtools/check.sh"}},
                  {"type": "tool_use", "name": "mcp__memory__fx_recall", "input": {}}]
        payload = {"messages": [{"type": "assistant", "message": {"role": "assistant", "content": blocks}}]}
        tid = c.execute("INSERT INTO turns (agent, goal_id, ended_at, raw_payload) VALUES ('fx-a', 7, now(), %s::jsonb) "
                        "RETURNING id", (json.dumps(payload),)).fetchone()[0]
        late = c.execute("INSERT INTO turns (agent, goal_id, ended_at) VALUES ('fx-c', 7, now() - interval '3 days') "
                         "RETURNING id").fetchone()[0]
        idle = c.execute("INSERT INTO turns (agent, ended_at) VALUES ('fx-c', now()) RETURNING id").fetchone()[0]
        c.execute("INSERT INTO steps (agent, kind, content, meta) VALUES "
                  "('fx-author','tool','Write: fixture',%s::jsonb), ('fx-author','tool',%s,NULL)",
                  (json.dumps({"edits": "script:devtools/check.sh", "v": 1}),
                   "Write: /tmp/fx-gone-checkout/t/nucleus/review_range.sh"))
        for caller, content, rid, t in (("fx-a", "Bash: run", "script:nucleus/check.sh", tid),
                                        ("fx-b", "Bash: run", "script:devtools/review_range.sh", tid),
                                        ("fx-b", "mcp__memory__fx_recall: ", "mcp:memory/fx_recall", tid),
                                        ("fx-a", "mcp__astryx__fx_send: ", "mcp:astryx/fx_send", tid),
                                        ("fx-a", "mcp__tools__fx_find: ", "mcp:tools/fx_find", tid),
                                        ("fx-c", "Bash: run", "script:nucleus/check.sh", late),
                                        ("fx-c", "mcp__astryx__fx_ping: ", "mcp:astryx/fx_ping", idle),
                                        ("fx-c", "mcp__tools__run: ", "mcp:tools/run", tid)):
            c.execute("INSERT INTO steps (agent, kind, content, meta, turn_id) VALUES (%s,'tool',%s,%s::jsonb,%s)",
                      (caller, content, json.dumps({"registry_id": rid, "v": 1}), t))
        # CENSUS_SRC is mutation_probe's seam. PYTHONPATH keeps what it was given FIRST (the sqlguard shim, when
        # traced) and adds this tree's src/, so a mutant copy outside the repo still imports astryx.
        pp = os.pathsep.join(x for x in (os.environ.get("PYTHONPATH"), str(REPO / "src")) if x)

        def census(*extra):
            return subprocess.run([sys.executable, "-B",
                                   os.environ.get("CENSUS_SRC") or str(REPO / "devtools" / "tool_census.py"),
                                   "--days", "1", "--before", PRE_S1, "--dsn", fx["dsn"], *extra],
                                  capture_output=True, text=True, timeout=300,
                                  env={**os.environ, "ASTRYX_LIVE_REPO": str(REPO), "PYTHONPATH": pp})
        r = census()
        out = r.stdout
        print("\n".join("    | " + ln for ln in out.splitlines()))
        check("the census runs against the real DDL (rc 0)", r.returncode == 0, r.stderr[-800:])
        if r.returncode:
            return 1   # every arm below would fail for the crash, not for what it names

        def has(pat, name):
            check(name, re.search(pat, out, re.M) is not None, f"no /{pat}/")
        has(r"core in : 8 calls", "(a) core in: all 8 calls")
        has(r"core out: 4 calls", "(a) core out: the four core calls leave the domain")
        has(r"the door's catch-all mcp:tools/run .*: 1 call\(s\)", "(a) the door's catch-all is counted on its own line")
        has(r"before: 4 calls · coverage 0\.00%", "(b) before: no author resolves (no canonical, no fold)")
        has(r"after : 4 calls · coverage 50\.00%", "(b) after: both moved rows' author resolves (2 of 4)")
        has(r"B1 steps content naming a registry\.json server's tool: 1 \(A's mcp: 1;",
            "(c) B1 counts the registry server's step, not the door's (tools is IN registry.json, and core)")
        has(r"B2 transcript Bash calls naming a tracked script: 2 of 3 tool calls", "(c) B2 counts naming (cat too)")
        has(r"B2x .*: 1 \(A's script: 3;", "(c) B2x counts only the execution position")
        has(r"A rows stamped in the window whose turn ended outside it: 1\)",
            "(c) the by-turn bucket finds the row whose turn ended outside B's window")
        has(r"unresolved before 4 = moved 2 \(resolved by S1's folds\) \+ residual 2 · resolved before and "
            r"unresolved after: 0", "(d) unresolved = moved + residual, no regression")
        has(r"^\s+1\s+its Writes are recorded only as legacy content at a path outside the live tree",
            "(d) the legacy-path cause")
        has(r"^\s+1\s+no Write or Edit of it in the ledger", "(d) the never-written cause")
        e = census("--until", "2000-01-01T00:00:00+00:00")
        check("an EMPTY window runs too (rc 0), every count 0", e.returncode == 0 and "core out: 0 calls" in e.stdout
              and "unresolved before 0 = moved 0" in e.stdout, (e.stdout + e.stderr)[-800:])
        check("PRIVACY: no tool input reaches the output", "cat devtools/check.sh" not in out
              and "fx-gone-checkout" not in out, "")
        pub = live.execute("SELECT count(*) FROM steps WHERE agent IN ('fx-a','fx-b','fx-author')").fetchone()[0]
        check("CONTAINMENT: no fixture row leaked to the live database", pub == 0, str(pub))
        return 1 if fails else 0
    finally:
        stack.close()
        live.close()


if __name__ == "__main__":
    rc = main()
    print()
    if rc == 1:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    elif rc == 0:
        print("tool census: the known-answer fixture reads back as (a) (b) (c) (d) say")
    sys.exit(rc)
