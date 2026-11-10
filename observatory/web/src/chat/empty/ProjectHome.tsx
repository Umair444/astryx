import { useEffect, useState } from 'react'
import { displayName, fmtAgo } from '../../api'
import AgentFace from '../../components/AgentFace'
import type { WsThread } from '../data'
import type { Project } from '../model'

/* A project's home (plan-11884 C5): its name, its agents, its brief (saved on blur), Run (its agents start working
   it together on chat:project-<id>), and its chats. Iteration 5 grows it into a full project page. */

export default function ProjectHome({ p, threads, go, run, onBrief, onRemove }: {
  p: Project; threads: WsThread[]; go: (t: string) => void; run: () => void; onBrief: (b: string) => void; onRemove: () => void
}) {
  const [brief, setBrief] = useState(p.brief)
  useEffect(() => setBrief(p.brief), [p.brief])
  return (
    <div className="mx-auto w-full max-w-[720px] px-5 md:px-6 pt-14 pb-8">
      <div className="ws-label mb-2">Project</div>
      <h2 className="ws-display text-[48px] leading-[1] text-ink">{p.name}</h2>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        {p.agents.map((a) => <span key={a} className="inline-flex items-center gap-1.5 text-[13px] text-ink-dim"><AgentFace name={a} size={20} />{displayName(a)}</span>)}
        {p.agents.length === 0 && <span className="text-[13px] text-ink-mute">No agents yet: @mention them in one of its chats.</span>}
      </div>
      <label className="block mt-8 text-[13px] font-medium text-ink" htmlFor="brief">What the project is for</label>
      <textarea id="brief" value={brief} onChange={(e) => setBrief(e.target.value)} onBlur={() => brief !== p.brief && onBrief(brief)} rows={4}
        className="ws-composer mt-2 w-full outline-none p-4 text-[15px] leading-relaxed text-ink placeholder:text-ink-mute" placeholder="The outcome you want, and anything the agents should know." />
      <div className="mt-4 flex items-center gap-3">
        <button onClick={run} className="ws-btn !border-transparent ws-sig !text-[var(--t-on)] font-medium">Run the project</button>
        <span className="text-[12.5px] text-ink-mute max-sm:hidden">Its agents start working it together; you watch in the workforce.</span>
        <button onClick={onRemove} className="ml-auto text-[12.5px] text-ink-mute hover:text-bad">Remove</button>
      </div>
      <div className="mt-10 text-[13px] font-medium text-ink mb-1">Chats in this project</div>
      {p.threads.length === 0 && <div className="text-[13px] text-ink-mute">None yet. A chat you start from here joins it.</div>}
      {p.threads.map((t) => {
        const row = threads.find((x) => x.thread === t)
        return (
          <button key={t} onClick={() => go(t)} className="ws-row w-full flex items-center gap-3 rounded-[12px] -mx-2.5 px-2.5 py-2 text-left">
            <AgentFace name={row?.agents[0] ?? 'owner'} size={22} />
            <span className="flex-1 min-w-0 truncate text-[14px] text-ink">{row?.title ?? t}</span>
            <span className="text-[12px] text-ink-mute">{row ? fmtAgo(row.last_ts) : ''}</span>
          </button>
        )
      })}
    </div>
  )
}
