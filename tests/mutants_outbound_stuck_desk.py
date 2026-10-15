"""Mutants for triggers/steward/outbound_stuck.py's observatory-desk class and the doorbell caveat (memory #54646,
#55679). The body is gitignored: OUTBOUND_STUCK_STAGED names a staged copy to probe before it is applied. The oracle is
tests/test_outbound_stuck.py."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("OUTBOUND_STUCK_STAGED") or REPO / "triggers" / "steward" / "outbound_stuck.py")
ORACLE = REPO / "tests" / "test_outbound_stuck.py"
ENV = "OUTBOUND_STUCK_SRC"
MUTANTS = {
    "D1 a desk reply takes the bridge's class ('pgrep the bridge, resend un-threaded')":
        ("        elif m.get(\"desk_served\") and f[2] == \"pending\":\n", "        elif False:\n"),
    "D2 the desk carve-out is not pending-only (a dead desk row hides as unserved)":
        ("        elif m.get(\"desk_served\") and f[2] == \"pending\":\n", "        elif m.get(\"desk_served\"):\n"),
    "D3 the desk's class is computed and never rendered":
        ("    if desk:\n        parts.append(", "    if False:\n        parts.append("),
    "D4 the SQL drops a prefix the observatory serves (obs:library-)":
        ("\"OR m.thread LIKE 'obs:person-%%' OR m.thread LIKE 'obs:library-%%')\")",
         "\"OR m.thread LIKE 'obs:person-%%')\")"),
    "D5 the SQL widens to every obs: thread (a near-miss no desk serves)":
        ("AND (m.thread LIKE 'obs:estate%%' \"", "AND (m.thread LIKE 'obs:%%' \""),
    "D6 the projection never reaches the bucket":
        ("            \"desk_served\": bool(r.get(\"desk_served\")),\n", ""),
    "D7 the doorbell caveat says nothing about content":
        ("not an owner-only surface: only content that group may \"\n            \"read; never People detail or "
         "owner-private content, which waits for its desk or an owner-private route)",
         "\"\n            \")"),
    "D8 the bridge's remedy loses the caveat":
        ("resend UN-THREADED {DOORBELL} or to a surface", "resend UN-THREADED (the owner doorbell) or to a surface"),
    "D9 the desk's WHO is dropped (a seed row reads 'was served')":
        ("({DESK_ROW} AND m.from_agent = 'memory') AS desk_served", "({DESK_ROW}) AS desk_served"),
    "D10 the uncarried class is computed and never rendered":
        ("    if desk_uncarried:\n        parts.append(", "    if False:\n        parts.append("),
    "D11 the person desk takes the doorbell remedy":
        ("            (desk_person if m.get(\"desk_person\") else desk).append(f)",
         "            desk.append(f)"),
    "D12 an uncarried row falls through to the bridge":
        ("        elif m.get(\"desk_uncarried\") and f[2] == \"pending\":\n", "        elif False:\n"),
    "D13 the person projection matches every desk thread":
        ("(m.thread LIKE 'obs:person-%%') AS desk_person", "(m.thread LIKE 'obs:%%') AS desk_person"),
}
