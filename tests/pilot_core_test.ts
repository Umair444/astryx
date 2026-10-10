// plan-9000 S1: the pilot executor's gate, run by node directly (type stripping), with no browser and no React.
// Called by tests/test_pilot_s1.py:  node tests/pilot_core_test.ts <catalog.json>
import { readFileSync } from 'node:fs'
import { createExecutor, validate, type Catalog, type Handler } from '../observatory/web/src/pilot/core.ts'

const catalog = JSON.parse(readFileSync(process.argv[2], 'utf8')) as Catalog
const ran: string[] = []
const handlers: Record<string, Handler> = Object.fromEntries(catalog.actions.map((a) => [a.name, (args) => { ran.push(a.name + JSON.stringify(args)); return { ok: true } }]))
let fails = 0
const arm = (name: string, ok: boolean) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}`); if (!ok) fails++ }

const ex = createExecutor(catalog, handlers)
const reset = () => { ran.length = 0 }

// C2: the model's args are untrusted, and the schema is strict
reset(); let o = await ex.run('set_theme', { theme: 'not-a-theme' }, 'room')
arm('an out-of-enum value is refused, nothing runs', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.run('set_theme', { theme: 'nord', href: 'https://x/?k=1' }, 'room')
arm('an extra property is refused, nothing runs', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.run('navigate', {}, 'room')
arm('a missing required arg is refused', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.run('open_thread', { thread: 'x'.repeat(121) }, 'owner_tap')
arm('a string over maxLength is refused', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.run('eval_js', { code: '1' }, 'owner_tap')
arm('an unknown action is refused', o.status === 'refused' && ran.length === 0)
arm('validate: a number where a string belongs is refused', validate({ type: 'string' }, 3) !== null)

// the matrix
reset(); o = await ex.run('set_theme', { theme: 'nord' }, 'room')
arm('room: a view action runs', o.status === 'done' && ran.length === 1)
reset(); o = await ex.run('get_usage', {}, 'room')
arm('room: a read action runs, marked for the egress projection', o.status === 'done' && o.projection === true)
reset(); o = await ex.run('get_usage', {}, 'agent')
arm('agent: a read action is refused', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.run('open_desktop', { agent: 'forge' }, 'agent')
arm('agent: an actuate action is refused', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.run('navigate', { view: 'goals' }, 'anonymous')
arm('anonymous: even a view action is refused', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.run('navigate', { view: 'goals' }, 'peer')
arm('peer: refused', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.run('get_usage', {}, 'visitor')
arm('visitor (palette without the key): a read is refused', o.status === 'refused' && ran.length === 0)

// R6: a missing class reads as actuate; a missing cell is deny
{
  const c2 = structuredClone(catalog)
  c2.actions.push({ name: 'mystery', description: 'no class', parameters: { type: 'object', additionalProperties: false, properties: {} } })
  c2.matrix.room = { view: 'allow' }
  const e2 = createExecutor(c2, { ...handlers, mystery: () => { ran.push('mystery'); return null } })
  reset(); o = await e2.run('mystery', {}, 'agent')
  arm('a classless action is actuate: refused for agent', o.status === 'refused' && ran.length === 0)
  reset(); o = await e2.run('mystery', {}, 'room')
  arm('a missing matrix cell is deny (room without an actuate cell)', o.status === 'refused' && ran.length === 0)
}

// the owner-tap confirm: a model call to actuate runs NOTHING until the owner taps THAT prompt
reset(); const a1 = await ex.run('open_desktop', { agent: 'forge' }, 'room')
arm('room: actuate parks a confirm and runs nothing', a1.status === 'needs_confirm' && ran.length === 0)
const n1 = a1.status === 'needs_confirm' ? a1.nonce : ''
reset(); const a2 = await ex.run('open_desktop', { agent: 'painter' }, 'room')
const n2 = a2.status === 'needs_confirm' ? a2.nonce : ''
arm('a new request replaces the pending one with a new nonce', a2.status === 'needs_confirm' && n2 !== n1 && ex.pending()?.nonce === n2)
reset(); o = await ex.confirm(n1)
arm('a tap on the OLD prompt runs neither call (a4 #44113 arm v)', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.confirm(n2)
arm('a tap on the pending prompt runs exactly that call, once', o.status === 'done' && ran.length === 1 && ran[0] === 'open_desktop{"agent":"painter"}')
reset(); o = await ex.confirm(n2)
arm('the same nonce never runs twice', o.status === 'refused' && ran.length === 0)
const a3 = await ex.run('open_desktop', { agent: 'forge' }, 'room')
if (a3.status === 'needs_confirm') ex.dismiss(a3.nonce)
reset(); o = await ex.confirm(a3.status === 'needs_confirm' ? a3.nonce : '')
arm('a dismissed prompt cannot be confirmed', o.status === 'refused' && ran.length === 0 && ex.pending() === null)

// metrics (C6 f)
const m = ex.metrics()
arm('per-action latency is recorded', !!m.set_theme && m.set_theme.n >= 1 && typeof m.set_theme.p95 === 'number')

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
process.exit(fails ? 1 : 0)
