import { useEffect, useRef, useState } from 'react'
import { ScrollArea, Slider, Textarea } from '@mantine/core'
import { api, apiPost, obsKey } from '../api'
import type { Msg } from '../types'

/* GrowBot — Art of the Problem's open two-servo body (github.com/britcruise9/GrowBot),
   ported to the wire. The reference brain talks to the body over cloud APIs; here the
   body hangs off astryx-growbot.service (:8470, USB-serial Pico) and the BRAIN is the
   org: the ask box writes a row on the wire, the growbot agent choreographs keyframes
   through its MCP hands, and the reply comes back as a message. The buttons/pose levers
   mirror Brit's control page; the conformance runner mirrors protocol/conformance.html. */

type Stats = {
  set_n: number; deadman: number; ws_rx: number; moving: boolean
  act: { active: boolean; queued_ms: number }
  up_s: number
  serial?: boolean // USB body-host extension; Brit's Wi-Fi firmware omits it
}

async function gb(path: string, opts?: { method?: string; json?: unknown }): Promise<{ status: number; text: string; ms: number }> {
  const key = obsKey()
  const t0 = performance.now()
  const r = await fetch('/api/growbot/' + path, {
    method: opts?.method ?? 'GET',
    headers: { ...(key ? { 'x-obs-key': key } : {}), ...(opts?.json !== undefined ? { 'content-type': 'application/json' } : {}) },
    body: opts?.json !== undefined ? JSON.stringify(opts.json) : undefined,
  })
  return { status: r.status, text: await r.text(), ms: performance.now() - t0 }
}

const ROUTINES = ['wiggle', 'dance', 'shimmy', 'march', 'bow', 'stretch']
const THREAD = 'growbot'

/* ---- conformance: the same checks as protocol/conformance.html, over the proxy ---- */
type ConfState = 'PASS' | 'FAIL' | 'WARN' | 'RUN'
type ConfRow = { name: string; ep: string; state: ConfState; detail: string }

const CONF_TAG: Record<ConfState, string> = {
  PASS: 'bg-emerald-400/15 text-emerald-300',
  FAIL: 'bg-red-400/15 text-red-300',
  WARN: 'bg-amber-400/15 text-amber-300',
  RUN: 'bg-deck-3 text-ink-mute',
}

async function runConformance(push: (r: ConfRow) => void): Promise<boolean> {
  let allPass = true
  const check = async (name: string, ep: string, fn: () => Promise<{ state: ConfState; detail: string }>) => {
    let res: { state: ConfState; detail: string }
    try { res = await fn() } catch (e) { res = { state: 'FAIL', detail: String(e) } }
    if (res.state === 'FAIL') allPass = false
    push({ name, ep, ...res })
  }
  await check('reachable + telemetry', 'GET /stats', async () => {
    const r = await gb('stats')
    const j = JSON.parse(r.text)
    if (r.status !== 200 || !j.act) return { state: 'FAIL', detail: `status ${r.status}` }
    return { state: 'PASS', detail: `200 · act=${JSON.stringify(j.act)} serial=${j.serial}` }
  })
  await check('gesture plays, replies instantly', 'POST /act', async () => {
    const steps = [{ l: 120, r: 60, ms: 400 }, { l: 60, r: 120, ms: 400 }, { l: 90, r: 90, ms: 300 }]
    const r = await gb('act', { method: 'POST', json: { steps, mode: 'replace' } })
    const j = JSON.parse(r.text)
    if (r.status !== 200 || j.ok !== 1) return { state: 'FAIL', detail: `expected 200 {ok:1}, got ${r.status} ${r.text.slice(0, 80)}` }
    if (j.queued_ms !== 1100) return { state: 'WARN', detail: `queued_ms=${j.queued_ms}, expected 1100` }
    if (r.ms >= 1100) return { state: 'FAIL', detail: `server BLOCKED ${Math.round(r.ms)}ms for an 1100ms motion` }
    return { state: 'PASS', detail: `200 {ok:1,queued_ms:1100} · replied in ${Math.round(r.ms)}ms` }
  })
  await check('stop is instant + limp', 'GET /stop', async () => {
    const r = await gb('stop')
    if (r.status !== 200) return { state: 'FAIL', detail: `status ${r.status}` }
    return { state: 'PASS', detail: `200 "${r.text.trim()}"` }
  })
  await check('backpressure: oversized plan refused', 'POST /act ×6·3000ms', async () => {
    const r = await gb('act', { method: 'POST', json: { steps: Array(6).fill({ l: 90, r: 90, ms: 3000 }) } })
    if (r.status === 409) return { state: 'PASS', detail: `409 "${r.text.slice(0, 60)}"` }
    return { state: 'FAIL', detail: `expected 409, got ${r.status}` }
  })
  await check('validation: garbage rejected', 'POST /act {steps:"soup"}', async () => {
    const r = await gb('act', { method: 'POST', json: { steps: 'soup' } })
    return r.status === 400 ? { state: 'PASS', detail: '400 as expected' } : { state: 'FAIL', detail: `expected 400, got ${r.status}` }
  })
  await check('canned routine', 'GET /routine?name=wiggle', async () => {
    const r = await gb('routine?name=wiggle')
    if (r.status === 200 && /queued/i.test(r.text)) { await gb('stop'); return { state: 'PASS', detail: `200 "${r.text.trim()}"` } }
    return { state: 'WARN', detail: `${r.status} "${r.text.slice(0, 60)}"` }
  })
  return allPass
}

