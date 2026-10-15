"""Mutants for observatory/api/main.py's desk reply routes: /api/memory/late (a reply no poll read is served once,
never twice) and the live /api/memory/chat poll (seed #55680, a4 #56052). The oracle is
tests/test_observatory_late_replies.py, which loads OBS_MAIN_SRC in place of the real main.py.

Not listed, on purpose: dropping the late UPDATE's outer status='pending'. Probed 10-15, it survives this oracle
(NOT PROBED). That is expected: the inner SELECT … FOR UPDATE re-checks status='pending' on the row's newest version
after any lock wait, so the outer clause is a redundant second guard, not the one that holds. A listed mutant that
can't fail would read as a hole forever."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "observatory" / "api" / "main.py"
ORACLE = REPO / "tests" / "test_observatory_late_replies.py"
ENV = "OBS_MAIN_SRC"
MUTANTS = {
    "L1 late serves without marking (UPDATE leaves status pending: served again next visit)":
        ("\"UPDATE messages SET status='delivered', delivered_at=now(), \"\n"
         "        \"delivery=jsonb_build_object('ok', true, 'handle', 'observatory:late') \"",
         "\"UPDATE messages SET delivered_at=delivered_at, \"\n"
         "        \"delivery=jsonb_build_object('ok', true, 'handle', 'observatory:late') \""),
    "L2 late drops to_agent='owner' (a memory→steward row on the desk is served and marked)":
        ("\"WHERE id IN (SELECT id FROM messages WHERE to_agent='owner' AND to_org='local' \"",
         "\"WHERE id IN (SELECT id FROM messages WHERE to_org='local' \""),
    "L3 late drops to_org='local' (an owner@peer row is marked delivered though it never left)":
        ("\"WHERE id IN (SELECT id FROM messages WHERE to_agent='owner' AND to_org='local' \"",
         "\"WHERE id IN (SELECT id FROM messages WHERE to_agent='owner' \""),
    "L4 late loses who wrote it":
        ("out.append({\"id\": x[\"id\"], \"from\": x[\"from_agent\"], \"thread\"", "out.append({\"id\": x[\"id\"], \"thread\""),
    "L5 the prefix allowlist widens to every obs: thread":
        ("    if prefix not in (\"obs:estate\", \"obs:person-\", \"obs:library-\"):",
         "    if not prefix.startswith(\"obs:\"):"),
    "V1 the live poll is the old one (from memory, whoever it's addressed to)":
        ("WHERE thread=$1 AND to_agent='owner' AND to_org='local' \"", "WHERE thread=$1 AND from_agent='memory' \""),
    "V2 the live poll drops to_org='local' (serves and marks an owner@peer row)":
        ("WHERE thread=$1 AND to_agent='owner' AND to_org='local' \"", "WHERE thread=$1 AND to_agent='owner' \""),
    "V3 the live payload loses who wrote it (a seed reply reads as memory's)":
        ("{\"id\": x[\"id\"], \"from\": x[\"from_agent\"], \"body\": x[\"body\"]", "{\"id\": x[\"id\"], \"body\": x[\"body\"]"),
}
