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
// Exit 77 when chromium, node_modules or the key are absent (a committed-only tree).
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
  console.log(`  NOT RUN: ${!CHROME ? 'no chromium' : !KEY ? 'no OBS_KEY in .env' : 'no observatory/web/node_modules'} (a committed-only tree)`)
  process.exit(77)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const kids = []
const cleanup = () => { for (const k of kids) try { k.kill() } catch {} }
process.on('exit', cleanup)

let URL0 = process.argv[2]
if (!URL0) {
  const vite = spawn(join(WEB, 'node_modules/.bin/vite'), ['--port', '5181', '--strictPort', '--host', '127.0.0.1'], { cwd: WEB, stdio: 'ignore' })
  kids.push(vite)
  URL0 = 'http://127.0.0.1:5181/'
  for (let i = 0; i < 60; i++) { try { if ((await fetch(URL0)).ok) break } catch {} await sleep(250) }
}
const prof = mkdtempSync(join(tmpdir(), 'pilot-cdp-'))
process.on('exit', () => { try { rmSync(prof, { recursive: true, force: true, maxRetries: 5 }) } catch {} })   // chromium may still be writing as it exits
const port = 9334
kids.push(spawn(CHROME, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${prof}`, '--window-size=1280,860', 'about:blank'], { stdio: 'ignore' }))
let ws
for (let i = 0; i < 60 && !ws; i++) {
  try { const p = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === 'page'); if (p) ws = new WebSocket(p.webSocketDebuggerUrl) } catch {}
  if (!ws) await sleep(250)
}
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
await sleep(2500)
await ev(`localStorage.setItem('obs_key', ${JSON.stringify(KEY)}); true`)
await cdp('Page.reload')
for (let i = 0; i < 40; i++) { if (await ev(`!!${T} && document.body.innerText.includes('owner')`)) break; await sleep(250) }
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

// (v) X shown > 500ms, Y arrives, a click at the same point at once → neither runs
const before = await allow()
if (!before) { arm('(v) the prompt from (i) is still on screen', false); console.log(`FAIL (${fails})`); cleanup(); process.exit(1) }
await room(AGENT.toUpperCase() === AGENT ? AGENT.toLowerCase() : AGENT.toUpperCase())   // different args, same agent (names match case-insensitively)
const y = await waitAllow()
await click(before.x, before.y)
await sleep(150)
const yNonce = await pend()
arm('(v) a click landing as Y replaces X runs neither', (await desktopRuns()) === 0 && !!yNonce && yNonce !== p1.nonce, `runs ${await desktopRuns()}`)
arm('(v) X\'s element is gone; the prompt on screen is Y\'s', !!y && y.nonce === yNonce && y.nonce !== before.nonce)

// (iii) a click under 500ms after render is ignored; after, it runs, exactly once
await room(AGENT)
const z = await waitAllow()
const zN = await pend()
await click(z.x, z.y)
await sleep(100)
arm('(iii) a trusted click under 500ms after render is ignored', (await desktopRuns()) === 0 && (await pend()) === zN)
await sleep(650)
await click(z.x, z.y)
await sleep(400)
arm('(iii) a trusted click after it armed runs the call exactly once', (await desktopRuns()) === 1 && (await pend()) === null, `runs ${await desktopRuns()}, pending ${await pend()}`)
await click(z.x, z.y)
await sleep(200)
arm('a second click runs nothing more', (await desktopRuns()) === 1)
arm('no uncaught errors in the page', errors.length === 0, errors.slice(0, 3).join(' ; '))
console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
cleanup()
process.exit(fails ? 1 : 0)
