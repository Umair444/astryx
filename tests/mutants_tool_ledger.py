"""Authored mutants for hooks/step.py's tool ledger (goal 4227, S0), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_tool_ledger.py

Why these, and not a generic mutator. Several oracle arms PASS vacuously against the pre-4227
hook. L2 (no secret in meta) and L5 (a toolreg failure never costs the row) both hold for a hook
that writes no meta at all, so proving the oracle RED against the old file says nothing about
them. Each mutant below is the plausible way the ledger could leak or lose a row, and each one
has to turn one of those arms red on its own.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "hooks" / "step.py"
ORACLE = REPO / "tests" / "test_tool_ledger.py"
ENV = "STEP_SRC"

MUTANTS = {
    # The most natural "improvement": keep the command for debugging. It's I5's leak, and it
    # also breaks the exact-key contract steward's rollup codes to.
    "M1 meta keeps the command text":
        ("        m = resolve(tool, tool_input)\n",
         "        m = resolve(tool, tool_input)\n"
         "        if isinstance(tool_input, dict) and tool_input.get('command'):\n"
         "            m = dict(m, cmd=tool_input['command'])\n"),

    # A result excerpt next to its size. It looks harmless, but results carry file contents,
    # DSNs and tier paths.
    "M2 tool_done keeps a result excerpt":
        ('"result_bytes": len(json.dumps(response, default=str).encode())}',
         '"result_bytes": len(json.dumps(response, default=str).encode()),\n'
         '                 "head": json.dumps(response, default=str)[:80]}'),

    # The fence narrowed. A broken toolreg then raises out of the hook and the step row is lost:
    # telemetry costing the row it rides on.
    "M3 the ledger fence no longer catches a toolreg failure":
        ("    except Exception:\n        return None\n\n\ndef wall_label",
         "    except KeyError:\n        return None\n\n\ndef wall_label"),

    # No savepoint. On a DB that predates the classifications table, the failed UPDATE aborts
    # the whole transaction, so the turn row is lost with it.
    "M4 classification claim without its savepoint":
        ("            with cur.connection.transaction():\n                cur.execute(\n"
         "                    \"UPDATE classifications",
         "            if True:\n                cur.execute(\n"
         "                    \"UPDATE classifications"),

    # The claim dropped entirely. Recurrence still works, but a label can no longer be joined
    # to the turn it described.
    "M5 Stop never claims the classification":
        ("    if turn_id is not None and started_at:\n        try:\n"
         "            with cur.connection.transaction():",
         "    if False:\n        try:\n"
         "            with cur.connection.transaction():"),

    # tool_done without the edits guard would need resolve() to hand back a registry_id for a
    # Write. Model that directly: every tool_done row gets the call meta whatever the tool was.
    "M6 tool_done meta written for non-calls":
        ('            if "registry_id" not in m:\n                return None',
         '            if "registry_id" not in m:\n                m = {"registry_id": "mcp:tools/run"}'),

    # Claim by agent + time only. A killed body's leftover label, or an overlapping session's,
    # gets joined to the wrong turn.
    "M7 classification claim without the session filter":
        ('"AND (session_id IS NULL OR session_id = %s) "\n', '"AND (true OR %s IS NULL) "\n'),

    # The pre-4227 fallback restored: a description-less Bash call shows its raw command, which
    # is public and fed nightly into memory's RAG.
    "M8 the raw-command fallback restored":
        ('            detail = ti.get("description") or ti.get("file_path") \\\n',
         '            detail = ti.get("description") or ti.get("command") or ti.get("file_path") \\\n'),

    # The error text back on the wall: a Bash failure's stderr can carry anything.
    "M9 error rows carry the error text":
        ('(agent, f"{tool}: failed", meta))', '(agent, f"{tool}: {brief(err, 300)}", meta))'),

    # A label that falls back to the command when toolreg is unavailable.
    "M10 wall label falls back to the command itself":
        ('    except Exception:\n        return "(command)"\n\n\ndef dsn',
         '    except Exception:\n        return str(cmd)\n\n\ndef dsn'),
}
