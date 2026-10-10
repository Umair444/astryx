#!/usr/bin/env node
// trigger_set's python-trigger path guard (channel/trigger_name.mjs; a2 #45063, a4 #45070). Pure: resolves URLs in a
// scratch dir and writes nothing outside it.
import { mkdtempSync, mkdirSync, readdirSync, readFileSync, rmSync } from 'node:fs'
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
rmSync(root, { recursive: true, force: true })

// WIRING (a2 #45073): the hole lives in channel/server.mjs, so the oracle reads it. In trigger_set's python branch:
// (a) the only writeFile target is the value triggerFile(dir, a.name) returned; (b) that call precedes the mkdir, so a
// refused name throws before anything is created; (c) no `new URL(` anywhere is built from a.name.
const src = readFileSync(new URL('../channel/server.mjs', import.meta.url), 'utf8')
const start = src.indexOf("if (name === 'trigger_set')")
const branch = src.slice(src.indexOf("a.kind === 'python'", start), src.indexOf('if (!a.schedule)', start))
const bind = branch.match(/const\s+(\w+)\s*=\s*triggerFile\(\s*dir\s*,\s*a\.name\s*\)/)
const writes = [...branch.matchAll(/writeFile\(\s*([^,]+?)\s*,/g)].map((m) => m[1])
arm('server.mjs: trigger_set binds its file through triggerFile(dir, a.name)', !!bind)
arm('server.mjs: the only writeFile target is that bound value', !!bind && writes.length >= 1 && writes.every((w) => w === bind[1]))
arm('server.mjs: triggerFile runs before the mkdir (a refused name creates nothing)', !!bind && branch.indexOf(bind[0]) < branch.indexOf('mkdir'))
arm('server.mjs: no `new URL(` is built from a.name anywhere', !/new URL\([^)]*a\.name/.test(src))
console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
process.exit(fails ? 1 : 0)
