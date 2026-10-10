#!/usr/bin/env node
// trigger_set's python-trigger path guard (channel/trigger_name.mjs; a2 #45063, a4 #45070). Pure: resolves URLs in a
// scratch dir and writes nothing outside it.
import { mkdtempSync, mkdirSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { triggerFile } from '../channel/trigger_name.mjs'

let fails = 0
const arm = (n, ok) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${n}`); if (!ok) fails++ }
const root = mkdtempSync(join(tmpdir(), 'trig-'))
const dir = pathToFileURL(join(root, 'triggers', 'canopus') + '/')
mkdirSync(fileURLToPath(dir), { recursive: true })
const refused = (name) => { try { triggerFile(dir, name); return false } catch { return true } }

for (const bad of ['../../hooks/step', '../x', '/etc/x', '..', '', 'a/b', 'a b', 'Step', 'x;rm', '%2e%2e/x', 'x\u0000', null, undefined]) {
  arm(`refused: ${JSON.stringify(bad)}`, refused(bad))
}
arm('a plain module name resolves inside triggers/<agent>/', fileURLToPath(triggerFile(dir, 'org_pulse')) === join(root, 'triggers', 'canopus', 'org_pulse.py'))
arm("the naive 'name.py' is not doubled to name.py.py", fileURLToPath(triggerFile(dir, 'org_pulse_refresh.py')).endsWith('/org_pulse_refresh.py'))
arm('nothing was written by any of it', readdirSync(fileURLToPath(dir)).length === 0)
rmSync(root, { recursive: true, force: true })
console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
process.exit(fails ? 1 : 0)