export default function GrowbotView() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [st, setSt] = useState('ready')
  const [pose, setPose] = useState<{ l: number; r: number }>({ l: 90, r: 90 })
  const [ask, setAsk] = useState('')
  const [thread, setThread] = useState<Msg[]>([])
  const [conf, setConf] = useState<ConfRow[] | null>(null)
  const [confVerdict, setConfVerdict] = useState<string | null>(null)
  const poseTimer = useRef<number | null>(null)

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try { const s = await api<Stats>('/growbot/stats'); if (alive) setStats(s) }
      catch { if (alive) setStats(null) }
    }
    poll()
    const iv = setInterval(poll, 2500)
    return () => { alive = false; clearInterval(iv) }
  }, [])

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try { const ms = await api<Msg[]>(`/messages?thread=${THREAD}&limit=30`); if (alive) setThread(ms) }
      catch { /* anonymous or offline — the ask box will say so */ }
    }
    poll()
    const iv = setInterval(poll, 3000)
    return () => { alive = false; clearInterval(iv) }
  }, [])

  const go = async (path: string) => {
    setSt('moving...')
    try { const r = await gb(path); setSt(r.text.slice(0, 90)) }
    catch { setSt('! no link to body') }
  }

  /* live pose levers — throttled so a drag doesn't flood the body */
  const sendPose = (l: number, r: number) => {
    setPose({ l, r })
    if (poseTimer.current) return
    poseTimer.current = window.setTimeout(async () => {
      poseTimer.current = null
      try { await gb(`pose?l=${l}&r=${r}`) } catch { /* body offline */ }
    }, 60)
  }

  const sendAsk = async () => {
    const text = ask.trim()
    if (!text) return
    setAsk('')
    setSt('routed to the wire — the growbot agent choreographs...')
    try {
      await apiPost('/messages', { to: 'growbot', thread: THREAD, body: text })
    } catch {
      setSt('! send failed — owner key needed (top-right badge)')
    }
  }

  const conformance = async () => {
    setConf([])
    setConfVerdict(null)
    const rows: ConfRow[] = []
    const ok = await runConformance((r) => { rows.push(r); setConf([...rows]) })
    setConfVerdict(ok ? '✅ PASS — this body speaks GrowBot' : '❌ not conforming — see FAILs')
  }

  const online = !!stats
  // "serial" is the USB body host's extension key. A body that answers /stats
  // WITHOUT it is Brit's own Wi-Fi firmware — linked by definition (it answered).
  const wifiBody = !!stats && !('serial' in stats)
  const serialUp = !!stats?.serial

  return (
    <ScrollArea className="h-full starfield">
      <div className="max-w-3xl mx-auto px-4 py-6 flex flex-col gap-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-lg font-bold text-ink">growbot</div>
            <div className="text-xs text-ink-mute leading-relaxed">
              a <a className="text-cyan-soft hover:underline" href="https://github.com/britcruise9/GrowBot" target="_blank" rel="noreferrer">GrowBot</a> body
              on the astryx wire — two servo legs, a Pico for a spine, the org for a brain
            </div>
          </div>
          <a href="#/face"
            className="shrink-0 px-3 py-2 rounded-xl border border-line bg-deck-2 text-cyan-soft text-sm font-semibold hover:bg-deck-3">
            ◠ ◠ face
          </a>
        </div>

        {/* body vitals */}
        <div className="rounded-xl border border-line bg-deck-2/80 p-4 flex flex-wrap gap-x-6 gap-y-2 text-xs">
          <span className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${online ? 'bg-emerald-400' : 'bg-red-400'}`} />
            body host {online ? 'up' : 'down'}
          </span>
          <span className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${serialUp || wifiBody ? 'bg-emerald-400' : 'bg-ink-mute/40'}`} />
            {wifiBody ? 'wi-fi body' : `pico serial ${serialUp ? 'linked' : 'unplugged'}`}
          </span>
          {stats && (
            <>
              <span className="text-ink-dim">
                {stats.act.active ? `playing · ${stats.act.queued_ms}ms queued` : stats.moving ? 'held pose' : 'limp (resting)'}
              </span>
              <span className="text-ink-mute">dead-man ×{stats.deadman}</span>
              <span className="text-ink-mute">up {Math.floor(stats.up_s / 60)}m</span>
            </>
          )}
        </div>

        {/* routine buttons — Brit's control page, astryx-skinned */}
        <div className="grid grid-cols-2 gap-2.5">
          <button
            onClick={() => go('stop')}
            className="col-span-2 py-4 rounded-xl text-lg font-bold bg-red-900/60 border border-red-500/30 text-red-100 hover:bg-red-900/80"
          >
            STOP
          </button>
          {ROUTINES.map((r) => (
            <button
              key={r}
              onClick={() => go(`routine?name=${r}`)}
              className="py-3.5 rounded-xl font-semibold text-[15px] bg-deck-2 border border-line text-ink hover:bg-deck-3 hover:text-cyan-soft"
            >
              {r}
            </button>
          ))}
        </div>
        <div className="text-center text-xs text-ink-mute min-h-[1.2em] font-mono">{st}</div>

        {/* pose levers */}
        <div className="rounded-xl border border-line bg-deck-2/80 p-4">
          <div className="text-[11px] uppercase tracking-wider text-ink-mute mb-3 font-semibold">
            pose · 90 = neutral · the legs mirror: l + r = 180 moves them together
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-4">
            {(['l', 'r'] as const).map((leg) => (
              <div key={leg}>
                <div className="flex justify-between text-xs text-ink-dim mb-1">
                  <span>{leg === 'l' ? 'left leg' : 'right leg'}</span>
                  <span className="font-mono">{pose[leg]}°</span>
                </div>
                <Slider
                  min={0} max={180} value={pose[leg]}
                  onChange={(v) => sendPose(leg === 'l' ? v : pose.l, leg === 'r' ? v : pose.r)}
                  onChangeEnd={() => gb('stop').catch(() => undefined)}
                  color="cyan" size="sm" label={null}
                />
              </div>
            ))}
          </div>
          <div className="text-[10px] text-ink-mute mt-2">release the lever and the body goes limp (the dead-man contract)</div>
        </div>

        {/* the wire ask — the astryx twist: the brain is the org */}
        <div className="rounded-xl border border-line bg-deck-2/80 p-4">
          <div className="text-[11px] uppercase tracking-wider text-ink-mute mb-2 font-semibold">
            ask the org to move — routed over the wire, not an API
          </div>
          <div className="flex gap-2">
            <Textarea
              className="flex-1" autosize minRows={1} maxRows={4}
              value={ask}
              onChange={(e) => setAsk(e.currentTarget.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAsk() } }}
              placeholder="dance like you just shipped v1.0"
              styles={{ input: { background: '#141c3a', border: '1px solid #1d2647', color: '#e8f0fb' } }}
            />
            <button
              onClick={sendAsk}
              className="px-4 rounded-lg font-bold text-sm bg-gradient-to-br from-teal-400 to-sky-400 text-deck"
            >
              ask
            </button>
          </div>
          {thread.length > 0 && (
            <div className="mt-3 flex flex-col gap-1.5 max-h-56 overflow-y-auto">
              {thread.slice(-12).map((m) => (
                <div key={m.id} className="text-xs leading-relaxed">
                  <span className={`font-semibold ${m.from === 'owner' ? 'text-cyan-soft' : 'text-emerald-300'}`}>
                    {m.from}
                  </span>{' '}
                  <span className="text-ink-dim whitespace-pre-wrap">{m.body.length > 400 ? m.body.slice(0, 400) + '…' : m.body}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* conformance — Brit's protocol/conformance.html, inside the observatory */}
        <div className="rounded-xl border border-line bg-deck-2/80 p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="text-[11px] uppercase tracking-wider text-ink-mute font-semibold">
              body conformance · does it speak GrowBot?
            </div>
            <button
              onClick={conformance}
              className="px-3 py-1 rounded-md text-xs font-bold bg-deck-3 border border-line text-cyan-soft hover:text-cyan"
            >
              run
            </button>
          </div>
          {confVerdict && (
            <div className={`text-sm font-bold mb-2 ${confVerdict.startsWith('✅') ? 'text-emerald-300' : 'text-red-300'}`}>
              {confVerdict}
            </div>
          )}
          {conf?.map((c, i) => (
            <div key={i} className="flex items-start gap-2 py-1 text-xs border-t border-line/50 first:border-0">
              <span className={`px-1.5 rounded font-bold text-[10px] leading-4 min-w-[42px] text-center ${CONF_TAG[c.state]}`}>
                {c.state}
              </span>
              <span className="text-ink-dim">{c.name}</span>
              <span className="ml-auto font-mono text-ink-mute text-[10px] text-right">{c.detail}</span>
            </div>
          ))}
          {!conf && (
            <div className="text-xs text-ink-mute">
              runs the protocol checks from{' '}
              <a className="text-cyan-soft hover:underline" href="https://github.com/britcruise9/GrowBot/blob/main/protocol/PROTOCOL.md" target="_blank" rel="noreferrer">
                PROTOCOL.md
              </a>{' '}
              against this body, live
            </div>
          )}
        </div>
      </div>
    </ScrollArea>
  )
}
