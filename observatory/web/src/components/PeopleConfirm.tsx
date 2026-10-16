import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api, apiPost } from '../api'
import { Empty, Skeleton } from '../ui/kit'

/* The owner tells the org who his people are. memory guesses privately (pid-keyed, counts-only
   evidence, never on the wire); here the owner confirms, corrects, or skips — one card at a time,
   names resolved on the owner's side only. Owner-only, like the graph it sits beside. */

interface Ask {
  pid: string
  label: string
  kind: string | null
  closeness: string | null
  confidence: string | null
  evidence: { shared_groups?: number; dm_msgs?: number; cadence_days?: number; days_since?: number; balance?: number }
}
interface Asks { kinds: string[]; closeness: string[]; answered: number; asks: Ask[] }

export default function PeopleConfirm({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<Asks | null>(null)
  const [err, setErr] = useState('')
  const load = () => api<Asks>('/people/asks').then(setData).catch((e) => setErr(String(e)))
  useEffect(() => { load() }, [])

  return (
    <aside className="ax-panel w-[360px] max-w-[92vw] shrink-0 m-3 mr-0 rounded-2xl flex flex-col min-h-0 overflow-hidden">
      <div className="px-4 py-3.5 border-b border-line flex items-start gap-2">
        <div className="min-w-0">
          <div className="text-[15px] font-semibold text-ink">Help the org know your people</div>
          <div className="text-[11px] text-ink-mute leading-snug mt-0.5">
            memory's private guesses — confirm, correct or skip. Names stay on your side; memory only hears a count.
          </div>
        </div>
        <button onClick={onClose} aria-label="close" className="ml-auto w-7 h-7 grid place-items-center rounded-full text-ink-mute hover:text-ink hover:bg-deck-3 text-lg leading-none">×</button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2.5">
        {err && <div className="text-[12px] text-bad">{err}</div>}
        {!data && !err && [0, 1, 2].map((i) => <Skeleton key={i} className="h-[148px] w-full rounded-xl" />)}
        {data && data.asks.length === 0 && (
          <Empty title="Nothing to confirm right now"
            hint={`${data.answered ? `${data.answered} answered so far. ` : ''}memory adds the next batch as its evidence grows.`} />
        )}
        <AnimatePresence initial={false}>
          {data?.asks.map((a) => (
            <Card key={a.pid} a={a} kinds={data.kinds} closeness={data.closeness}
              onDone={() => setData((d) => d && { ...d, answered: d.answered + 1, asks: d.asks.filter((x) => x.pid !== a.pid) })} />
          ))}
        </AnimatePresence>
      </div>
      {data && <div className="px-4 py-2 border-t border-line text-[11px] text-ink-mute">{data.asks.length} waiting · {data.answered} answered</div>}
    </aside>
  )
}

function Card({ a, kinds, closeness, onDone }: { a: Ask; kinds: string[]; closeness: string[]; onDone: () => void }) {
  const [kind, setKind] = useState(a.kind && kinds.includes(a.kind) ? a.kind : '')
  const [close, setClose] = useState(a.closeness && closeness.includes(a.closeness) ? a.closeness : '')
  const [busy, setBusy] = useState(false)
  const e = a.evidence
  async function send(skip = false) {
    setBusy(true)
    try { await apiPost('/people/answers', { pid: a.pid, kind: skip ? null : kind, closeness: skip ? null : close, skip }); onDone() }
    finally { setBusy(false) }
  }
  return (
    <motion.div layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 40 }}
      className="rounded-xl border border-line bg-deck-3/50 p-3.5">
      <div className="flex items-baseline gap-2">
        <span className="text-[14px] font-medium text-ink truncate">{a.label}</span>
        {a.confidence && <span className="text-[10px] uppercase tracking-wider text-ink-mute">{a.confidence} confidence</span>}
      </div>
      <div className="text-[11px] text-ink-mute mt-0.5 font-mono">
        {[e.dm_msgs != null && `${e.dm_msgs} msgs`, e.shared_groups != null && `${e.shared_groups} shared groups`,
          e.cadence_days != null && `every ~${Math.round(e.cadence_days)}d`, e.days_since != null && `last ${Math.round(e.days_since)}d ago`]
          .filter(Boolean).join(' · ') || 'little evidence yet'}
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {kinds.map((k) => (
          <button key={k} onClick={() => setKind(k)}
            className={`text-[11.5px] px-2.5 py-0.5 rounded-full border transition ${kind === k ? 'border-cyan bg-cyan/15 text-ink' : 'border-line text-ink-dim hover:text-ink hover:border-line-2'}`}>{k}</button>
        ))}
      </div>
      <div className="mt-1.5 flex gap-1">
        {closeness.map((c) => (
          <button key={c} onClick={() => setClose(c)}
            className={`flex-1 text-[11px] py-0.5 rounded-md border transition ${close === c ? 'border-cyan bg-cyan/15 text-ink' : 'border-line text-ink-dim hover:text-ink'}`}>{c}</button>
        ))}
      </div>
      <div className="mt-2.5 flex gap-2">
        <button disabled={busy || !kind || !close} onClick={() => send(false)}
          className="ax-action flex-1 text-[12px] font-medium py-1.5 rounded-lg disabled:opacity-40">
          {a.kind && kind === a.kind && close === a.closeness ? 'Confirm' : 'Save'}
        </button>
        <button disabled={busy} onClick={() => send(true)} className="text-[12px] px-3 py-1.5 rounded-lg border border-line text-ink-dim hover:text-ink">Skip</button>
      </div>
    </motion.div>
  )
}
