"""Mutants for triggers/steward/outbound_stuck.py's observatory thread-pane class (painter 003bea7, steward #57406: p1's
replies on thread 'owner' were told to resend into the doorbell group). The body is gitignored: OUTBOUND_STUCK_STAGED
names a staged copy to probe before it is applied. The oracle is tests/test_outbound_stuck.py."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("OUTBOUND_STUCK_STAGED") or REPO / "triggers" / "steward" / "outbound_stuck.py")
ORACLE = REPO / "tests" / "test_outbound_stuck.py"
ENV = "OUTBOUND_STUCK_SRC"
MUTANTS = {
    "P1 a pane reply takes the bridge's class ('resend un-threaded')":
        ('        elif m.get("pane_served") and f[2] == "pending":', '        elif False:'),
    "P2 the pane carve-out takes dead rows too (a raised failure read as 'he hasn't opened it')":
        ('        elif m.get("pane_served") and f[2] == "pending":', '        elif m.get("pane_served"):'),
    "P3 the pane ignores the bridges' predicate (a t-/wa: row a bridge carries reads as pane-served)":
        ("            f\"AND NOT {OWNER_ROW_BRIDGED_SQL.replace('%', '%%')}\")", "            \"AND TRUE\")"),
    "P4 the pane's WHO is dropped (the owner's own row, which the pane never marks, reads as served)":
        ("PANE_ROW = (\"m.to_org = 'local' AND m.to_agent = 'owner' AND m.from_agent <> 'owner' \"",
         "PANE_ROW = (\"m.to_org = 'local' AND m.to_agent = 'owner' \""),
    "P5 the pane render prescribes a resend of the same text":
        ('f"UNREAD IN AN OBSERVATORY THREAD PANE ({len(pane)}) — NOT a fault: DO NOT restart anything, and DO NOT "\n'
         '            f"resend the same text.',
         'f"UNREAD IN AN OBSERVATORY THREAD PANE ({len(pane)}) — NOT a fault: DO NOT restart anything, and "\n'
         '            f"resend it.'),
    "P6 the projection is computed but never carried into meta":
        ('            "pane_served": bool(r.get("pane_served")),', '            "pane_served": False,'),
    "P7 the pane's pointer remedy loses the doorbell caveat":
        ('f"UN-THREADED {DOORBELL} that names the thread;', 'f"UN-THREADED that names the thread;'),
    "P8 the imported predicate's % is not escaped for psycopg (the main query raises)":
        ("OWNER_ROW_BRIDGED_SQL.replace('%', '%%')", "OWNER_ROW_BRIDGED_SQL"),
}
