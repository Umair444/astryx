"""Authored mutants for channel/tombstone.mjs (plan-9853 D2, the trigger tombstone), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_trigger_tombstone_js.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "channel/tombstone.mjs"
ORACLE = REPO / "tests" / "test_trigger_tombstone.py"
ENV = "TOMBSTONE_SRC"
TIMEOUT = 300

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
    'definedNames answers nothing':
        ('      resolve(Array.isArray(names) ? names.filter(n => TRIGGER_NAME.test(String(n))) : [])\n',
         '      resolve([])\n'),
    "back to the one-line source regex (a4 #49496): multi-line decorators and shims are missed":
        ('      try { names = err ? [] : JSON.parse(stdout) } catch { names = [] }\n',
         "      names = [...process.getBuiltinModule('node:fs').readFileSync(file, 'utf8').matchAll("
         "/^@trigger\\b[^\\n]*\\n(?:@[^\\n]*\\n)*(?:async\\s+)?def\\s+([A-Za-z_]\\w*)\\s*\\(/gm)].map(x => x[1])\n"),
}
