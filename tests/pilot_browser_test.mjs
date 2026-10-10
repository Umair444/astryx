#!/usr/bin/env node
// plan-9000 S1, the TRUSTED-input arms (#44094 (i)-(iv), a4 #44113 (v), a1 #44141 R2): the owner-tap confirm in a
// real page, driven over CDP. CDP's Input.dispatchMouseEvent / dispatchKeyEvent produce isTrusted events, which is
// what the gate must tell apart from the model's calls (data-channel function calls, never DOM events).
//
//   node tests/pilot_browser_test.mjs [observatory dev URL]
//
// With no URL it starts a vite dev server from observatory/web on 127.0.0.1:5181 and stops it after. It reads
// OBS_KEY from .env into a throwaway chromium profile (never printed) and talks to the live API read-only. The
// actuate it confirms is open_desktop for an agent with no desktop, so the handler runs and fails harmlessly.
// Absent chromium, node_modules or key: exit 77 on a committed-only tree (no triggers/), but 1, BROKEN, on a LIVE
// host, where this gate is the proof of a prevention-graded cell and must not switch itself off quietly (a1 #44266).
// Every wait is on a condition with a deadline, never on time alone, and names itself when it expires.
import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..')
const CHROME = ['/usr/bin/chromium', '/usr/bin/google-chrome-stable', '/usr/bin/chromium-browser'].find(existsSync)
const WEB = join(REPO, 'observatory/web')
const envPath = join(REPO, '.env')
const KEY = existsSync(envPath) ? (readFileSync(envPath, 'utf8').split('\n').find((l) => l.startsWith('OBS_KEY=')) || '').slice(8).trim() : ''
if (!CHROME || !KEY || !existsSync(join(WEB, 'node_modules/.bin/vite'))) {
  const why = !CHROME ? 'no chromium' : !KEY ? 'no OBS_KEY in .env' : 'no observatory/web/node_modules'
  if (existsSync(join(REPO, 'triggers'))) { console.log(`  BROKEN: ${why} on a live host (triggers/ present)`); process.exit(1) }
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
const cleanup = () => { for (const k of kids) try { k.kill() } catch {} }
process.on('exit', cleanup)

let URL0 = process.argv[2]
if (!URL0) {
  const vite = spawn(join(WEB, 'node_modules/.bin/vite'), ['--port', '5181', '--strictPort', '--host', '127.0.0.1'], { cwd: WEB, stdio: 'ignore' })
  kids.push(vite)
  URL0 = 'http://127.0.0.1:5181/'
}
// vite serves index.html before its first dependency optimization finishes; wait for the app's entry module too
await until('the dev server to answer', async () => (await fetch(URL0)).ok)
await until('the app entry module to compile', async () => (await fetch(new URL('/src/main.tsx', URL0))).ok)
const prof = mkdtempSync(join(tmpdir(), 'pilot-cdp-'))
process.on('exit', () => { try { rmSync(prof, { recursive: true, force: true, maxRetries: 5 }) } catch {} })   // chromium may still be writing as it exits
const port = 9334
kids.push(spawn(CHROME, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${prof}`, '--window-size=1280,860', 'about:blank'], { stdio: 'ignore' }))
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
const cdp = (method, params = {}) => new Promise((r) => { const i = ++id; waits.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
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
arm('no uncaught errors in the page', errors.length === 0, errors.slice(0, 3).join(' ; '))
console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
cleanup()
process.exit(fails ? 1 : 0)
