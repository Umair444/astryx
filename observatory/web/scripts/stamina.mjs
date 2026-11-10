/* STAMINA — the chat workspace left open all day (iteration 14). Re-run after any change to store.tsx, the chat
   data layer or the thread view. It never writes to the wire: everything it adds is a CLIENT-SIDE fixture (Playwright
   route interception), and the dev API it targets refuses wire writes anyway (ASTRYX_DEV_NO_WIRE).

   HOW TO RUN (against the GUARDED dev API, which serves the production build of this tree):
     cd observatory/web && npm run build && /home/astryx/astryx-ws/.devlogs/dev.sh restart-api
     OBS_KEY=$(grep '^OBS_KEY=' /opt/astryx/.env | cut -d= -f2-) \
       PLAYWRIGHT_CORE=<dir>/node_modules/playwright-core/index.mjs CHROMIUM=~/.local/bin/chromium \
       node scripts/stamina.mjs all --base http://127.0.0.1:8092 [--out results.json] [--minutes 20]
   Modes: offline (network drop 30–120 s, then backfill), restart (API down/up; needs --dev-sh <path to dev.sh>),
          hidden (tab hidden for "hours"), dedupe (SSE + refetch overlap, out-of-order), long (a 3,000-message thread:
          open time, long tasks while scrolling, typing latency, heap), soak (--minutes of live stream + thread
          switching, heap/nodes/listeners sampled each minute), deploy (a rebuilt bundle under an open tab),
          all (every mode but soak + restart).
   Exit code 0 = every check passed. The owner key is read from OBS_KEY and NEVER printed: every URL that is logged
   has its key= masked. */
const PW = process.env.PLAYWRIGHT_CORE || 'playwright-core'
const { chromium } = await import(PW)
import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'

const argv = process.argv.slice(2)
const mode = argv[0] || 'all'
const opt = (k, d) => { const i = argv.indexOf(`--${k}`); return i >= 0 ? argv[i + 1] : d }
const BASE = opt('base', 'http://127.0.0.1:8092')
const OUT = opt('out', '')
const MINUTES = +opt('minutes', '20')
const DEVSH = opt('dev-sh', '')
const KEY = process.env.OBS_KEY || ''
if (!KEY) { console.error('OBS_KEY is required (the owner key; it is never printed)'); process.exit(2) }
const mask = (s) => String(s).replace(/key=[^&\s"]+/g, 'key=…').split(KEY).join('…')
const log = (...a) => console.log(...a.map(mask))
const results = {}
const checks = []
const check = (name, ok, detail = '') => { checks.push({ name, ok: !!ok, detail: mask(detail) }); log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function open(url, { viewport = { width: 1440, height: 900 } } = {}) {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || process.env.HOME + '/.local/bin/chromium', args: ['--no-sandbox', '--enable-precise-memory-info'] })
  const ctx = await b.newContext({ viewport })
  await ctx.addInitScript((k) => { try { localStorage.setItem('obs_key', k) } catch { /* */ } }, KEY)
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', (e) => errors.push(mask(e.message).slice(0, 200)))
  const cdp = await ctx.newCDPSession(p)
  await cdp.send('Network.enable'); await cdp.send('Performance.enable')
  const sse = { opened: 0, events: 0, pings: 0 }
  cdp.on('Network.requestWillBeSent', (e) => { if (e.request.url.includes('/api/events')) sse.opened++ })
  cdp.on('Network.eventSourceMessageReceived', (e) => { if (e.eventName === 'ping') sse.pings++; else sse.events++ })
  if (url) await p.goto(url, { waitUntil: 'domcontentloaded' })
  return { b, ctx, p, cdp, errors, sse }
}
async function metrics(cdp, gc = true) {
  if (gc) { await cdp.send('HeapProfiler.collectGarbage').catch(() => {}); await sleep(300) }
  const m = Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((x) => [x.name, x.value]))
  return { heapMB: +(m.JSHeapUsedSize / 1048576).toFixed(2), nodes: m.Nodes, listeners: m.JSEventListeners, script: m.ScriptDuration, layout: m.LayoutDuration, tasks: m.TaskDuration }
}
const apiGet = async (path) => {
  const r = await fetch(BASE + '/api' + path, { headers: { 'x-obs-key': KEY } })
  if (!r.ok) throw new Error(`${path} → ${r.status}`)
  return r.json()
}
/* what the thread view shows: one hidden marker per block that stands for a message (thread/focus.ts) */
const rendered = (p) => p.evaluate(() => [...document.querySelectorAll('[role="log"] [data-msg]')].map((e) => +e.getAttribute('data-msg')))
const connState = (p) => p.evaluate(() => document.querySelector('[data-conn]')?.getAttribute('data-conn') ?? 'none')
/* the ids the view SHOULD mark: every row, minus the owner's fan-out copies Turns folds into one block (same text
   within a minute of the previous owner block) */
