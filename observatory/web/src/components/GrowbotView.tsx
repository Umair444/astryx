import { useEffect, useRef, useState } from 'react'
import { ScrollArea, Slider, Textarea } from '@mantine/core'
import { api, apiPost, obsKey } from '../api'
import type { Msg } from '../types'
import { displayName } from '../api'
import AgentFace from './AgentFace'
import { Empty, LiveDot, Panel, SectionHead, ViewHeader } from '../ui/kit'

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
  PASS: 'bg-good/15 text-good',
  FAIL: 'bg-bad/15 text-bad',
  WARN: 'bg-warn/15 text-warn',
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

  const bodyState = !online ? 'asleep' : stats?.act.active ? 'working' : 'awake'

  return (
    <ScrollArea className="h-full">
      <div className="max-w-3xl mx-auto px-5 sm:px-8 py-7 flex flex-col gap-5">
        <ViewHeader
          kicker="a body on the wire"
          title="GrowBot"
          live={<>
            <span className="flex items-center gap-1.5"><LiveDot state={bodyState} />body host {online ? 'up' : 'down'}</span>
            <span className="text-ink-mute">·</span>
            <span className="flex items-center gap-1.5">
              <LiveDot state={serialUp || wifiBody ? 'awake' : 'asleep'} />
              {wifiBody ? 'wi-fi body' : `pico serial ${serialUp ? 'linked' : 'unplugged'}`}
            </span>
          </>}
          actions={
            <a href="#/face" className="ax-panel ax-panel-hover px-4 py-2 rounded-xl text-[13px] font-medium text-ink no-underline">
              ◠ ◠ face
            </a>
          }
        />
        <p className="-mt-3 text-[13px] text-ink-mute leading-relaxed">
          A <a className="text-cyan-soft hover:underline" href="https://github.com/britcruise9/GrowBot" target="_blank" rel="noreferrer">GrowBot</a> body
          on the astryx wire — two servo legs, a Pico for a spine, the org for a brain.
        </p>

        {/* body vitals */}
        <Panel live={!!stats?.act.active} className="p-4 grid grid-cols-2 sm:grid-cols-4 gap-4">
          {(
            [
              ['motion', stats ? (stats.act.active ? `playing · ${stats.act.queued_ms}ms` : stats.moving ? 'held pose' : 'limp (resting)') : '—'],
              ['dead-man', stats ? `×${stats.deadman}` : '—'],
              ['uptime', stats ? `${Math.floor(stats.up_s / 60)}m` : '—'],
              ['commands', stats ? String(stats.set_n) : '—'],
            ] as [string, string][]
          ).map(([k, v]) => (
            <div key={k} className="min-w-0">
              <div className="text-[10.5px] uppercase tracking-[0.14em] text-ink-mute">{k}</div>
              <div className="text-[15px] font-semibold text-ink mt-1 truncate">{v}</div>
            </div>
          ))}
        </Panel>

        {/* routine buttons — Brit's control page, astryx-skinned */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
          <button
            onClick={() => go('stop')}
            className="col-span-2 sm:col-span-3 py-4 rounded-2xl text-[17px] font-bold tracking-[0.12em] bg-bad/15 border border-bad/40 text-bad hover:bg-bad/25 transition-colors"
          >
            STOP
          </button>
          {ROUTINES.map((r) => (
            <Panel key={r} as="button" interactive onClick={() => go(`routine?name=${r}`)}
              className="py-4 font-semibold text-[15px] text-ink capitalize">
              <span className="block w-full text-center">{r}</span>
            </Panel>
          ))}
        </div>
        <div className="text-center text-xs text-ink-mute min-h-[1.2em] font-mono">{st}</div>

        {/* pose levers */}
        <Panel className="p-5">
          <SectionHead title="Pose" right={<span className="text-[11px] text-ink-mute">90 = neutral · l + r = 180 moves them together</span>} />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-4">
            {(['l', 'r'] as const).map((leg) => (
              <div key={leg}>
                <div className="flex justify-between text-xs text-ink-dim mb-1.5">
                  <span>{leg === 'l' ? 'left leg' : 'right leg'}</span>
                  <span className="font-mono text-ink">{pose[leg]}°</span>
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
          <div className="text-[11px] text-ink-mute mt-3">release the lever and the body goes limp (the dead-man contract)</div>
        </Panel>

        {/* the wire ask — the astryx twist: the brain is the org */}
        <Panel className="p-5">
          <SectionHead title="Ask the org to move" right={<span className="text-[11px] text-ink-mute">routed over the wire, not an API</span>} />
          <div className="flex items-end gap-2 rounded-xl bg-deck-3/70 border border-line focus-within:border-cyan/50 pl-3 pr-1.5 py-1.5 transition-colors">
            <Textarea
              className="flex-1" autosize minRows={1} maxRows={4}
              value={ask}
              variant="unstyled"
              onChange={(e) => setAsk(e.currentTarget.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAsk() } }}
              placeholder="dance like you just shipped v1.0"
              styles={{ input: { color: 'var(--t-fg)', fontSize: 14, padding: '4px 0' } }}
            />
            <button onClick={sendAsk} disabled={!ask.trim()} className="ax-action px-4 py-1.5 rounded-lg font-medium text-[13px] disabled:opacity-40">
              Ask
            </button>
          </div>
          {thread.length > 0 && (
            <div className="mt-4 flex flex-col gap-2.5 max-h-64 overflow-y-auto">
              {thread.slice(-12).map((m) => (
                <div key={m.id} className="flex gap-2.5 text-[13px] leading-relaxed">
                  {m.from === 'owner'
                    ? <span className="w-6 h-6 shrink-0 rounded-full grid place-items-center text-[10px] font-semibold ax-action">you</span>
                    : <AgentFace name={m.from} size={24} />}
                  <div className="min-w-0">
                    <span className={`font-semibold text-[12px] ${m.from === 'owner' ? 'text-cyan-soft' : 'text-ink'}`}>
                      {m.from === 'owner' ? 'you' : displayName(m.from)}
                    </span>
                    <div className="text-ink-dim whitespace-pre-wrap">{m.body.length > 400 ? m.body.slice(0, 400) + '…' : m.body}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        {/* conformance — Brit's protocol/conformance.html, inside the observatory */}
        <Panel className="p-5">
          <SectionHead title="Body conformance"
            right={<button onClick={conformance} className="ax-action px-3.5 py-1 rounded-lg text-xs font-medium">Run</button>} />
          {confVerdict && (
            <div className={`text-[14px] font-semibold mb-2 ${confVerdict.startsWith('✅') ? 'text-good' : 'text-bad'}`}>
              {confVerdict}
            </div>
          )}
          {conf?.map((c, i) => (
            <div key={i} className="flex items-start gap-2.5 py-2 text-xs border-t border-line/50 first:border-0">
              <span className={`px-2 rounded-full font-bold text-[10px] leading-5 min-w-[46px] text-center ${CONF_TAG[c.state]}`}>
                {c.state}
              </span>
              <span className="text-ink-dim">{c.name}</span>
              <span className="ml-auto font-mono text-ink-mute text-[10px] text-right">{c.detail}</span>
            </div>
          ))}
          {!conf && (
            <Empty tone="accent2" title="Does this body speak GrowBot?"
              hint={<>Runs the protocol checks from{' '}
                <a className="text-cyan-soft hover:underline" href="https://github.com/britcruise9/GrowBot/blob/main/protocol/PROTOCOL.md" target="_blank" rel="noreferrer">
                  PROTOCOL.md
                </a>{' '}against this body, live.</>} />
          )}
        </Panel>
      </div>
    </ScrollArea>
  )
}
