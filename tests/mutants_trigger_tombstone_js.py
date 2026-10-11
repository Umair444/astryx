"""Authored mutants for channel/tombstone.mjs (plan-9853 D2, the trigger tombstone), run by nucleus/mutation_probe.py:

    venv/bin/python nucleus/mutation_probe.py tests/mutants_trigger_tombstone_js.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "channel/tombstone.mjs"
ORACLE = REPO / "tests" / "test_trigger_tombstone.py"
ENV = "TOMBSTONE_SRC"
TIMEOUT = 240

MUTANTS = {
    'retire writes nothing':
        ('  await writeFile(f, `${new Date().toISOString()} retired by trigger_rm\\n`)\n',
         ''),
    'clear clears nothing':
        ('    try { await unlink(tombstoneFile(root, agent, n)) } catch { /* absent, or not a name: nothing to clear */ }\n',
         ''),
    "the tombstone isn't under the agent (triggers/.retired/<name>)":
        ('  return new URL(`${a}/.retired/${n}`, root)',
         '  return new URL(`.retired/${n}`, root)'),
    'nested (indented) decorated defs count as triggers: the top-level anchor dropped':
        ('matchAll(/^@trigger\\b[^\\n]*\\n(?:@[^\\n]*\\n)*(?:async\\s+)?def\\s+([A-Za-z_]\\w*)\\s*\\(/gm)',
         'matchAll(/^\\s*@trigger\\b[^\\n]*\\n(?:\\s*@[^\\n]*\\n)*\\s*(?:async\\s+)?def\\s+([A-Za-z_]\\w*)\\s*\\(/gm)'),
}