function expectedMarks(rows) {
  const out = []; let last = null
  const strip = (b) => b.replace(/\[\[(file|ann):[^\]]*\]\]/g, '').trim()
  for (const m of rows) {
    if (m.from === 'owner' && last && last.from === 'owner' && strip(last.body) === strip(m.body) && Date.parse(m.ts) - Date.parse(last.ts) < 60000) continue
    out.push(m.id); last = m.from === 'owner' ? m : null
  }
  return out
}
async function waitFor(fn, ms = 15000, every = 250) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) { try { if (await fn()) return Date.now() - t0 } catch { /* */ } await sleep(every) }
  return -1
}

/* typing latency: keydown → the next painted frame, 40 characters into the composer (the box keeps its own state) */
async function typingLatency(p) {
  const box = p.locator('textarea').last()
  await box.click()
  const r = await p.evaluate(async () => {
    const ta = [...document.querySelectorAll('textarea')].at(-1)
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set
    const lat = []
    for (const ch of 'the estate is steady today, show me more'.split('')) {
      const t = performance.now()
      ta.dispatchEvent(new KeyboardEvent('keydown', { key: ch, bubbles: true }))
      setter.call(ta, ta.value + ch); ta.dispatchEvent(new Event('input', { bubbles: true }))
      await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)))
      lat.push(performance.now() - t)
    }
    lat.sort((a, b) => a - b)
    return { p50: +lat[lat.length >> 1].toFixed(1), p95: +lat[Math.floor(lat.length * 0.95)].toFixed(1), max: +lat.at(-1).toFixed(1) }
  })
  await box.fill('')
  return r
}

/* ------------------------------------------------------------------ fixtures: a synthetic thread nobody else sees */
const FIX0 = 900_000_000
function fixtureRows(thread, n, start = FIX0) {
  const t0 = Date.now() - n * 60_000
  return Array.from({ length: n }, (_, i) => {
    const owner = i % 3 === 0
    return {
      id: start + i, ts: new Date(t0 + i * 60_000).toISOString(), from: owner ? 'owner' : 'seed', from_org: null, to: owner ? 'seed' : 'owner', to_org: null,
      thread, intent: 'chat', status: 'read', turn_id: null,
      body: owner ? `Question ${i}: how is the estate today?` : `Answer ${i}. The **estate** is steady.\n\n- point one ${i}\n- point two\n\n| a | b |\n|---|---|\n| ${i} | ${i * 2} |`,
    }
  })
}
/* serve GET /api/messages for `thread` (and the global feed's after_id backfill) from an in-memory table */
async function routeFixture(ctx, table) {
  await ctx.route((u) => u.pathname === '/api/messages', async (route) => {
    const req = route.request()
    if (req.method() !== 'GET') return route.abort()          // the fixture never writes
    const u = new URL(req.url())
    const thread = u.searchParams.get('thread'), after = +(u.searchParams.get('after_id') || 0), before = +(u.searchParams.get('before_id') || 0)
    const limit = Math.min(+(u.searchParams.get('limit') || 100), 500)
    if (thread && table.threads[thread]) {
      let rows = table.threads[thread].filter((m) => (!after || m.id > after) && (!before || m.id < before))
      rows = after ? rows.slice(0, limit) : rows.slice(-limit)
      table.hits.push({ thread, after, before, n: rows.length })
      return route.fulfill({ json: rows })
    }
    if (!thread && after && after >= FIX0 - 1) {            // the global backfill past the fixture ids
      const all = Object.values(table.threads).flat().filter((m) => m.id > after && m.live).sort((a, b) => a.id - b.id).slice(0, limit)
      table.hits.push({ global: true, after, n: all.length })
      return route.fulfill({ json: all })
    }
    return route.continue()
  })
}

