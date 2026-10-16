#!/usr/bin/env node
// plan-9000 S2, LIVE: one real realtime session end to end, the way the owner uses it. It SPENDS a few voice seconds
// (the shared daily cap, owner-signed), so it is a hand-run proof for a deploy, never part of check.sh.
//
//   node tests/pilot_voice_live.mjs
//
// It starts this tree's observatory API on 127.0.0.1:8193 (the live DB, read-mostly: one usage row per run) and a
// vite dev server pointed at it, opens headless chromium with a fake microphone, taps "Talk" (a trusted click),
// waits for the session to go live, then speaks to the model in TEXT and measures that its tool calls drove the
// screen: "switch the theme to nord" → the theme; "open the goals view" → #/goals; "how much of my token usage is
// left" → a get_usage call answered. Then it hangs up and checks the usage row was reported.
import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..')
const WEB = join(REPO, 'observatory/web')
const KEY = (readFileSync(join(REPO, '.env'), 'utf8').split('\n').find((l) => l.startsWith('OBS_KEY=')) || '').slice(8).trim()
const CHROME = ['/usr/bin/chromium', '/usr/bin/google-chrome-stable'].find(existsSync)
const PY = '/home/umair/astryx/venv/bin/uvicorn'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const kids = []
const cleanup = () => { for (const k of kids) try { k.kill() } catch {} }
process.on('exit', cleanup)
async function until(what, test, ms = 60000) {
  const end = Date.now() + ms
  for (;;) {
    try { const v = await test(); if (v) return v } catch {}
    if (Date.now() > end) { console.log(`  FAIL  timed out after ${ms / 1000}s waiting for ${what}`); console.log('FAIL'); cleanup(); process.exit(1) }
    await sleep(250)
  }
}
kids.push(spawn(PY, ['main:app', '--host', '127.0.0.1', '--port', '8193'], { cwd: join(REPO, 'observatory/api'), stdio: 'ignore' }))
await until('the API on :8193', async () => (await fetch('http://127.0.0.1:8193/api/overview')).ok)
kids.push(spawn(join(WEB, 'node_modules/.bin/vite'), ['--port', '5193', '--strictPort', '--host', '127.0.0.1'], { cwd: WEB, stdio: 'ignore', env: { ...process.env, OBS_API: 'http://127.0.0.1:8193', VITE_CACHE_DIR: process.env.VITE_CACHE_DIR || mkdtempSync(join(tmpdir(), 'voice-live-vite-')) } }))   // plan-10108 D2: its own vite cache
const URL0 = 'http://127.0.0.1:5193/'
await until('vite', async () => (await fetch(URL0)).ok && (await fetch(URL0 + 'src/main.tsx')).ok)
const prof = mkdtempSync(join(tmpdir(), 'pilot-voice-'))
process.on('exit', () => { try { rmSync(prof, { recursive: true, force: true, maxRetries: 5 }) } catch {} })
kids.push(spawn(CHROME, ['--headless=new', '--remote-debugging-port=9393', `--user-data-dir=${prof}`, '--window-size=1280,860',
  '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--autoplay-policy=no-user-gesture-required', 'about:blank'], { stdio: 'ignore' }))
const page = await until('chromium', async () => (await (await fetch('http://127.0.0.1:9393/json/list')).json()).find((t) => t.type === 'page'), 30000)
const ws = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((r) => ws.addEventListener('open', r))
let id = 0
const waits = new Map()
ws.addEventListener('message', (m) => { const d = JSON.parse(m.data); if (d.id && waits.has(d.id)) { waits.get(d.id)(d); waits.delete(d.id) } })
const cdp = (method, params = {}) => new Promise((r) => { const i = ++id; waits.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
const ev = async (expr) => (await cdp('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value
let fails = 0
const arm = (n, ok, d = '') => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${n}${!ok && d !== '' ? '  (' + d + ')' : ''}`); if (!ok) fails++ }

await cdp('Runtime.enable')
await cdp('Page.navigate', { url: URL0 })
await until('the first load', () => ev(`document.readyState === 'complete'`))
await ev(`localStorage.setItem('obs_key', ${JSON.stringify(KEY)}); localStorage.setItem('astryx_theme', 'astryx'); true`)
await cdp('Page.reload')
await until('the owner view', () => ev(`document.readyState === 'complete' && !!window.__pilotVoice && document.body.innerText.includes('owner')`))
// tap Talk: a trusted click, as the owner would
const btn = await until('the Talk button', () => ev(`(() => { const b = document.querySelector('button[aria-label="Talk"]'); if (!b) return null; const r = b.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 } })()`))
const t0 = Date.now()
await cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x: btn.x, y: btn.y, button: 'left', clickCount: 1 })
await cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x: btn.x, y: btn.y, button: 'left', clickCount: 1 })
await until('the session to go live', async () => { const s = await ev('window.__pilotVoice.state()'); if (s?.phase === 'error') throw new Error(s.error); return s?.phase === 'live' }, 30000)
console.log(`    live in ${Date.now() - t0}ms`)
arm('a tap on Talk opens a live realtime session', true)

const ask = async (text, ok, what) => {
  const s0 = Date.now()
  await ev(`window.__pilotVoice.say(${JSON.stringify(text)}); true`)
  const got = await until(what, ok, 30000)
  console.log(`    "${text}" → ${what} in ${Date.now() - s0}ms`)
  return got
}
await ask('switch the theme to nord', () => ev(`localStorage.getItem('astryx_theme') === 'nord'`), 'the theme is nord')
arm('voice: "switch the theme to nord" changes the theme', (await ev(`localStorage.getItem('astryx_theme')`)) === 'nord')
await sleep(1500)
await ask('open the goals view', () => ev(`location.hash === '#/goals'`), 'the goals view')
arm('voice: "open the goals view" navigates', (await ev('location.hash')) === '#/goals')
await sleep(1500)
await ask('how much of my token usage have I used this week?', () => ev(`(window.__pilotVoice.state().said || '').match(/\\d+\\s*(%|percent)/i)`), 'a spoken percentage')
const said = await ev('window.__pilotVoice.state().said')
arm('voice: usage is answered with a percentage', /\d+\s*(%|percent)/i.test(said || ''), said)
console.log(`    it said: "${(said || '').slice(0, 140)}"`)
await ev('window.__pilotVoice.hangup(); true')
await sleep(1500)
arm('hang up returns to idle', (await ev('window.__pilotVoice.state().phase')) === 'idle')
const st = await (await fetch('http://127.0.0.1:8193/api/pilot/voice/status', { headers: { 'x-obs-key': KEY } })).json()
console.log(`    voice minutes today: ${st.minutes_today} of ${st.cap}`)
arm('the session was billed into the shared ledger', st.minutes_today > 0)
console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
cleanup()
process.exit(fails ? 1 : 0)
