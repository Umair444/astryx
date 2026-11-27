import { useEffect, useRef, useState } from 'react'
import { api, displayName, fmtTokens } from '../../api'
import AgentFace from '../../components/AgentFace'
import { NeedsConfirm, terminalType } from '../live'

/* THE GENERAL COMMANDS AND THE QUIET ACTIONS (owner 11-15: "/usage doesn't belong to the terminal, they are general
   commands … /compact should work out of the way without showing the terminal screen"; homes/seed/chat-terminal/
   DESIGN.md parts 1-2). One card above the box, about the agent this chat is with (its lead):
     info    /usage /cost /status /context: answered from the org's own records (GET /api/ws/agents/<a>/session),
             nothing typed anywhere
     action  /compact /clear /model: typed into its session in the background (the guarded terminal route), the card
             saying what it is doing and when it is done: a compact is done when the agent's next turn records a
             smaller context; /clear asks first, as the server requires */

export type SessionAsk = { id: number; agent: string; kind: 'info'; what: 'usage' | 'cost' | 'status' | 'context' }
  | { id: number; agent: string; kind: 'action'; text: string }
interface Session {
  known: boolean; model?: string; context?: number; window?: number; window_proven?: boolean; last_turn_ended?: string | null
  session_turns?: number; session_tokens?: number; today_tokens?: number
  energy?: { known?: boolean; word?: string; fact?: string; windows?: Record<string, { used: number; resets_at: string; spare: number; dry_at: string | null }> }
}

const pct = (n: number, d: number) => `${Math.round((100 * n) / Math.max(1, d))}%`
const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

export default function SessionCard({ ask, onClose }: { ask: SessionAsk; onClose: () => void }) {
  const [s, setS] = useState<Session | null>(null)
  const [state, setState] = useState<string>('')
  const [confirm, setConfirm] = useState(false)
  const before = useRef<Session | null>(null)
  const name = displayName(ask.agent)
  const read = () => api<Session>(`/ws/agents/${encodeURIComponent(ask.agent)}/session`)

  async function act(confirmed = false) {
    if (ask.kind !== 'action') return
    setConfirm(false)
    try {
      before.current = await read()
      await terminalType(ask.agent, { text: ask.text, ...(confirmed ? { confirm: true } : {}) })
      setState(ask.text.startsWith('/compact') ? `Compacting ${name}…` : ask.text.startsWith('/clear') ? `Clearing ${name}’s conversation…` : `${ask.text} sent to ${name}`)
    } catch (e) {
      if (e instanceof NeedsConfirm) setConfirm(true)
      else setState(String((e as Error).message || e))
    }
  }
  useEffect(() => {
    setS(null); setState(''); setConfirm(false)
    if (ask.kind === 'info') read().then(setS).catch((e) => setState(String((e as Error).message || e)))
    else void act()
  }, [ask.id])   // eslint-disable-line react-hooks/exhaustive-deps
  // a compact is DONE when the agent's next turn has ended with a smaller context than before it
  useEffect(() => {
    if (ask.kind !== 'action' || !ask.text.startsWith('/compact') || !state.startsWith('Compacting')) return
    const t = setInterval(() => {
      read().then((now) => {
        const b = before.current
        if (b?.context && now.context && now.last_turn_ended !== b.last_turn_ended && now.context < b.context)
          setState(`${name} compacted · ${fmtTokens(b.context)} → ${fmtTokens(now.context)}`)
      }).catch(() => {})
    }, 4000)
    return () => clearInterval(t)
  }, [state])   // eslint-disable-line react-hooks/exhaustive-deps

  const w = s?.energy?.windows
  return (
    <section className="ws-col" aria-label={`${name}'s session`}>
      <div className="mb-2 rounded-[14px] border border-line px-3.5 py-2.5 flex flex-col gap-1.5" style={{ background: 'color-mix(in srgb, var(--t-panel) 92%, transparent)' }}>
        <div className="flex items-center gap-2">
          <AgentFace name={ask.agent} size={20} />
          <span className="text-[13px] font-medium text-ink flex-1 min-w-0 truncate">
            {ask.kind === 'info' ? `${name} · ${ask.what === 'usage' ? 'usage' : ask.what === 'cost' ? 'what it has used' : ask.what === 'status' ? 'status' : 'context'}` : name}
          </span>
          <button onClick={onClose} className="text-[12px] text-ink-mute hover:text-ink px-1">Close</button>
        </div>
        {state && <div className="text-[13px] text-ink-dim" role="status">{state}</div>}
        {confirm && ask.kind === 'action' && (
          <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-ink" role="alert">
            <span className="flex-1 min-w-[200px]">This wipes {name}’s conversation; it starts with no memory of this chat.</span>
            <button onClick={() => void act(true)} className="rounded-lg px-2.5 py-1 border border-line hover:border-line-2">Clear it</button>
            <button onClick={onClose} className="text-[12px] text-ink-mute hover:text-ink">Cancel</button>
          </div>
        )}
        {ask.kind === 'info' && !s && !state && <div className="text-[12.5px] text-ink-mute">Reading…</div>}
        {ask.kind === 'info' && s && !s.known && <div className="text-[12.5px] text-ink-mute">{name} hasn’t finished a turn yet, so there is nothing to read.</div>}
        {ask.kind === 'info' && s?.known && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1.5 text-[12.5px]">
            {(ask.what === 'status' || ask.what === 'context') && <Fact label="Model" value={s.model || '—'} />}
            {(ask.what === 'status' || ask.what === 'context') && (
              <Fact label="Context" value={`${fmtTokens(s.context ?? 0)} of ${fmtTokens(s.window ?? 0)}${s.window_proven ? '' : ' (assumed)'}`} sub={pct(s.context ?? 0, s.window ?? 1)} />
            )}
            {(ask.what === 'cost' || ask.what === 'status') && <Fact label="This session" value={fmtTokens(s.session_tokens ?? 0)} sub={`${s.session_turns ?? 0} turns`} />}
            {(ask.what === 'cost' || ask.what === 'status') && <Fact label="Today" value={fmtTokens(s.today_tokens ?? 0)} />}
            {(ask.what === 'usage' || ask.what === 'status') && w && Object.entries(w).map(([k, x]) => (
              <Fact key={k} label={k === 'h5' ? 'The 5 hours' : 'The week'} value={`${Math.round(x.used)}% used`} sub={x.dry_at ? `runs out around ${clock(x.dry_at)}` : `resets ${clock(x.resets_at)}`} />
            ))}
            {ask.what === 'context' && <div className="col-span-full text-[11.5px] text-ink-mute">The breakdown by part (system prompt, tools, memory, messages) is in its terminal: /terminal, then /context.</div>}
          </div>
        )}
      </div>
    </section>
  )
}

function Fact({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[11.5px] text-ink-mute">{label}</div>
      <div className="text-ink tabular-nums truncate">{value}</div>
      {sub && <div className="text-[11.5px] text-ink-mute truncate">{sub}</div>}
    </div>
  )
}