/* ------------------------------------------------------------------ 1. offline: a laptop that sleeps / loses wifi */
async function offline(secs = [30, 120]) {
  const thread = 'chat:stamina-offline'
  const table = { threads: { [thread]: fixtureRows(thread, 12) }, hits: [] }
  const s = await open(null)
  await routeFixture(s.ctx, table)
  await s.p.goto(`${BASE}/#/chat/${encodeURIComponent(thread)}`, { waitUntil: 'domcontentloaded' })
  await waitFor(async () => (await rendered(s.p)).length >= 8)
  await waitFor(async () => s.sse.opened > 0)
  for (const sec of secs) {
    const opened = s.sse.opened
    await s.cdp.send('Network.emulateNetworkConditions', { offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1 })
    // while away, two rows land on the open thread (as the org would write them)
    const tab = table.threads[thread]; const last = tab.at(-1).id
    const add = fixtureRows(thread, 2, last + 1).map((m) => ({ ...m, live: true, ts: new Date().toISOString() }))
    tab.push(...add)
    const shownOff = await waitFor(async () => /reconnect|offline/i.test(await connState(s.p)), 20000)
    await sleep(sec * 1000)
    const frozen = await s.p.evaluate(() => !!document.querySelector('[role="log"]'))
    await s.cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 })
    const t0 = Date.now()
    const back = await waitFor(async () => (await rendered(s.p)).includes(add[1].id), 45000)
    const ids = await rendered(s.p)
    const want = expectedMarks(tab)
    check(`offline ${sec}s: the stream reconnected`, s.sse.opened > opened, `opens ${opened}→${s.sse.opened}`)
    check(`offline ${sec}s: said so while away`, shownOff >= 0, `state=${await connState(s.p)}`)
    check(`offline ${sec}s: the view stayed up`, frozen && s.errors.length === 0, s.errors.join(' | '))
    check(`offline ${sec}s: backfilled the rows that arrived while away`, back >= 0, `${back >= 0 ? back + ' ms after coming back' : 'missing ' + add.map((m) => m.id)}`)
    check(`offline ${sec}s: thread == server (no gap, no dupes)`, JSON.stringify(ids) === JSON.stringify(want), `rendered ${ids.length} vs ${want.length}`)
    const calm = await waitFor(async () => /live|back/.test(await connState(s.p)), 15000)
    check(`offline ${sec}s: "Back" then calm`, calm >= 0, `state=${await connState(s.p)} after ${Date.now() - t0} ms`)
    results[`offline_${sec}`] = { reconnectMs: back, opens: s.sse.opened }
  }
  await s.b.close()
}

/* ------------------------------------------------------------------ 2. the API itself restarts (dev.sh) */
async function restart(downSecs = 30) {
  if (!DEVSH) { log('restart: skipped (pass --dev-sh <path to dev.sh>)'); return }
  const threads = (await apiGet('/ws/threads')).threads
  const thread = threads.sort((a, b) => b.count - a.count)[0].thread
  const s = await open(`${BASE}/#/chat/${encodeURIComponent(thread)}`)
  await waitFor(async () => (await rendered(s.p)).length > 0)
  const opened = s.sse.opened
  execFileSync(DEVSH, ['stop-api'], { stdio: 'ignore' })
  const said = await waitFor(async () => /reconnect|offline/i.test(await connState(s.p)), 90000)   // behind a proxy: the watchdog (60 s)
  await sleep(downSecs * 1000)
  execFileSync(DEVSH, ['start-api'], { stdio: 'ignore' })
  const t0 = Date.now()
  const back = await waitFor(async () => /live|back/.test(await connState(s.p)) && s.sse.opened > opened, 90000)
  await sleep(2500)
  const ids = await rendered(s.p)
  const want = expectedMarks(await apiGet(`/messages?thread=${encodeURIComponent(thread)}&limit=500`)).slice(-ids.length)
  check('restart: said "Reconnecting" while the API was down', said >= 0)
  check('restart: reconnected after the API came back', back >= 0, `${Date.now() - t0} ms, opens ${opened}→${s.sse.opened}`)
  check('restart: thread == server', JSON.stringify(ids) === JSON.stringify(want), `rendered ${ids.length}`)
  check('restart: no page errors', s.errors.length === 0, s.errors.join(' | '))
  results.restart = { reconnectMs: back, opens: s.sse.opened }
  await s.b.close()
}

