"""Authored mutants for bridges/common.py route_target() (seed #33250), run by
nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_bridge_routing.py

One per clause of the rule "the newest agent-bearing row on THIS thread". B1 is the pre-fix
rule that misrouted the owner's go-ahead.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "bridges" / "common.py"
ORACLE = REPO / "tests" / "test_bridge_routing.py"
ENV = "ROUTE_SRC"

MUTANTS = {
    "B1 the pre-fix rule (last inbound CHAT's to_agent only)":
        ("\"SELECT CASE WHEN from_org='local' THEN from_agent ELSE to_agent END AS who \"\n"
         "        \"FROM messages WHERE thread=$1 AND intent IN ('chat','poll') \"\n"
         "        \"AND (from_org='local' OR to_org='local') ORDER BY id DESC LIMIT 20\"",
         "\"SELECT to_agent AS who FROM messages WHERE thread=$1 AND intent='chat' \"\n"
         "        \"AND from_org<>'local' AND to_org='local' ORDER BY id DESC LIMIT 20\""),
    "B2 an agent's own message is not counted as it speaking":
        ("CASE WHEN from_org='local' THEN from_agent ELSE to_agent END", "to_agent"),
    "B3 poll votes don't count":
        ("AND intent IN ('chat','poll') ", "AND intent='chat' "),
    "B4 the newest row is taken even when it names no agent":
        ('        if agent_exists(r["who"]):\n            return r["who"], text\n',
         '        return r["who"], text\n'),
    "B5 the thread filter dropped (another thread's speaker leaks in)":
        ("FROM messages WHERE thread=$1 AND", "FROM messages WHERE $1::text IS NOT NULL AND"),
}
