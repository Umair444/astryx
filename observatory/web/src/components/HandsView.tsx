import { useCallback, useEffect, useRef, useState } from 'react'
import RFB from '@novnc/novnc/lib/rfb'
import { api, apiPost, displayName, obsKey } from '../api'
import AgentFace from './AgentFace'
import { Action, Empty, LiveDot, Panel, SectionHead, ViewHeader, useNow } from '../ui/kit'

/* Hands (plan-7862): every agent's own desktop on this machine, live. The owner WATCHES it, JOINS
   in (one shared cursor: the agent's next move takes it back), and STOPS it at any moment. The
   view never sends anything to an agent; the stop is a file the agent's hands check per action. */

type Desk = {
  agent: string
  running: boolean
  vnc_port: number | null
  stopped: string | null
  size: [number, number]
  last_act: { ts: number; action: string; by?: string } | null
  kind?: 'laptop' | 'own'
  windows?: { id: number; app: string; title: string; focused: boolean }[]
}

const ACT_LABEL: Record<string, string> = {
  click: 'clicking', type_text: 'typing', key: 'pressing keys', scroll: 'scrolling',
  drag: 'dragging', move: 'moving', open: 'opening', focus: 'switching windows',
}

const nameOf = (d: { agent: string }) => (d.agent === 'laptop' ? 'Your laptop' : displayName(d.agent))
const isLaptop = (d: { agent: string }) => d.agent === 'laptop'

function ago(ts: number, now: number) {
  const s = Math.max(0, Math.round(now / 1000 - ts))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  return `${Math.round(s / 3600)}h ago`
}