/* ------------------------------------------------------------------ 3. hidden for hours, then back */
async function hidden() {
  const thread = 'chat:stamina-hidden'
  const table = { threads: { [thread]: fixtureRows(thread, 6) }, hits: [] }
  const s = await open(null)
  await routeFixture(s.ctx, table)
  await s.p.goto(`${BASE}/#/chat/${encodeURIComponent(thread)}`, { waitUntil: 'domcontentloaded' })
  await waitFor(async () => (await rendered(s.p)).length >= 4)
  // "hours": the tab goes hidden, its stream stays silent long enough that it can't be trusted (simulated by cutting
  // the network quietly, the way a sleeping laptop's socket half-dies), a row lands, the tab comes back
  await s.p.evaluate(() => { Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' }); Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange')) })
  const tab = table.threads[thread]
  const add = fixtureRows(thread, 1, tab.at(-1).id + 1).map((m) => ({ ...m, live: true, ts: new Date().toISOString() }))
  tab.push(...add)
  await sleep(35000)                                      // longer than the store's "long hide" (30 s)
  const hits = table.hits.length
  await s.p.evaluate(() => { Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' }); Object.defineProperty(document, 'hidden', { configurable: true, get: () => false }); document.dispatchEvent(new Event('visibilitychange')) })
  const back = await waitFor(async () => (await rendered(s.p)).includes(add[0].id), 15000)
  check('hidden: coming back resyncs (the row written while hidden shows)', back >= 0, `${back} ms, fixture fetches ${hits}→${table.hits.length}`)
  check('hidden: no page errors', s.errors.length === 0, s.errors.join(' | '))
  await s.b.close()
}

/* ------------------------------------------------------------------ 4. duplicates + ordering */
async function dedupe() {
  const thread = 'chat:stamina-dedupe'
  const rows = fixtureRows(thread, 10)
  // the server answers OUT OF ORDER and with a repeated row; a backfill overlaps the history
  const table = { threads: { [thread]: [...rows] }, hits: [] }
  const s = await open(null)
  await s.ctx.route((u) => u.pathname === '/api/messages', async (route) => {
    const u = new URL(route.request().url())
    if (route.request().method() !== 'GET') return route.abort()
    if (u.searchParams.get('thread') === thread) {
      const shuffled = [rows[3], rows[0], rows[1], rows[1], rows[2], ...rows.slice(4).reverse()]
      return route.fulfill({ json: shuffled })
    }
    return route.continue()
  })
  await s.p.goto(`${BASE}/#/chat/${encodeURIComponent(thread)}`, { waitUntil: 'domcontentloaded' })
  await waitFor(async () => (await rendered(s.p)).length >= 6)
  // the same rows again through every refetch path the app has: a resync (as after a reconnect) and a thread revisit
  await s.p.evaluate(() => window.dispatchEvent(new Event('online')))
  await sleep(1500)
  await s.p.goto(`${BASE}/#/chat/library`); await sleep(800)
  await s.p.goto(`${BASE}/#/chat/${encodeURIComponent(thread)}`); await sleep(1500)
  const ids = await rendered(s.p)
  const want = expectedMarks(rows)
  check('dedupe: no message renders twice', new Set(ids).size === ids.length, `${ids.length} marks, ${new Set(ids).size} distinct`)
  check('dedupe: sorted by id', ids.every((x, i) => !i || ids[i - 1] < x))
  check('dedupe: thread == fixture', JSON.stringify(ids) === JSON.stringify(want), `${ids.length} vs ${want.length}`)
  await s.b.close()
}

/* ------------------------------------------------------------------ 5. a 3,000-message thread */
async function long(n = 3000) {
  const thread = 'chat:stamina-long'
  const table = { threads: { [thread]: fixtureRows(thread, n) }, hits: [] }
  const s = await open(null)
  await routeFixture(s.ctx, table)
  await s.p.goto(`${BASE}/#/chat/library`, { waitUntil: 'domcontentloaded' })
  await sleep(2500)
  const m0 = await metrics(s.cdp)
  await s.p.evaluate(() => {
    window.__lt = []
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lt.push(e.duration) }).observe({ type: 'longtask', buffered: false })
  })
  const t0 = Date.now()
  await s.p.evaluate((t) => { location.hash = `#/chat/${encodeURIComponent(t)}` }, thread)
  const openMs = await waitFor(async () => (await rendered(s.p)).length >= 60, 30000, 20)
  const ltOpen = await s.p.evaluate(() => { const x = window.__lt; window.__lt = []; return x })
  await sleep(1000)
  const typing = await typingLatency(s.p)                 // as the owner meets it: the newest window on screen
  // idle cost: 30 s with the live stream flowing and this thread open (each event re-renders only what it touches)
  const a = await metrics(s.cdp, false); const ev0 = s.sse.events
  await sleep(30000)
  const z = await metrics(s.cdp, false)
  const idle = { events: s.sse.events - ev0, scriptMs: Math.round((z.script - a.script) * 1000), scriptMsPerEvent: +(((z.script - a.script) * 1000) / Math.max(1, s.sse.events - ev0)).toFixed(1) }
  // scroll the whole loaded history: "Show earlier" until there is none, then top → bottom in steps
  let clicks = 0
  while (clicks < 60) {
    const btn = s.p.locator('button.ws-earlier').first()
    if (!(await btn.count())) break
    await btn.click(); clicks++; await sleep(120)
  }
  const shownAll = (await rendered(s.p)).length
  const sc = await s.p.evaluate(async () => {
    const el = document.querySelector('[role="log"]')?.parentElement?.parentElement
    if (!el) return { frames: 0 }
    el.scrollTop = 0; await new Promise((r) => setTimeout(r, 200))
    window.__lt = []
    const frames = []; let last = performance.now()
    const steps = 60, h = el.scrollHeight
    for (let i = 0; i <= steps; i++) {
      el.scrollTop = (h * i) / steps
      await new Promise((r) => requestAnimationFrame(() => r()))
      const t = performance.now(); frames.push(t - last); last = t
    }
    frames.sort((a, b) => a - b)
    return { frames: frames.length, p50: +frames[frames.length >> 1].toFixed(1), p95: +frames[Math.floor(frames.length * 0.95)].toFixed(1), max: +frames.at(-1).toFixed(1), longtasks: window.__lt.length }
  })
  const typingAll = await typingLatency(s.p)             // and with EVERY row of the thread opened
  const m1 = await metrics(s.cdp)
  const older = table.hits.filter((h) => h.thread === thread && h.before).length
  results.long = { n, openMs, longtasksOpen: ltOpen.length, longestOpenTaskMs: Math.round(Math.max(0, ...ltOpen)), shownAfterEarlier: shownAll, earlierClicks: clicks, olderPagesFetched: older, scroll: sc, typing, typingAll, idle, heapBeforeMB: m0.heapMB, heapAfterMB: m1.heapMB, nodes: m1.nodes }
  log('long:', JSON.stringify(results.long))
  check('long: opens under 1.5 s', openMs >= 0 && openMs < 1500, `${openMs} ms`)
  check('long: the whole thread is reachable (older pages load)', shownAll >= n * 0.95, `${shownAll} of ${n} reachable`)
  check('long: typing p95 under 50 ms', typing.p95 < 50, `p95 ${typing.p95} ms`)
  check('long: scrolling p95 frame under 50 ms', sc.p95 < 50, `p95 ${sc.p95} ms, ${sc.longtasks} long tasks`)
  check('long: no page errors', s.errors.length === 0, s.errors.join(' | '))
  await s.b.close()
}

