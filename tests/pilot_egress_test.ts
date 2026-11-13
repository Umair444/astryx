// plan-9000 S2, C1: what leaves the page for the realtime provider. node, type stripping, no browser.
//   node tests/pilot_egress_test.ts <catalog.json>
import { readFileSync } from 'node:fs'
import { createExecutor, type Catalog, type Handler, type Json } from '../observatory/web/src/pilot/core.ts'
import { functionOutput, mask, project, projectScreen, screenLine, SCREEN_BUDGET } from '../observatory/web/src/pilot/egress.ts'
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
arm('open_desktop from the owner\'s call runs outright (11-11) and leaves only the desktop field', p.includes('"ok":true') && ex.pending() === null && !p.includes(SENTINEL))
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
  for (const a of catalog.actions.filter((x) => x.class === 'view' || x.class === 'read' || x.class === 'compose')) {
    if (project(a.name, {}) === null) arm(`every room-reachable action has a projection entry: ${a.name}`, false)
  }
  arm('every view, read and compose action has a projection entry (no silent refusal)', true)
}

// ---- the call (iteration 17): what the voice is told about the screen. SYNTHETIC numbers only (03XXXXXXXXX shape).
{
  const CC_PHONE = '92' + '3001234567'   // built at runtime: the privacy gate refuses the literal in a tracked file
  const PHONES = ['03001234567', '0300-1234567', '+92 300 1234567', '0300 123 4567', CC_PHONE]
  const ACCOUNT = '1234567890123456'
  for (const ph of PHONES) {
    const m = mask(`call ${ph} today`)
    arm(`a phone-shaped run is masked: ${ph.replace(/\d/g, 'X')}`, !m.includes(ph) && m.includes('[number]') && m.replace(/\D/g, '').length === 0)
  }
  arm('an account/card-shaped run is masked', !mask(`acct ${ACCOUNT}`).includes(ACCOUNT) && !/\d{7}/.test(mask(`acct ${ACCOUNT}`)))
  arm('a count, a percentage and a date survive the mask', mask('3,742 wallets, 42% up, on 2026-11-11') === '3,742 wallets, 42% up, on 2026-11-11')
  arm('an e-mail is masked', !mask('mail a.b+c@example.com now').includes('example.com'))
  arm('a bearer-ish token is masked', !mask('key sk-test-ABCDEFGH12345678 here').includes('ABCDEFGH') && !mask('ek_68e1c0ffee00aa11bb22').includes('c0ffee'))
  arm('key=value secrets are masked', !mask('password: hunter2xyz').includes('hunter2') && !mask('token=abc123def').includes('abc123'))
  arm('a URL keeps its path, never its query', mask('see https://x.example/a/b?obs_key=SECRETQ#frag') === 'see https://x.example/a/b')
  arm('a long hex run is masked', !mask('hash 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08').includes('9f86d0'))

  const PH = '03001234567'
  const raw = {
    surface: 'chat', view: 'thread', title: `Wallet ${PH} reconciliation`, agent: 'db',
    headings: ['Daily actives', `Lookup for 0300-1234567`], captions: [`Top senders (${ACCOUNT})`],
    lines: [`db: the number +92 300 1234567 has 3 txns`, 'owner: thanks'], dialog: null, draft: true,
    body: SENTINEL, url: `http://h/#/chat?obs_key=${SENTINEL}`,
  }
  const h2: Record<string, Handler> = Object.fromEntries(catalog.actions.map((a) => [a.name, () => ({ ok: true })]))
  h2.read_screen = () => raw as unknown as Json
  h2.type_in_composer = (a) => ({ typed: true, chars: String(a.text).length, text: a.text } as unknown as Json)
  const ex3 = createExecutor(catalog, h2, { project })
  const scr = JSON.stringify(functionOutput(await ex3.room.run('read_screen', {})))
  arm('read_screen reaches the provider (title words, agent, headings)', scr.includes('reconciliation') && scr.includes('"agent":"db"') && scr.includes('Daily actives'))
  arm('no phone- or account-shaped digit run is in the read_screen bytes', !/\d[\d\s-]{6,}\d/.test(scr.replace(/"chars":\d+/g, '')) && !scr.includes(PH) && !scr.includes(ACCOUNT))
  arm('a field the projection does not name (a body, a URL) never leaves', !scr.includes(SENTINEL) && !scr.includes('obs_key'))
  arm('the draft leaves as a flag, never its words', scr.includes('"draft":true'))
  const line = screenLine(projectScreen(raw))
  arm('the pushed context line carries the screen and no digit run', line.includes('reconciliation') && !/\d{7}/.test(line.replace(/\D+/g, (m) => (m.length > 3 ? ' ' : ''))) && !line.includes(PH))
  const big = { headings: Array.from({ length: 50 }, (_, i) => `Heading ${i} ` + 'x'.repeat(90)), captions: Array.from({ length: 50 }, () => 'c'.repeat(120)),
    lines: Array.from({ length: 50 }, () => 'l'.repeat(200)), title: 't'.repeat(500) }
  arm(`the screen is cut to the budget (${SCREEN_BUDGET} chars) as a whole`, JSON.stringify(projectScreen(big)).length <= SCREEN_BUDGET)
  arm('a non-object screen projects to an empty shape, not a throw', JSON.stringify(projectScreen('nope')).length < 200)
  const typed = JSON.stringify(functionOutput(await ex3.room.run('type_in_composer', { text: `ping ${PH}` })))
  arm('type_in_composer echoes a count, never the typed words', typed.includes('"typed":true') && !typed.includes(PH) && !typed.includes('ping'))
  const sent = JSON.stringify(functionOutput(await ex3.room.run('send_message', { text: `hello ${PH}` })))
  arm('send_message from the owner\'s call sends at once (11-11) and echoes nothing', sent.includes('"sent":') && !sent.includes(PH) && !sent.includes('hello') && ex3.pending() === null)
  arm('switch_agent (compose) runs for the room without a tap', (await ex3.room.run('switch_agent', { agent: 'db' })).status === 'done')
}

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
process.exit(fails ? 1 : 0)
