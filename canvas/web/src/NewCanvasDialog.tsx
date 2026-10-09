import { useState } from 'react'
import { post } from './api'
import { go } from './nav'
import { refreshLists, useStore } from './store'
import type { Canvas } from './types'
import { Modal } from './Modal'

const IDEAS = [
  ['Org pulse', 'A live dashboard of the org: agents awake, messages and steps today, goals in flight. Animate the numbers.'],
  ['Token economy', 'Where the org’s effort went this week, by agent and by goal, with a trend line.'],
  ['Explain the wire', 'A short animated explainer of how a message travels from me to an agent and back.'],
]

export function NewCanvasDialog({ onClose, seed }: { onClose: () => void; seed?: string }) {
  const me = useStore(s => s.me)!
  const agents = useStore(s => s.agents)
  const [title, setTitle] = useState('')
  const [brief, setBrief] = useState(seed ?? '')
  const [agent, setAgent] = useState(me.agents.includes(me.painter) ? me.painter : me.agents[0] ?? me.painter)
  const [tier, setTier] = useState<'org' | 'personal'>('org')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function create() {
    if (!title.trim()) return setErr('Give it a name')
    setBusy(true); setErr('')
    try {
      const c = await post<Canvas>('/canvases', { title, brief, agent, tier })
      await refreshLists()
      onClose()
      go(`/canvas/${c.id}`)
    } catch (e) { setErr(e instanceof Error ? e.message : 'failed') } finally { setBusy(false) }
  }

  return (
    <Modal title="New canvas" onClose={onClose}>
      <p className="text-fg-dim text-sm -mt-1 mb-5">Describe what you want to see. An agent paints it live — you'll watch it appear, then click and ask for changes.</p>
      <label className="block text-xs uppercase tracking-wider text-fg-mute mb-1.5">Name</label>
      <input autoFocus value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. Org pulse"
        className="w-full bg-white/[.04] border border-line rounded-xl px-3.5 py-2.5 outline-none focus:border-violet/50 mb-4" />
      <label className="block text-xs uppercase tracking-wider text-fg-mute mb-1.5">What should it show?</label>
      <textarea value={brief} onChange={e => setBrief(e.target.value)} rows={4} placeholder="The question it answers, the data, how it should feel…"
        className="w-full bg-white/[.04] border border-line rounded-xl px-3.5 py-2.5 outline-none focus:border-violet/50 resize-none" />
      {!brief && (
        <div className="flex flex-wrap gap-2 mt-2">
          {IDEAS.map(([t, b]) => (
            <button key={t} onClick={() => { setTitle(t); setBrief(b) }}
              className="text-xs px-3 py-1.5 rounded-full border border-line hover:border-violet/50 text-fg-dim hover:text-fg transition">{t}</button>
          ))}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 mt-4">
        <div>
          <label className="block text-xs uppercase tracking-wider text-fg-mute mb-1.5">Painted by</label>
          <select value={agent} onChange={e => setAgent(e.target.value)}
            className="w-full bg-ink-800 border border-line rounded-xl px-3 py-2.5 outline-none">
            {(agents.length ? agents.map(a => a.name) : [agent]).map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs uppercase tracking-wider text-fg-mute mb-1.5">Tier</label>
          <div className="grid grid-cols-2 gap-1 p-1 rounded-xl bg-white/[.04] border border-line">
            {(['org', 'personal'] as const).map(t => (
              <button key={t} onClick={() => setTier(t)}
                className={`py-1.5 rounded-lg text-sm transition ${tier === t ? 'bg-white/[.1] text-fg' : 'text-fg-dim'}`}>{t}</button>
            ))}
          </div>
        </div>
      </div>
      {tier === 'personal' && <p className="text-[12px] text-warn/80 mt-2">Personal canvases are never shared with anyone.</p>}
      {err && <p className="text-bad text-sm mt-3">{err}</p>}
      <button onClick={create} disabled={busy}
        className="w-full mt-5 sig rounded-2xl py-3 font-medium text-white disabled:opacity-60 hover:brightness-110 transition">
        {busy ? 'Handing the brush…' : 'Start painting'}
      </button>
    </Modal>
  )
}
