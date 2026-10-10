// plan-9000 S2, C1: what leaves the page for the realtime provider. node, type stripping, no browser.
//   node tests/pilot_egress_test.ts <catalog.json>
import { readFileSync } from 'node:fs'
import { createExecutor, type Catalog, type Handler, type Json } from '../observatory/web/src/pilot/core.ts'
import { functionOutput, project } from '../observatory/web/src/pilot/egress.ts'
import { makeHandlers, type PilotCtx } from '../observatory/web/src/pilot/handlers.ts'

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

// R2 (a4 #44288): get_view_state READS the page. Run the REAL handler against a page that holds an obs key in the
// URL, a personal thread open, and a private agent's step body on screen; the bytes the provider gets carry none.
{
  const KEYSENT = 'OBSKEY-SENTINEL-91c2'
  const THREAD = 'career-offer-SENTINEL-ab12'
  const BODY = 'STEP-BODY-SENTINEL-55e0'
  const g = globalThis as unknown as Record<string, unknown>
  g.location = { hash: `#/wire/${THREAD}?key=${KEYSENT}`, search: `?key=${KEYSENT}`, href: `http://x/?key=${KEYSENT}#/wire/${THREAD}` }
  g.document = { body: { innerText: BODY }, title: BODY }
  const ctx = {
    view: () => 'wire', thread: () => THREAD, navigate: () => {}, openThread: () => {},
    agents: () => ['canopus', 'seed'], agentOpen: () => 'canopus', openAgent: () => {},
    themes: () => [{ id: 'nord', name: 'Nord' }], theme: () => 'nord', setTheme: () => {}, cycleTheme: () => {},
    desktopOpen: () => null, openDesktop: () => {}, deskOf: () => null, get: async () => ({}),
  } as unknown as PilotCtx
  const real = makeHandlers(ctx)
  const ex2 = createExecutor(catalog, real, { project })
  const out = await ex2.room.run('get_view_state', {})
  const frame = JSON.stringify({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: 'c1', output: JSON.stringify(functionOutput(out)) } })
  arm('get_view_state reaches the provider (view, theme, the open agent\'s name)', out.status === 'done' && frame.includes('wire') && frame.includes('nord') && frame.includes('canopus'))
  arm('an OBS_KEY in the URL is absent from the frame', !frame.includes(KEYSENT))
  arm('a personal thread key is absent from the frame', !frame.includes(THREAD))
  arm('a private agent\'s step body on the page is absent from the frame', !frame.includes(BODY))
  const ctx2 = { ...ctx, thread: () => 'plan-9000' } as PilotCtx
  const o2 = await createExecutor(catalog, makeHandlers(ctx2), { project }).room.run('get_view_state', {})
  arm('an org plan thread key may leave', JSON.stringify(functionOutput(o2)).includes('plan-9000'))
  const nav = JSON.stringify(functionOutput(await createExecutor(catalog, makeHandlers(ctx), { project }).room.run('open_thread', { thread: THREAD })))
  arm('open_thread on a personal key does not echo it back', !nav.includes(THREAD))
  for (const a of catalog.actions.filter((x) => x.class === 'view' || x.class === 'read')) {
    if (project(a.name, {}) === null) arm(`every room-reachable action has a projection entry: ${a.name}`, false)
  }
  arm('every view and read action has a projection entry (no silent refusal)', true)
}

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
process.exit(fails ? 1 : 0)
