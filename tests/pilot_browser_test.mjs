#!/usr/bin/env node
// plan-9000 S1, the TRUSTED-input arms (#44094 (i)-(iv), a4 #44113 (v), a1 #44141 R2): the owner-tap confirm in a
// real page, driven over CDP. CDP's Input.dispatchMouseEvent / dispatchKeyEvent produce isTrusted events, which is
// what the gate must tell apart from the model's calls (data-channel function calls, never DOM events).
//
//   node tests/pilot_browser_test.mjs [observatory dev URL]
//
// With no URL it starts a vite dev server from observatory/web and stops it after. Every listener is found through what
// THIS gate owns (plan-10108 D3): vite picks a free port itself and the URL is read from its own stdout; chromium takes
// port 0 and its port is read from its own profile's DevToolsActivePort. Concurrent gates never share one. It reads
// OBS_KEY from .env into a throwaway chromium profile (never printed) and talks to the live API read-only. The
// actuate it confirms is open_desktop for an agent with no desktop, so the handler runs and fails harmlessly.
// Absent chromium, node_modules or key: exit 77 on a committed-only tree (no triggers/), but 1, BROKEN, on a LIVE
// host, where this gate is the proof of a prevention-graded cell and must not switch itself off quietly (a1 #44266).
// Every wait is on a condition with a deadline, never on time alone, and names itself when it expires.
import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

