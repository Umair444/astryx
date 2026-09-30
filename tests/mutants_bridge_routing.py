"""Authored mutants for bridges/common.py route_target() (seed #33250, a2 #33257), run by
nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_bridge_routing.py

One per clause of the precedence: explicit mention > the newest row the HUMAN saw (their own
message, or an agent's message TO them, whatever its intent) > the surface default.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "bridges" / "common.py"
ORACLE = REPO / "tests" / "test_bridge_routing.py"
ENV = "ROUTE_SRC"

MUTANTS = {
    # seed #33255: the explicit mention must ALWAYS win.
    "B1 the explicit @mention no longer wins":
        ("    if agent:                                    # 1. explicit @mention on this message\n"
         "        return agent, cleaned\n",
         "    if False:\n        return agent, cleaned\n"),
    # The pre-fix blind spot: an agent speaking to the human isn't the conversation.
    "B2 an agent's message to the human doesn't count":
        ('        elif not agent_exists(r["to_agent"]):    # an agent speaking TO the human\n'
         '            who = r["from_agent"]\n',
         '        elif False:\n            who = r["from_agent"]\n'),
    # a2 B1: an agent-to-agent handoff counted as the conversation.
    "B3 agent-to-agent rows count too":
        ('        elif not agent_exists(r["to_agent"]):    # an agent speaking TO the human\n',
         '        elif True:                               # an agent speaking TO the human\n'),
    # a2 B2: an intent allowlist restored (a receipt to the human stops counting).
    "B4 an intent allowlist on the agent's side (a receipt to the human stops counting)":
        ('"SELECT from_org, from_agent, to_agent, intent FROM messages WHERE thread=$1 "',
         '"SELECT from_org, from_agent, to_agent, intent FROM messages WHERE thread=$1 "\n'
         '        "AND (from_org<>\'local\' OR intent IN (\'chat\',\'poll\')) "'),
    "B5 the newest row is taken even when it names no agent":
        ('        if agent_exists(who):\n            return who, text\n',
         '        return who, text\n'),
    "B6 the thread filter dropped (another thread's speaker leaks in)":
        ('"SELECT from_org, from_agent, to_agent, intent FROM messages WHERE thread=$1 "',
         '"SELECT from_org, from_agent, to_agent, intent FROM messages WHERE $1::text IS NOT NULL "'),

    # seed #33262: a mention must NOT stick. Counting the human's free-text chats makes it stick.
    "B7 the human's own free-text chats count (a past @mention sticks)":
        ('            if r["intent"] == "chat":            # free text (a past @mention included) doesn\'t stick\n'
         '                continue\n', ''),
}
