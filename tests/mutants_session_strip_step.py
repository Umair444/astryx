"""Mutants for plan-9139 S1d in hooks/step.py: the whole-session strip and the child-spawn refusal. The oracle is
tests/test_session_strip.py."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "hooks" / "step.py"
ORACLE = REPO / "tests" / "test_session_strip.py"
ENV = "STEP_SRC"
MUTANTS = {
    "S1 an unreadable label reads as ORG (no charter, a malformed grant: unstripped)":
        ("        return f\"{MARK} (label unreadable: {type(e).__name__})\"", "        return None"),
    "S2 only the tool calls are stripped, never the turn (a1's mutant: the heredoc staging rides the transcript)":
        ("    if strip:                            # S1d: the turn's text", "    if False:                            # S1d: the turn's text"),
    "S3 the turn's input_prompt is kept":
        ("        stored_prompt = f\"[{MARK}]\"", "        stored_prompt = input_prompt"),
    "S4 the response step carries the reply":
        ("(f\"[{MARK}: {len(last_text.encode())} bytes]\" if strip", "(f\"[{MARK}: {last_text}]\" if strip"),
    "S5 a step's description, path or target is kept":
        ("            if strip:                          # S1d: a description", "            if False:                          # S1d: a description"),
    "S6 the stripped raw_payload keeps the messages":
        ("        payload = {\"withheld\": strip, \"usage\": payload.get(\"usage\")}",
         "        payload = {\"withheld\": strip, **payload}"),
    "S7 a Bash call of the CLI is never a spawn":
        ("    if tool == \"Bash\":\n        cmd = (ti or {}).get(\"command\") or \"\"",
         "    if False:\n        cmd = (ti or {}).get(\"command\") or \"\""),
    "S8 the CLI's name is typed, not derived (ASTRYX_CLI ignored)":
        ("    return {os.path.basename(n) for n in names if n} or {\"claude\"}", "    return {\"claude\"}"),
    "S9 the Workflow and Task tools are not spawns":
        ("SPAWN_TOOLS = frozenset({\"Agent\", \"Task\", \"Workflow\"})", "SPAWN_TOOLS = frozenset({\"Agent\"})"),
    "S10 a path to the binary isn't recognised (no basename)":
        ("        words = {os.path.basename(w) for w in", "        words = {w for w in"),
    "S11 the label is read from the door module's tree, not the hook's (a fixture's agents/ ignored)":
        ("        return MARK if release.label_of(agent, Path(REPO) / \"agents\") else None",
         "        return MARK if release.label_of(agent) else None"),
    "S12 the spawn refusal is decided after the DB (a dead DSN opens it)":
        ("        if not denied:\n            denied = spawn_guard(h.get(\"tool_name\", \"?\"), h.get(\"tool_input\") or {}, strip)",
         "        pass"),
}