// PILOT_REPO: tests/test_gate_concurrency.py runs a MUTANT copy of this file from a temp dir (its seam)
const REPO = process.env.PILOT_REPO || join(dirname(fileURLToPath(import.meta.url)), '..')
const CHROME = ['/usr/bin/chromium', '/usr/bin/google-chrome-stable', '/usr/bin/chromium-browser'].find(existsSync)
const WEB = join(REPO, 'observatory/web')
const envPath = join(REPO, '.env')  // org-home: one org: a live probe of this tree's org; no JS estate resolver (home.mjs defaults to ASTRYX_HOME, not this tree)
const KEY = existsSync(envPath) ? (readFileSync(envPath, 'utf8').split('\n').find((l) => l.startsWith('OBS_KEY=')) || '').slice(8).trim() : ''
// THIS tree's federation name: in a cog the front answers a bare /api with 409 until the viewer picks a room, and a fresh
// profile has picked none, so the gate picks the room this tree IS, by name, never "the first org" (steward #61761)
const ORG_NAME = existsSync(envPath) ? (readFileSync(envPath, 'utf8').split('\n').find((l) => l.startsWith('ASTRYX_ORG=')) || '').slice(11).trim() : ''
if (!CHROME || !KEY || !existsSync(join(WEB, 'node_modules/.bin/vite'))) {
  const why = !CHROME ? 'no chromium' : !KEY ? 'no OBS_KEY in .env' : 'no observatory/web/node_modules'
  if (existsSync(join(REPO, 'triggers'))) { console.log(`  BROKEN: ${why} on a live host (triggers/ present)`); process.exit(1) }  // org-home: audit: is THIS tree a live host
  console.log(`  NOT SEARCHED: ${why} (a committed-only tree: triggers/ absent)`)
  process.exit(77)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
/** Poll `test` until truthy or `ms` passes; on expiry, say which wait it was and stop. */
async function until(what, test, ms = 60000) {
  const end = Date.now() + ms
  for (;;) {
    try { const v = await test(); if (v) return v } catch {}
    if (Date.now() > end) { console.log(`  FAIL  timed out after ${ms / 1000}s waiting for ${what}`); console.log('FAIL (1)'); cleanup(); process.exit(1) }
    await sleep(200)
  }
}
const kids = []
// cleanup kills each child's whole DESCENDANT tree (read from /proc), not just the child: chromium's renderers and
// vite's workers outlived a kill of the main pid alone when the gate exited fast on a failure (7 chromium processes
// left, measured 10-11). The children stay in this process group on purpose, so an outer group kill (check.sh's
// per-gate cap) reaches them too.
const tree = (root) => {
  const kids = new Map()
  for (const d of readdirSync('/proc')) {
    if (!/^\d+$/.test(d)) continue
    try { const ppid = Number(readFileSync(`/proc/${d}/stat`, 'utf8').split(') ')[1].split(' ')[1]); (kids.get(ppid) ?? kids.set(ppid, []).get(ppid)).push(Number(d)) } catch {}
  }
  const out = []; const walk = (p) => { for (const c of kids.get(p) ?? []) { out.push(c); walk(c) } }
  walk(root); return out
}
// a child that already exited is skipped (its pid could be reused); then, as a belt, any process whose argv carries
// this run's unique chromium profile dir is killed too: every chromium child does carry it (13/13 measured), so a
// renderer reparented by a crashed main is still found (measured: they also exit by themselves within 3s)
const byArgv = (needle) => readdirSync('/proc').filter((d) => /^\d+$/.test(d)).filter((d) => {
  try { return readFileSync(`/proc/${d}/cmdline`, 'utf8').includes(needle) } catch { return false }
}).map(Number).filter((pid) => pid !== process.pid)
let PROFILE = ''
const cleanup = () => {
  for (const k of kids) {
    if (k.exitCode !== null || k.signalCode !== null) continue
    for (const pid of [...tree(k.pid), k.pid]) try { process.kill(pid, 'SIGKILL') } catch {}
  }
  if (PROFILE) for (const pid of byArgv(`--user-data-dir=${PROFILE}`)) try { process.kill(pid, 'SIGKILL') } catch {}
}
process.on('exit', cleanup)
// a hung run is a FAIL that names itself, never a process that holds a check.sh slot for hours (steward #45245: one
// run hung 3h37m). The whole gate gets WALL_MS; every CDP call gets CALL_MS (a dead chromium never answers).
const WALL_MS = Number(process.env.PILOT_GATE_WALL_MS || 600000)
const CALL_MS = 30000
setTimeout(() => { console.log(`  FAIL  the gate exceeded its ${WALL_MS / 1000}s wall clock (a hang, not a verdict)`); console.log('FAIL (1)'); cleanup(); process.exit(1) }, WALL_MS)

let URL0 = process.argv[2]
if (!URL0) {
  // no --port/--strictPort: vite listens on a free port itself (on EADDRINUSE it takes the next, never a probe-then-
  // release), and the gate learns the port FROM vite's own stdout. Its dependency cache is this gate's (D2).
  const cache = process.env.VITE_CACHE_DIR || mkdtempSync(join(tmpdir(), 'pilot-vite-'))
  if (!process.env.VITE_CACHE_DIR) process.on('exit', () => { try { rmSync(cache, { recursive: true, force: true }) } catch {} })
  const vite = spawn(join(WEB, 'node_modules/.bin/vite'), ['--host', '127.0.0.1'], { cwd: WEB, stdio: ['ignore', 'pipe', 'ignore'],
    env: { ...process.env, VITE_CACHE_DIR: cache } })
  kids.push(vite)
  let said = ''
  vite.stdout.setEncoding('utf8')
  vite.stdout.on('data', (d) => { if (said.length < 65536) said += d })   // keeps DRAINING after the URL (a full pipe stalls vite)
  const local = await until('vite to print its own URL', async () => said.replace(/\x1b\[[0-9;]*m/g, '').match(/Local:\s+(http:\/\/127\.0\.0\.1:\d+\/)/)?.[1])
  URL0 = local
}
// vite serves index.html before its first dependency optimization finishes; wait for the app's entry module too
await until('the dev server to answer', async () => (await fetch(URL0)).ok)
await until('the app entry module to compile', async () => (await fetch(new URL('/src/main.tsx', URL0))).ok)
const prof = mkdtempSync(join(tmpdir(), 'pilot-cdp-'))
PROFILE = prof
process.on('exit', () => { try { rmSync(prof, { recursive: true, force: true, maxRetries: 5 }) } catch {} })   // chromium may still be writing as it exits
// port 0: chromium binds a free port itself and writes it to <its own profile>/DevToolsActivePort (line 1)
kids.push(spawn(CHROME, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${prof}`, '--window-size=1280,860', 'about:blank'], { stdio: 'ignore' }))
const port = await until('chromium to write its own DevToolsActivePort', async () => {
  const p = Number(readFileSync(join(prof, 'DevToolsActivePort'), 'utf8').split('\n')[0])
  return p > 0 ? p : null
}, 30000)
let ws
const page = await until('chromium\'s debugging port', async () => (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === 'page'), 30000)
ws = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((r) => ws.addEventListener('open', r))
let id = 0
const waits = new Map()
const errors = []
ws.addEventListener('message', (m) => {
  const d = JSON.parse(m.data)
  if (d.id && waits.has(d.id)) { waits.get(d.id)(d); waits.delete(d.id) }
  if (d.method === 'Runtime.exceptionThrown') errors.push((d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text || '').split('\n')[0])
})
const cdp = (method, params = {}) => new Promise((r, reject) => {
  const i = ++id
  const t = setTimeout(() => { waits.delete(i); reject(new Error(`CDP ${method} gave no answer in ${CALL_MS / 1000}s`)) }, CALL_MS)
  waits.set(i, (d) => { clearTimeout(t); r(d) })
  ws.send(JSON.stringify({ id: i, method, params }))
})
for (const ev of ['unhandledRejection', 'uncaughtException']) {   // a rejected top-level await arrives as the latter
  process.on(ev, (e) => { console.log(`  FAIL  ${e?.message || e}`); console.log('FAIL (1)'); cleanup(); process.exit(1) })
}
const ev = async (expr) => (await cdp('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value
const keyEv = (type, key, code, vk, extra = {}) => cdp('Input.dispatchKeyEvent', { type, key, code, windowsVirtualKeyCode: vk, ...extra })
const press = async (key, code, vk) => { await keyEv('keyDown', key, code, vk, key === ' ' ? { text: ' ' } : key === 'Enter' ? { text: '\r' } : {}); await keyEv('keyUp', key, code, vk) }
const click = async (x, y) => {
  await cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 })
  await cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 })
}
const T = 'window.__pilotTest'
const pend = () => ev(`(${T}.pending() || {}).nonce || null`)
const desktopRuns = () => ev(`${T}.ran().filter(r => r.action === 'open_desktop').length`)
const allow = () => ev(`(() => { const b = document.querySelector('[data-pilot-allow]'); if (!b) return null; const r = b.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2, nonce: b.closest('[data-pilot-confirm]').dataset.pilotConfirm } })()`)
const waitAllow = async (nonce) => { for (let i = 0; i < 40; i++) { const a = await allow(); if (a && (!nonce || a.nonce === nonce)) return a; await sleep(25) } return null }
const room = (agent) => ev(`${T}.room.run('open_desktop', { agent: ${JSON.stringify(agent)} }).then(o => o.status)`)
let fails = 0
const arm = (n, ok, d = '') => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${n}${!ok && d !== '' ? '  (' + d + ')' : ''}`); if (!ok) fails++ }

await cdp('Runtime.enable')
await cdp('Page.enable')
await cdp('Page.navigate', { url: URL0 })
await until('the first page load', () => ev(`document.readyState === 'complete'`))
await ev(`localStorage.setItem('obs_key', ${JSON.stringify(KEY)}); true`)
// A cog's front (409 on a bare /api/whoami): choose this tree's room as the app's chooser does, the astryx_org cookie
// (cog.tsx chooseOrg), so the reload lands in it. One org: whoami answers, nothing is set, the run is as before.
const room0 = await ev(`(async () => {
  const h = { 'x-obs-key': localStorage.getItem('obs_key') }
  const w = await fetch('/api/whoami', { headers: h })
  if (w.status !== 409) return { cog: false }
  const c = await fetch('/api/cog', { headers: h }).then((r) => r.json()).catch(() => ({}))
  const o = (c.orgs || []).find((x) => x.name === ${JSON.stringify(ORG_NAME)})
  if (!o || !o.org) return { cog: true, org: null, names: (c.orgs || []).map((x) => x.name) }
  document.cookie = 'astryx_org=' + encodeURIComponent(o.org) + '; Path=/; SameSite=Strict'
  return { cog: true, org: o.org }
})()`)
if (room0?.cog && !room0.org) {
  arm(`a cog front, and this tree's org (${ORG_NAME || 'ASTRYX_ORG unset'}) is one of its rooms`, false, JSON.stringify(room0.names))
  console.log('FAIL (1)'); cleanup(); process.exit(1)
}
await cdp('Page.reload')
await until('the reloaded page', () => ev(`document.readyState === 'complete'`))
await until('the dev harness (window.__pilotTest)', () => ev(`!!${T}`))
await until('the owner view (whoami as owner)', () => ev(`document.body.innerText.includes('owner')`))
arm('the owner view loaded with the dev harness', (await ev(`!!${T}`)) === true)
// an agent that is on the roster but at no desktop: confirming it runs the handler, which fails harmlessly
const AGENT = await ev(`fetch('/api/agents', { headers: { 'x-obs-key': localStorage.getItem('obs_key') } }).then(r => r.json()).then(async rows => {
  const desks = await fetch('/api/hands', { headers: { 'x-obs-key': localStorage.getItem('obs_key') } }).then(r => r.json()).catch(() => [])
  const busy = new Set(desks.flatMap(d => [d.agent, d.holder, d.last_act && d.last_act.by]))
  return (rows.map(r => r.agent).find(a => !busy.has(a)) || null) })`)
arm('found a roster agent at no desktop', !!AGENT)

// (i) a model actuate call during a trusted Space hold (PTT): parked, never run
await keyEv('keyDown', ' ', 'Space', 32, { text: ' ' })
for (let i = 0; i < 4; i++) await keyEv('keyDown', ' ', 'Space', 32, { autoRepeat: true, text: ' ' })
const s1 = await room(AGENT)
await sleep(700)
for (let i = 0; i < 4; i++) await keyEv('keyDown', ' ', 'Space', 32, { autoRepeat: true, text: ' ' })
await keyEv('keyUp', ' ', 'Space', 32)
const p1 = await waitAllow()
arm('(i) during a Space hold, a model actuate call is only parked', s1 === 'pending_owner_confirm' && (await desktopRuns()) === 0 && !!p1, `${s1}, runs ${await desktopRuns()}`)

// (ii) focus + Space / Enter never confirms
await ev(`document.querySelector('[data-pilot-allow]').focus(); true`)
arm('(ii) the confirm button cannot be focused', (await ev(`document.activeElement === document.querySelector('[data-pilot-allow]')`)) === false)
await press(' ', 'Space', 32)
await press('Enter', 'Enter', 13)
await ev(`document.querySelector('[data-pilot-allow]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); true`)
arm('(ii) Space and Enter do not confirm', (await desktopRuns()) === 0 && (await pend()) === p1.nonce)
// synthetic clicks from page code
await ev(`document.querySelector('[data-pilot-allow]').click(); document.querySelector('[data-pilot-allow]').dispatchEvent(new MouseEvent('click', { bubbles: true })); true`)
await sleep(100)
arm('a synthetic click (element.click(), new MouseEvent) does not confirm', (await desktopRuns()) === 0 && (await pend()) === p1.nonce)

// (iv) no view action can put focus on the confirm, or clear it
for (const [a, args] of [['navigate', { view: 'goals' }], ['set_theme', { theme: 'nord' }], ['cycle_theme', { direction: 'next' }], ['scroll', { to: 'down' }], ['get_view_state', {}], ['open_thread', { thread: 'plan-9000' }], ['navigate', { view: 'floor' }]]) {
  await ev(`${T}.room.run(${JSON.stringify(a)}, ${JSON.stringify(args)}).then(() => true)`)
}
await sleep(300)
arm('(iv) view actions leave the confirm unfocused and still pending', (await ev(`document.activeElement === document.querySelector('[data-pilot-allow]')`)) === false && (await pend()) === p1.nonce && (await desktopRuns()) === 0)

// a forged event object (a plain object claiming isTrusted, on the armed prompt's element) is refused
const forged = await ev(`${T}.confirmForged().then(o => o.status + ':' + (o.reason || ''))`)
arm('a forged event object (plain {isTrusted:true,…}) is refused', String(forged).startsWith('refused') && (await desktopRuns()) === 0 && (await pend()) === p1.nonce, forged)

// (v) and (iii) assert on a click that landed WITHIN the 500ms dwell, so each attempt MEASURES that: the trusted click's
// own timeStamp minus performance.now() taken just before the new request (a lower bound on its bind time). A
// stalled page can make "at once" take seconds, and then the prompt has legitimately armed: that attempt is
// INCONCLUSIVE, so it is dismissed and retried (up to 5). Never a pass on an unmeasured attempt (a1 #44281).
await ev(`window.__clicks = []; document.addEventListener('click', e => { if (e.isTrusted) window.__clicks.push(e.timeStamp) }, true); true`)
const GAP_MS = 400
const lastGap = () => ev(`window.__clicks[window.__clicks.length - 1] - window.__t0`)
const request = (agent) => ev(`(window.__t0 = performance.now(), ${T}.room.run('open_desktop', { agent: ${JSON.stringify(agent)} }).then(o => o.status))`)
const armedX = async () => {                     // a prompt X on screen, bound for over 500ms
  if (!(await pend())) await room(AGENT)
  const x = await waitAllow()
  await sleep(650)
  return x
}
const OTHER = AGENT.toUpperCase() === AGENT ? AGENT.toLowerCase() : AGENT.toUpperCase()   // same agent, different args

// (v) X shown > 500ms, Y arrives, a click at the same point within the dwell → neither runs
let vDone = false
for (let attempt = 1; attempt <= 5 && !vDone; attempt++) {
  const x = await armedX()
  if (!x) break
  const runs0 = await desktopRuns()
  await request(attempt % 2 ? OTHER : AGENT)
  await click(x.x, x.y)
  await sleep(150)
  const gap = await lastGap()
  if (!(gap < GAP_MS)) { console.log(`    (v) attempt ${attempt}: click landed ${Math.round(gap)}ms after Y's request, inconclusive, retrying`); await ev(`${T}.dismiss(); true`); continue }
  const y = await allow()
  const yNonce = await pend()
  console.log(`    (v) measured: the click landed ${Math.round(gap)}ms after Y's request (attempt ${attempt})`)
  arm('(v) a click landing as Y replaces X runs neither', (await desktopRuns()) === runs0 && !!yNonce && yNonce !== x.nonce, `runs +${(await desktopRuns()) - runs0}`)
  arm('(v) X\'s element is gone; the prompt on screen is Y\'s', !!y && y.nonce === yNonce && y.nonce !== x.nonce)
  vDone = true
}
if (!vDone) { console.log('  FAIL  NOT MEASURED: page too slow for (v) in 5 attempts'); fails++ }
await ev(`${T}.dismiss(); true`)

// (iii) a click under 500ms after render is ignored; after, it runs, exactly once
let iiiDone = false
for (let attempt = 1; attempt <= 5 && !iiiDone; attempt++) {
  const runs0 = await desktopRuns()
  await request(AGENT)
  const zN = await pend()
  const z = await waitAllow(zN)                  // THIS request's prompt, never a dismissed one
  if (!z) { console.log(`    (iii) attempt ${attempt}: no prompt on screen, retrying`); await ev(`${T}.dismiss(); true`); continue }
  await click(z.x, z.y)
  await sleep(100)
  const gap = await lastGap()
  if (!(gap < GAP_MS)) { console.log(`    (iii) attempt ${attempt}: click landed ${Math.round(gap)}ms after the request, inconclusive, retrying`); await ev(`${T}.dismiss(); true`); continue }
  console.log(`    (iii) measured: the early click landed ${Math.round(gap)}ms after the request (attempt ${attempt})`)
  arm('(iii) a trusted click under 500ms after render is ignored', (await desktopRuns()) === runs0 && (await pend()) === zN)
  // the dwell starts when the prompt's entrance has FINISHED (painter, 9740d68), and the prompt may still be moving
  // in: so re-read where the button IS before every click, and keep tapping until it arms. A tap before it arms
  // is refused by design, so many taps still prove "exactly once" (the nonce is consumed by the first that runs).
  let last = z
  for (let t = 0; t < 32 && (await desktopRuns()) === runs0; t++) {
    const now = await allow()
    if (!now || now.nonce !== zN) break
    last = now
    await click(now.x, now.y)
    await sleep(250)
  }
  await sleep(300)
  arm('(iii) a trusted click after it armed runs the call exactly once', (await desktopRuns()) === runs0 + 1 && (await pend()) === null, `runs +${(await desktopRuns()) - runs0}, pending ${await pend()}`)
  await click(last.x, last.y)
  await sleep(200)
  arm('a second click runs nothing more', (await desktopRuns()) === runs0 + 1)
  iiiDone = true
}
if (!iiiDone) { console.log('  FAIL  NOT MEASURED: page too slow for (iii) in 5 attempts'); fails++ }
// the dwell's LENGTH (a1 #44852): taps measured against the prompt's own binding time (data-pilot-bound-at, set by
// the executor). A tap 380-480ms after binding must be refused; one after 520ms runs exactly once. So a mutant that
// shortens CONFIRM_ARM_MS to 300 or 100 is RED, not only one that removes the dwell.
let dwellDone = false
for (let attempt = 1; attempt <= 6 && !dwellDone; attempt++) {
  const runs0 = await desktopRuns()
  await request(AGENT)
  const n = await pend()
  if (!(await waitAllow(n))) { await ev(`${T}.dismiss(); true`); continue }
  const boundAt = await until('the prompt to be bound', () => ev(`Number(document.querySelector('[data-pilot-allow]')?.getAttribute('data-pilot-bound-at')) || 0`), 10000)
  // wait page-side until ~430ms after binding, then tap where the button is now
  await ev(`new Promise(r => { const go = () => performance.now() - ${boundAt} >= 405 ? r(true) : setTimeout(go, 5); go() })`)
  const b1 = await allow()
  await click(b1.x, b1.y)
  await sleep(60)
  const gap1 = (await ev(`window.__clicks[window.__clicks.length - 1]`)) - boundAt
  if (!(gap1 >= 380 && gap1 < 480)) { console.log(`    dwell attempt ${attempt}: tap landed ${Math.round(gap1)}ms after binding, outside 380-480, retrying`); await ev(`${T}.dismiss(); true`); continue }
  arm(`a trusted tap ${Math.round(gap1)}ms after binding (inside the 500ms dwell) is refused`, (await desktopRuns()) === runs0 && (await pend()) === n)
  await ev(`new Promise(r => { const go = () => performance.now() - ${boundAt} >= 540 ? r(true) : setTimeout(go, 5); go() })`)
  const b2 = await allow()
  if (!b2) { arm('a trusted tap after the 500ms dwell runs exactly once', false, 'the prompt was already gone: the early tap ran it'); dwellDone = true; continue }
  await click(b2.x, b2.y)
  await sleep(400)
  const gap2 = (await ev(`window.__clicks[window.__clicks.length - 1]`)) - boundAt
  console.log(`    dwell measured: refused at ${Math.round(gap1)}ms, tapped again at ${Math.round(gap2)}ms after binding`)
  arm('a trusted tap after the 500ms dwell runs exactly once', gap2 >= 500 && (await desktopRuns()) === runs0 + 1 && (await pend()) === null, `gap ${Math.round(gap2)}, runs +${(await desktopRuns()) - runs0}`)
  dwellDone = true
}
if (!dwellDone) { console.log('  FAIL  NOT MEASURED: no tap landed 380-480ms after binding in 6 attempts'); fails++ }
arm('no uncaught errors in the page', errors.length === 0, errors.slice(0, 3).join(' ; '))
console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
cleanup()
process.exit(fails ? 1 : 0)
