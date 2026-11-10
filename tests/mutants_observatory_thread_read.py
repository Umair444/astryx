"""Mutants for observatory/api/main.py's /api/thread/read: opening a thread's pane marks the agent→owner replies on
it read (seed #57412, steward #57407). The oracle is tests/test_observatory_thread_read.py, which loads OBS_MAIN_SRC
in place of the real main.py.

Not listed, on purpose: dropping the route's own x-obs-key check. Probed 10-16, it survives this oracle (NOT PROBED
BY THIS SET): /api/thread/read is not in PUBLIC_PATHS, so the central default-deny gate answers a keyless call 403
before the route runs. The route's check is a second guard, as on the desks; the GATE arms pin the 403 either way."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "observatory" / "api" / "main.py"
ORACLE = REPO / "tests" / "test_observatory_thread_read.py"
ENV = "OBS_MAIN_SRC"
MUTANTS = {
    "R2 a blank thread gets through (only an empty one is 400)": ("if not r.thread.strip():", "if not r.thread:"),
    "R3 drops to_agent='owner' (a p1→steward row is marked read)":
        ("AND id <= $2 AND to_agent='owner' AND to_org='local'", "AND id <= $2 AND to_org='local'"),
    "R4 drops to_org='local' (an owner@peer row is marked though it never left)":
        ("AND id <= $2 AND to_agent='owner' AND to_org='local'", "AND id <= $2 AND to_agent='owner'"),
    "R5 drops from_agent<>'owner' (the owner's own row is marked)":
        ("AND to_org='local' AND from_agent<>'owner' ", "AND to_org='local' "),
    "R6 drops upto (a reply the pane never rendered is marked)":
        ("WHERE thread=$1 AND id <= $2 AND to_agent='owner'", "WHERE thread=$1 AND $2::bigint > 0 AND to_agent='owner'"),
    "R7 scoped by sender, not thread (every reply to the owner is marked)":
        ("WHERE thread=$1 AND id <= $2 AND to_agent='owner'", "WHERE $1::text IS NOT NULL AND id <= $2 AND to_agent='owner'"),
    "R8 drops status='pending' (a bridge's delivery is re-handled as observatory:thread)":
        ("f\"AND status='pending' AND NOT {OWNER_ROW_BRIDGED_SQL}", "f\"AND NOT {OWNER_ROW_BRIDGED_SQL}"),
    "R10 drops the bridged exclusion (a t-/wa:/tg:/dc:/cv:/tier/ear row is marked before its bridge sends it)":
        (" AND NOT {OWNER_ROW_BRIDGED_SQL} RETURNING id", " RETURNING id"),
    "R9 marks under the late desk's handle":
        ("'handle', 'observatory:thread') \"", "'handle', 'observatory:late') \""),
}