/* ------------------------------------------------------------------ 5b. a deploy while the tab is open */
async function deploy() {
  // the build changed under an open tab: the next lazy view's old chunk is gone (404 once); the tab loads the new build
  const s = await open(`${BASE}/#/chat`)
  await sleep(4000)
  let gone = 0
  await s.ctx.route((u) => /\/assets\/Library-[^/]+\.js$/.test(u.pathname), (r) => (gone++ ? r.continue() : r.fulfill({ status: 404, body: '' })))
  let loads = 0
  s.p.on('load', () => loads++)
  await s.p.evaluate(() => { location.hash = '#/chat/library' })
  const ok = await waitFor(async () => (await s.p.evaluate(() => !!document.querySelector('input[aria-label="search files"]'))), 20000)
  check('deploy: a missing chunk reloads into the new build (no dead page)', ok >= 0 && s.errors.length === 0, `reloads ${loads}, chunk asks ${gone}${s.errors.length ? ', ' + s.errors.join(' | ') : ''}`)
  await s.b.close()
}

/* ------------------------------------------------------------------ 6. soak: minutes of live stream + switching */
async function soak(minutes = MINUTES) {
  const threads = (await apiGet('/ws/threads')).threads.map((t) => t.thread)
  const pdfThread = 'cv:0b7661abb9'
  const routes = [...threads.map((t) => `chat/${encodeURIComponent(t)}`), 'chat/library', 'chat/projects', 'chat', 'floor']
  const s = await open(`${BASE}/#/chat`)
  await sleep(5000)
  // the first sample after one full lap of the views: lazy chunks, fonts and caches are warm by then
  const samples = [{ min: 0, ...(await metrics(s.cdp)), events: 0 }]
  log('soak t=0', JSON.stringify(samples[0]))
  const t0 = Date.now(); let i = 0, nextSample = 60_000
  while (Date.now() - t0 < minutes * 60_000) {
    const r = routes[i++ % routes.length]
    await s.p.evaluate((h) => { location.hash = `#/${h}` }, r)
    await sleep(4000)
    if (i % 6 === 0 && threads.includes(pdfThread)) {      // a file opens in the panel (pdf.js, images) and closes again
      await s.p.evaluate((h) => { location.hash = `#/chat/${encodeURIComponent(h)}` }, pdfThread); await sleep(2500)
      const chip = s.p.locator('.ws-chip').first()
      if (await chip.count()) { await chip.click().catch(() => {}); await sleep(3500); await s.p.locator('[aria-label="close the panel"]').first().click().catch(() => {}); await sleep(500) }
    }
    await sleep(26000)
    if (Date.now() - t0 >= nextSample) {
      nextSample += 60_000
      // every sample on the SAME view (the workspace home), so a number is comparable with the one before it
      await s.p.evaluate(() => { location.hash = '#/chat' }); await sleep(2500)
      const m = { min: Math.round((Date.now() - t0) / 60000), ...(await metrics(s.cdp)), events: s.sse.events }
      samples.push(m); log('soak', JSON.stringify(m))
    }
  }
  const first = samples[1] ?? samples[0], last = samples.at(-1)
  const tail = samples.slice(Math.floor(samples.length / 2))
  const slope = tail.length > 1 ? (tail.at(-1).heapMB - tail[0].heapMB) / Math.max(1, tail.at(-1).min - tail[0].min) : 0
  results.soak = { minutes, samples, heapGrowthMB: +(last.heapMB - first.heapMB).toFixed(2), secondHalfMBPerMin: +slope.toFixed(3), nodesGrowth: last.nodes - first.nodes, listenerGrowth: last.listeners - first.listeners, events: s.sse.events, errors: s.errors }
  log('soak:', JSON.stringify({ ...results.soak, samples: undefined }))
  check('soak: second-half heap slope under 0.15 MB/min', slope < 0.15, `${slope.toFixed(3)} MB/min`)
  // a lazy view registers its listeners once (a step, then flat); a leak climbs. Judged on the second half, so the
  // first visit to each view is not counted. The residual heap creep (~0.1 MB/min) diffed by constructor is V8's JIT
  // code and DevTools' own Network buffers (this harness enables CDP Network), not app objects.
  check('soak: listeners do not climb (second half)', tail.at(-1).listeners - tail[0].listeners < 50, `${first.listeners}→${last.listeners}, second half ${tail[0].listeners}→${tail.at(-1).listeners}`)
  check('soak: DOM nodes do not climb (nothing detached is kept)', last.nodes - first.nodes < 500, `${first.nodes}→${last.nodes}`)
  check('soak: no page errors', s.errors.length === 0, s.errors.join(' | '))
  await s.b.close()
}

const plan = { offline: [offline], restart: [restart], hidden: [hidden], dedupe: [dedupe], long: [long], soak: [soak], deploy: [deploy], all: [dedupe, deploy, hidden, offline, long] }[mode]
if (!plan) { console.error(`unknown mode ${mode}`); process.exit(2) }
for (const f of plan) {
  try { await f() } catch (e) { check(`${f.name}: ran to the end`, false, e.message) }
}
if (OUT) writeFileSync(OUT, JSON.stringify({ mode, at: new Date().toISOString(), results, checks }, null, 2))
const bad = checks.filter((c) => !c.ok)
log(`\n${checks.length - bad.length}/${checks.length} checks passed`)
process.exit(bad.length ? 1 : 0)