function Screen({ desk, joined }: { desk: Desk; joined: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  const rfb = useRef<RFB | null>(null)
  const [state, setState] = useState<'connecting' | 'live' | 'closed'>('connecting')

  useEffect(() => {
    if (!box.current || !desk.running) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${location.host}/api/hands/${encodeURIComponent(desk.agent)}/vnc?key=${encodeURIComponent(obsKey() || '')}`
    setState('connecting')
    const r = new RFB(box.current, url, { shared: true })
    r.scaleViewport = true
    r.resizeSession = false
    r.background = 'transparent'
    r.addEventListener('connect', () => setState('live'))
    r.addEventListener('disconnect', () => setState('closed'))
    rfb.current = r
    return () => { try { r.disconnect() } catch { /* already closed */ } rfb.current = null }
  }, [desk.agent, desk.running])

  useEffect(() => { if (rfb.current) rfb.current.viewOnly = !joined }, [joined, state])

  return (
    <div className="relative w-full rounded-xl overflow-hidden border border-line bg-black"
      style={{ aspectRatio: `${desk.size[0]} / ${desk.size[1]}`, boxShadow: joined ? '0 0 0 2px var(--t-accent)' : undefined }}>
      <div ref={box} className="absolute inset-0" />
      {state !== 'live' && (
        <div className="absolute inset-0 grid place-items-center text-[13px] text-ink-mute">
          {state === 'connecting' ? 'Connecting to the desktop…' : 'The desktop closed the connection.'}
        </div>
      )}
    </div>
  )
}

export default function HandsView() {
  const now = useNow(2000)
  const [desks, setDesks] = useState<Desk[] | null>(null)
  const [sel, setSel] = useState<string | null>(null)
  const [joined, setJoined] = useState(false)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    try {
      const d = (await api<Desk[]>('/hands')).sort((a, b) => Number(isLaptop(b)) - Number(isLaptop(a)))
      setDesks(d)
      setSel((s) => s ?? (d.find((x) => x.running)?.agent || d[0]?.agent || null))
    } catch (e) { setErr(String(e)) }
  }, [])
  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t) }, [load])

  const desk = desks?.find((d) => d.agent === sel) || null
  const doIt = async (what: 'stop' | 'resume' | 'up' | 'down') => {
    if (!desk) return
    setBusy(what); setErr('')
    try { await apiPost(`/hands/${encodeURIComponent(desk.agent)}/${what}`, {}); await load() }
    catch (e) { setErr(String(e)) } finally { setBusy('') }
  }
  const driving = (d: Desk) => !!d.last_act && now / 1000 - d.last_act.ts < 20 && !d.stopped
  const live = desks?.filter(driving) || []

  return (
    <div className="h-full overflow-y-auto px-4 sm:px-8 py-6">
      <ViewHeader kicker="agents at the keyboard" title="Hands"
        live={<>
          <LiveDot state={live.length ? 'working' : desks?.some((d) => d.running) ? 'awake' : 'asleep'} />
          {live.length ? live.map((d) => isLaptop(d) ? `${displayName(d.last_act?.by || '')} is using your laptop` : `${displayName(d.agent)} is working`).join(' · ')
            : desks?.some((d) => d.running) ? 'desktops open, nobody driving' : 'no desktop open'}
        </>}
        faces={live.map((d) => d.last_act?.by || d.agent).filter((n) => n !== 'laptop')} />

      {err && <div className="mb-4 text-[13px] text-[var(--t-bad,#e5484d)]">{err}</div>}
      {desks && desks.length === 0 && (
        <Empty title="No agent has opened its hands yet"
          hint="An agent's desktop starts the first time it uses its hands tool. You'll watch it here, join in, or stop it." />
      )}

      {desks && desks.length > 0 && (
        <div className="grid gap-5 lg:grid-cols-[240px_1fr]">
          <div className="flex lg:flex-col gap-2 overflow-x-auto lg:overflow-visible">
            {desks.map((d) => (
              <Panel key={d.agent} as="button" interactive onClick={() => { setSel(d.agent); setJoined(false) }}
                className={`shrink-0 flex items-center gap-3 px-3 py-2.5 min-w-[200px] ${d.agent === sel ? 'ring-1 ring-[var(--t-accent)]' : ''}`}>
                {isLaptop(d)
                  ? <span className="w-8 h-8 grid place-items-center rounded-full text-[16px] text-ink-dim border border-line">⌖</span>
                  : <AgentFace name={d.agent} size={32} />}
                <div className="min-w-0">
                  <div className="text-[14px] text-ink truncate">{nameOf(d)}</div>
                  <div className="text-[12px] text-ink-mute truncate">
                    {d.stopped ? 'stopped by you' : !d.running ? 'desktop closed'
                      : driving(d) ? `${isLaptop(d) ? displayName(d.last_act!.by || '') + ' · ' : ''}${ACT_LABEL[d.last_act!.action] || d.last_act!.action}…`
                      : d.last_act ? `idle · last moved ${ago(d.last_act.ts, now)}` : 'idle'}
                  </div>
                </div>
              </Panel>
            ))}
          </div>

          {desk && (
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2 mb-3">
                <SectionHead title={isLaptop(desk) ? 'Your laptop, live' : `${displayName(desk.agent)}'s own desktop`}
                  right={desk.windows && desk.windows.length > 0
                    ? <span className="text-[12px] text-ink-mute truncate max-w-[40ch]">{desk.windows.find((w) => w.focused)?.title || ''}</span>
                    : undefined} />
              </div>
              <div className="flex flex-wrap items-center gap-2 mb-3">
                {desk.running && !isLaptop(desk) && (
                  <button onClick={() => setJoined((j) => !j)}
                    className={`px-3.5 py-2 rounded-xl text-[13px] border ${joined ? 'border-[var(--t-accent)] text-ink' : 'border-line text-ink-dim hover:text-ink'}`}>
                    {joined ? 'You’re in: click Watch to let go' : 'Join in (use mouse + keyboard)'}
                  </button>
                )}
                {desk.stopped
                  ? <Action onClick={() => doIt('resume')} disabled={!!busy}>Give hands back</Action>
                  : <button onClick={() => doIt('stop')} disabled={!!busy}
                      className="px-4 py-2 rounded-xl text-[13px] font-medium text-white disabled:opacity-40"
                      style={{ background: '#e5484d' }}>{isLaptop(desk) ? 'Stop agents on my laptop' : `Stop ${displayName(desk.agent)}`}</button>}
                <span className="flex-1" />
                {desk.running
                  ? <button onClick={() => doIt('down')} title={isLaptop(desk) ? 'Detach: agents stop seeing your screen until one needs it again' : undefined} disabled={!!busy} className="px-3 py-2 rounded-xl text-[12px] text-ink-mute hover:text-ink border border-line">Close desktop</button>
                  : <button onClick={() => doIt('up')} disabled={!!busy} className="px-3 py-2 rounded-xl text-[12px] text-ink-dim hover:text-ink border border-line">Open desktop</button>}
              </div>
              {desk.stopped && (
                <div className="mb-3 text-[13px] text-ink-dim">Stopped. Every action {isLaptop(desk) ? 'any agent tries on your laptop' : displayName(desk.agent) + ' tries'} is now refused, and it's told to stop and report where it was.</div>
              )}
              {isLaptop(desk) && !desk.stopped && (
                <div className="mb-3 text-[13px] text-ink-dim">This is your real screen: your browser, your logins, your apps. An agent here uses your cursor while it works.</div>
              )}
              {desk.running ? <Screen desk={desk} joined={joined} />
                : <Panel className="p-10"><Empty title="Desktop closed" hint="Its browser profile and logins are kept. Open it again, or the agent opens it when it next uses its hands." /></Panel>}
              {joined && !isLaptop(desk) && <div className="mt-2 text-[12px] text-ink-mute">You and {displayName(desk.agent)} share one cursor here. Your moves take it; its next action takes it back. Click Watch before it acts again if you're mid-task.</div>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
