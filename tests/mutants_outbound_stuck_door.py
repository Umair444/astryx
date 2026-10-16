"""Mutants for triggers/steward/outbound_stuck.py's door class (plan-9139 S1c-2). The body is gitignored:
OUTBOUND_STUCK_STAGED names a staged copy to probe before it is applied. The oracle is tests/test_outbound_stuck.py."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("OUTBOUND_STUCK_STAGED") or REPO / "triggers" / "steward" / "outbound_stuck.py")
ORACLE = REPO / "tests" / "test_outbound_stuck.py"
ENV = "OUTBOUND_STUCK_SRC"
MUTANTS = {
    "O1 a refused row takes its mechanism's class (bridge: 'resend un-threaded')":
        ("        if f[2] == \"refused\":\n", "        if False:\n"),
    "O2 a refused row waits out the first band (grace like a pending row)":
        ("        if r[\"status\"] in (\"dead\", \"refused\"):", "        if r[\"status\"] == \"dead\":"),
    "O3 the door's class is computed and never rendered":
        ("    if refused:\n        parts.append(", "    if False:\n        parts.append("),
}
