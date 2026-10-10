// plan-9000 S1: the pilot executor's gate, run by node directly (type stripping), with no browser and no React.
// Called by tests/test_pilot_s1.py:  node tests/pilot_core_test.ts <catalog.json>
// The TRUSTED-input arms (a real click, keys, focus, timing in a page) are tests/pilot_browser_test.mjs.
import { readFileSync } from 'node:fs'
import { CONFIRM_ARM_MS, createExecutor, validate, type Catalog, type Handler, type TapEvent } from '../observatory/web/src/pilot/core.ts'

const catalog = JSON.parse(readFileSync(process.argv[2], 'utf8')) as Catalog
const ran: string[] = []
const handlers: Record<string, Handler> = Object.fromEntries(catalog.actions.map((a) => [a.name, (args) => { ran.push(a.name + JSON.stringify(args)); return { ok: true } }]))
let fails = 0
const arm = (name: string, ok: boolean) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}`); if (!ok) fails++ }
let t = 1000
const ex = createExecutor(catalog, handlers, { clock: () => t })
const reset = () => { ran.length = 0 }
const EL = { id: 'allow-button' }
const tap = (over: Partial<TapEvent> = {}): TapEvent => ({ isTrusted: true, pointerType: 'mouse', currentTarget: EL, timeStamp: t, ...over })

// R1: no caller names a principal
arm('the executor exposes entry points, not a principal argument', typeof (ex as unknown as { run?: unknown }).run === 'undefined'
  && ['owner', 'visitor', 'room', 'agent'].every((k) => typeof (ex as unknown as Record<string, { run: unknown }>)[k].run === 'function'))
arm('there is no owner_tap entry point', !('owner_tap' in ex))

// C2: the model's args are untrusted, and the schema is strict
reset(); let o = await ex.room.run('set_theme', { theme: 'not-a-theme' })
arm('an out-of-enum value is refused, nothing runs', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.room.run('set_theme', { theme: 'nord', href: 'https://x/?k=1' })
arm('an extra property is refused, nothing runs', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.room.run('navigate', {})
arm('a missing required arg is refused', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.owner.run('open_thread', { thread: 'x'.repeat(121) })
arm('a string over maxLength is refused', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.owner.run('eval_js', { code: '1' })
arm('an unknown action is refused', o.status === 'refused' && ran.length === 0)
arm('validate: a number where a string belongs is refused', validate({ type: 'string' }, 3) !== null)

// the matrix
reset(); o = await ex.room.run('set_theme', { theme: 'nord' })
arm('room: a view action runs', o.status === 'done' && ran.length === 1)
reset(); o = await ex.room.run('get_usage', {})
arm('room: a read is REFUSED while no egress projection is installed (fail closed)', o.status === 'refused' && ran.length === 0)
{
  const e2 = createExecutor(catalog, handlers, { project: (_a, r) => ({ projected: true, had: r !== null }) })
  reset(); const p = await e2.room.run('get_usage', {})
  arm('room: with a projector, a read returns the PROJECTED result only', p.status === 'done' && JSON.stringify(p.result) === '{"projected":true,"had":true}')
  const e3 = createExecutor(catalog, handlers, { project: () => null })
  reset(); const q = await e3.room.run('list_goals', { state: 'active' })
  arm('room: a projector that drops the result refuses it', q.status === 'refused')
}
reset(); o = await ex.owner.run('get_usage', {})
arm('owner: a read runs', o.status === 'done' && ran.length === 1)
reset(); o = await ex.agent.run('get_usage', {})
arm('agent: a read is refused', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.agent.run('open_desktop', { agent: 'forge' })
arm('agent: an actuate action is refused, not even parked', o.status === 'refused' && ran.length === 0 && ex.pending() === null)
reset(); o = await ex.visitor.run('get_usage', {})
arm('visitor (palette without the key): a read is refused', o.status === 'refused' && ran.length === 0)

// R6: a missing class reads as actuate; a missing cell is deny
{
  const c2 = structuredClone(catalog)
  c2.actions.push({ name: 'mystery', description: 'no class', parameters: { type: 'object', additionalProperties: false, properties: {} } })
  c2.matrix.room = { view: 'allow' }
  const e2 = createExecutor(c2, { ...handlers, mystery: () => { ran.push('mystery'); return null } })
  reset(); o = await e2.agent.run('mystery', {})
  arm('a classless action is actuate: refused for agent', o.status === 'refused' && ran.length === 0)
  reset(); o = await e2.room.run('mystery', {})
  arm('a missing matrix cell is deny (room without an actuate cell)', o.status === 'refused' && ran.length === 0)
}

// write / actuate: parked, and only a trusted pointer click on the bound element after it armed runs it
reset(); o = await ex.owner.run('open_desktop', { agent: 'forge' })
arm('owner: actuate is parked too (R3: the palette is not a second door)', o.status === 'pending_owner_confirm' && ran.length === 0)
arm('R4: the outcome carries no nonce', !('nonce' in o))
reset(); o = await ex.room.run('open_desktop', { agent: 'forge' })
const n1 = ex.pending()!.nonce
arm('room: actuate parks a confirm and runs nothing', o.status === 'pending_owner_confirm' && ran.length === 0)
ex.bindConfirm(n1, EL)
t += CONFIRM_ARM_MS + 10
reset(); o = await ex.confirm(n1)
arm('confirm with NO event runs nothing', o.status === 'refused' && ran.length === 0 && ex.pending()?.nonce === n1)
reset(); o = await ex.confirm(n1, tap({ isTrusted: false }))
arm('an untrusted (synthetic) event runs nothing', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.confirm(n1, tap({ pointerType: '' }))
arm('a keyboard-made click (no pointerType) runs nothing', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.confirm(n1, tap({ currentTarget: { id: 'elsewhere' } }))
arm('a click on another element runs nothing', o.status === 'refused' && ran.length === 0)
// arm v: a new request replaces the pending one; the old prompt is dead, the new one arms afresh
reset(); await ex.room.run('open_desktop', { agent: 'painter' })
const n2 = ex.pending()!.nonce
arm('a new request replaces the pending one with a new nonce', n2 !== n1)
reset(); o = await ex.confirm(n1, tap())
arm('a tap aimed at the OLD prompt runs neither call', o.status === 'refused' && ran.length === 0)
const EL2 = { id: 'allow-2' }
ex.bindConfirm(n2, EL2)
reset(); o = await ex.confirm(n2, tap({ currentTarget: EL2, timeStamp: t + CONFIRM_ARM_MS - 1 }))
arm('a click before the new prompt armed runs nothing', o.status === 'refused' && ran.length === 0)
reset(); o = await ex.confirm(n2, tap({ currentTarget: EL2, timeStamp: t + CONFIRM_ARM_MS }))
arm('a trusted click on the armed prompt runs exactly that call, once', o.status === 'done' && ran.length === 1 && ran[0] === 'open_desktop{"agent":"painter"}')
reset(); o = await ex.confirm(n2, tap({ currentTarget: EL2, timeStamp: t + 2 * CONFIRM_ARM_MS }))
arm('the same nonce never runs twice', o.status === 'refused' && ran.length === 0)
await ex.room.run('open_desktop', { agent: 'forge' })
const n3 = ex.pending()!.nonce
ex.bindConfirm(n3, EL); ex.dismiss(n3)
reset(); o = await ex.confirm(n3, tap({ timeStamp: t + 10 * CONFIRM_ARM_MS }))
arm('a dismissed prompt cannot be confirmed', o.status === 'refused' && ran.length === 0 && ex.pending() === null)
arm('a stale nonce cannot be bound', ex.bindConfirm(n1, EL) === false)

// metrics (C6 f)
const m = ex.metrics()
arm('per-action latency is recorded', !!m.set_theme && m.set_theme.n >= 1 && typeof m.set_theme.p95 === 'number')

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
process.exit(fails ? 1 : 0)
