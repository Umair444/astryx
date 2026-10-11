#!/usr/bin/env node
// plan-9853 D2: trigger_rm's tombstone (channel/tombstone.mjs), pure, in a scratch dir; plus its WIRING in server.mjs.
import { mkdtempSync, existsSync, rmSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
// Seams for the python oracle (tests/test_trigger_tombstone.py runs this): TOMBSTONE_SRC is the module under test,
// staged beside trigger_name.mjs; SERVER_SRC the server.mjs whose wiring is read.
const { tombstoneFile, retire, clear, triggerNames } = await import(
  process.env.TOMBSTONE_SRC ? pathToFileURL(process.env.TOMBSTONE_SRC).href : '../channel/tombstone.mjs')

let fails = 0
const arm = (n, ok) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${n}`); if (!ok) fails++ }
const root = pathToFileURL(join(mkdtempSync(join(tmpdir(), 'tomb-')), 'triggers') + '/')
const refused = (a, n) => { try { tombstoneFile(root, a, n); return false } catch { return true } }
for (const [a, n] of [['../x', 'n'], ['a', '../n'], ['a', 'N'], ['', 'n'], ['a', ''], ['a/b', 'n'], ['a', 'n.py']]) {
  arm(`refused: agent ${JSON.stringify(a)} name ${JSON.stringify(n)}`, refused(a, n))
}
const f = await retire(root, 'canopus', 'watch_x')
arm('retire writes triggers/<agent>/.retired/<name>', fileURLToPath(f) === join(fileURLToPath(root), 'canopus', '.retired', 'watch_x') && existsSync(f))
await clear(root, 'canopus', ['watch_x', 'never_there', '../evil'])
arm('clear removes it (and ignores absent or invalid names)', !existsSync(f))
const src = '@trigger("* * * * *")\ndef a1(ctx):\n    pass\n\n@trigger("*/5 * * * *", note="x")\n@other\nasync def b2(ctx):\n    pass\n\ndef plain(ctx):\n    pass\n\nclass K:\n    @trigger("x")\n    def nested(self): pass\n'
arm('triggerNames: top-level @trigger defs (stacked decorators, async), not plain or nested ones',
  JSON.stringify(triggerNames(src)) === JSON.stringify(['a1', 'b2']))
rmSync(fileURLToPath(new URL('../', root)), { recursive: true, force: true })

// WIRING: server.mjs retires python triggers in trigger_rm, and un-retires what trigger_set writes.
const s = readFileSync(process.env.SERVER_SRC || new URL('../channel/server.mjs', import.meta.url), 'utf8')
const rm = s.slice(s.indexOf("if (name === 'trigger_rm')"), s.indexOf('throw new Error(`unknown tool', s.indexOf("if (name === 'trigger_rm')")))
arm("trigger_rm: RETURNING kind, then retire(…, AGENT, a.name) only for kind 'python'",
  /RETURNING kind/.test(rm) && /kind === 'python'/.test(rm) && /retire\(TRIGGERS_ROOT, AGENT, a\.name\)/.test(rm))
const set = s.slice(s.indexOf("if (name === 'trigger_set')"), s.indexOf("if (name === 'trigger_list')"))
const py = set.slice(set.indexOf("a.kind === 'python'"), set.indexOf('if (!a.schedule)'))
arm('trigger_set python: clear(…, triggerNames(a.check)) AFTER the file is written',
  py.indexOf('clear(TRIGGERS_ROOT, AGENT, triggerNames(a.check))') > py.indexOf('writeFile(file, a.check)') && py.includes('writeFile(file, a.check)'))
arm('trigger_set heartbeat/sql: clear(…, [a.name])', set.slice(set.indexOf('if (!a.schedule)')).includes('clear(TRIGGERS_ROOT, AGENT, [a.name])'))
console.log(fails ? `FAIL: ${fails}` : 'PASS: tombstones (per agent and name), and server.mjs writes and clears them')
process.exit(fails ? 1 : 0)
