// Hand-run: the Room's speaking path end to end on a dev server (spends one short TTS).
import { spawn } from 'node:child_process'
import { readFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const REPO = join(dirname(fileURLToPath(import.meta.url)), '..')
const KEY = (readFileSync(join(REPO, '.env'), 'utf8').split('\n').find((l) => l.startsWith('OBS_KEY=')) || '').slice(8).trim()
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const kids = []; const done = (c) => { kids.forEach((k) => { try { k.kill('SIGKILL') } catch {} }); process.exit(c) }
setTimeout(() => { console.log('FAIL wall clock'); done(1) }, 240000)
async function until(what, f, ms = 60000) { const e = Date.now() + ms; for (;;) { try { const v = await f(); if (v) return v } catch {} if (Date.now() > e) { console.log('FAIL waiting for ' + what); done(1) } await sleep(300) } }
kids.push(spawn('/home/umair/astryx/venv/bin/uvicorn', ['main:app', '--host', '127.0.0.1', '--port', '8195'], { cwd: join(REPO, 'observatory/api'), stdio: 'ignore' }))
await until('api', async () => (await fetch('http://127.0.0.1:8195/api/overview')).ok)
kids.push(spawn(join(REPO, 'observatory/web/node_modules/.bin/vite'), ['--port', '5195', '--strictPort', '--host', '127.0.0.1'], { cwd: join(REPO, 'observatory/web'), stdio: 'ignore', env: { ...process.env, OBS_API: 'http://127.0.0.1:8195' } }))
await until('vite', async () => (await fetch('http://127.0.0.1:5195/src/main.tsx')).ok)
kids.push(spawn('/usr/bin/chromium', ['--headless=new', '--remote-debugging-port=9396', `--user-data-dir=${mkdtempSync(join(tmpdir(), 'room-'))}`, '--autoplay-policy=no-user-gesture-required', 'about:blank'], { stdio: 'ignore' }))
const p = await until('chromium', async () => (await (await fetch('http://127.0.0.1:9396/json/list')).json()).find((t) => t.type === 'page'))
const ws = new WebSocket(p.webSocketDebuggerUrl); await new Promise((r) => ws.addEventListener('open', r))
let id = 0; const w = new Map(); ws.addEventListener('message', (m) => { const d = JSON.parse(m.data); if (d.id && w.has(d.id)) { w.get(d.id)(d); w.delete(d.id) } })
const cdp = (method, params = {}) => new Promise((r) => { const i = ++id; w.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
const ev = async (e) => (await cdp('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })).result?.result?.value
await cdp('Page.navigate', { url: 'http://127.0.0.1:5195/' }); await until('load', () => ev(`document.readyState==='complete'`))
await ev(`localStorage.setItem('obs_key', ${JSON.stringify(KEY)}); true`); await cdp('Page.reload')
await until('owner view', () => ev(`document.body.innerText.includes('owner')`))
await sleep(3000)
// an agent's reply to the room, as send(to='room') writes it
const { execFileSync } = await import('node:child_process')
const dsn = (readFileSync(join(REPO, '.env'), 'utf8').split('\n').find((l) => l.startsWith('ASTRYX_DSN=')) || '').slice(11).trim()
const t0 = Date.now()
const mid = execFileSync('psql', [dsn, '-Atc', "INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES ('seed','room','room:observatory','chat','Hi Umair, seed here. The room speaks now.') RETURNING id"]).toString().trim().split('\n')[0]
console.log('inserted room message', mid)
const cap = await until('the caption on the stage', () => ev(`document.body.innerText.includes('The room speaks now') ? 'shown' : ''`), 30000)
console.log(`caption ${cap} in ${Date.now() - t0}ms`)
const st = execFileSync('psql', [dsn, '-Atc', `SELECT status FROM messages WHERE id=${mid}`]).toString().trim()
console.log('row status:', st)
const audio = await until('the clip to be served', async () => (await fetch(`http://127.0.0.1:8195/api/room/audio/${mid}`, { headers: { 'x-obs-key': KEY } })).ok, 30000)
console.log('audio served:', audio)
// a screen action from an agent
execFileSync('psql', [dsn, '-Atc', `INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES ('seed','room','room:observatory','screen','{"action":"navigate","args":{"view":"goals"}}')`])
await until('the agent screen action to navigate', () => ev(`location.hash === '#/goals'`), 20000)
console.log('screen action: navigated to #/goals')
console.log('ALL PASS'); done(0)
