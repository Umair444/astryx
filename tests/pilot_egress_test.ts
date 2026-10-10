// plan-9000 S2, C1: what leaves the page for the realtime provider. node, type stripping, no browser.
//   node tests/pilot_egress_test.ts <catalog.json>
import { readFileSync } from 'node:fs'
import { createExecutor, type Catalog, type Handler, type Json } from '../observatory/web/src/pilot/core.ts'
import { functionOutput, project } from '../observatory/web/src/pilot/egress.ts'

const catalog = JSON.parse(readFileSync(process.argv[2], 'utf8')) as Catalog
let fails = 0
const arm = (name: string, ok: boolean) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}`); if (!ok) fails++ }
const SENTINEL = 'SENTINEL-PERSONAL-7f3a'

// handlers that return MORE than the allowlist, with planted private fields
const handlers: Record<string, Handler> = Object.fromEntries(catalog.actions.map((a) => [a.name, () => ({ ok: true })]))
handlers.get_usage = () => ({ five_hour_pct: 12, seven_day_pct: 67, five_hour_reset: '2026-10-10T21:30:00Z', seven_day_reset: '2026-10-14T12:59:00Z', age_seconds: 40,
  spend: { amount: 4242, currency: 'USD' }, extra_usage_dollars: 99, note: SENTINEL } as unknown as Json)
handlers.list_goals = () => ({ state: 'active', count: 1, goals: [{ id: 9000, title: 'Observatory voice pilot', owner: 'seed', scope_note: `career thread ${SENTINEL}`, body: SENTINEL }] } as unknown as Json)
const ex = createExecutor(catalog, handlers, { project })
const wire = async (name: string, args: unknown) => JSON.stringify(functionOutput(await ex.room.run(name, args)))

const u = await wire('get_usage', {})
arm('get_usage reaches the provider with the gauges', u.includes('"five_hour_pct":12') && u.includes('"seven_day_pct":67'))
arm('a planted spend.amount is absent from the bytes', !u.includes('4242') && !u.includes('spend'))
arm('no *_dollars key leaves', !/dollars/i.test(u))
arm('an unnamed field (a personal sentinel) is absent', !u.includes(SENTINEL))
const g = await wire('list_goals', { state: 'active' })
arm('list_goals leaves id, title and owner', g.includes('9000') && g.includes('Observatory voice pilot') && g.includes('"owner":"seed"'))
arm('a sentinel in a goal\'s scope_note or body is absent from the bytes', !g.includes(SENTINEL) && !g.includes('scope_note') && !g.includes('body'))
arm('an unknown read is refused by the projector (fail closed)', project('something_new', { a: 1 }) === null)
const p = await wire('open_desktop', { agent: 'forge' })
arm('a parked confirm tells the provider only that the owner must tap', p.includes('tap Allow') && !p.includes(ex.pending()!.nonce))
const r = await wire('set_theme', { theme: 'nope' })
arm('a refusal leaves as an error string', r.includes('"ok":false') && r.includes('error'))

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
process.exit(fails ? 1 : 0)
