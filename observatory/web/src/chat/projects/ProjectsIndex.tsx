import { motion, useReducedMotion } from 'motion/react'
import AgentFace from '../../components/AgentFace'
import { I } from '../icons'
import type { WsThread } from '../data'
import type { Project } from '../model'
import { colorCss } from './model'
import { ProjectMark, since } from './parts'

/* ALL PROJECTS (#/chat/projects): one card per project — its mark and name, the first lines of its instructions,
   its team, how many conversations and files, when it last changed — newest first, and "New project". */

export default function ProjectsIndex({ projects, threads, loaded, onOpen, onNew }: {
  projects: Project[]; threads: WsThread[]; loaded: boolean; onOpen: (id: string) => void; onNew: () => void
}) {
  const reduce = useReducedMotion()
  const last = (p: Project) => Math.max(Date.parse(p.updated ?? '0') || 0, ...threads.filter((t) => p.threads.includes(t.thread)).map((t) => Date.parse(t.last_ts ?? '0') || 0))
  const list = [...projects].sort((a, b) => last(b) - last(a))
  const known = new Set(threads.map((t) => t.thread))
  return (
    <div className="mx-auto w-full max-w-[1080px] px-4 md:px-10 pt-8 md:pt-12 pb-20">
      <div className="flex items-end gap-4 flex-wrap">
        <div>
          <h1 className="ws-display text-[clamp(40px,5.4vw,56px)] leading-[0.95] text-ink">Projects</h1>
          <p className="mt-2 text-[13px] text-ink-mute">Instructions, a team, its files and its conversations: work that outlives one chat.</p>
        </div>
        <button onClick={onNew} className="ws-btn ws-btn-primary ml-auto">{I.plus('w-4 h-4')}New project</button>
      </div>
      {loaded && list.length === 0 && (
        <div className="max-w-[540px] mx-auto py-16 text-center">
          <div className="mx-auto w-14 h-14 rounded-[18px] grid place-items-center bg-[color-mix(in_srgb,var(--t-accent)_10%,transparent)] text-[var(--t-accent)]">{I.folder('w-6 h-6')}</div>
          <h2 className="ws-display text-[30px] leading-tight text-ink mt-5">No projects yet</h2>
          <p className="mt-2 text-[14px] text-ink-dim leading-relaxed">
            A project keeps a piece of work together: the instructions its team works under, the agents on it, the files it relies
            on, and every conversation about it. Each new chat in a project starts already briefed.
          </p>
          <button onClick={onNew} className="ws-btn mt-6">{I.plus('w-4 h-4')}Make the first one</button>
        </div>
      )}
      <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {list.map((p, i) => {
          const n = p.threads.filter((t) => known.has(t)).length          // conversations with words in them, as the sidebar counts
          return (
            <motion.button key={p.id} onClick={() => onOpen(p.id)} className="ws-pcard text-left p-4 flex flex-col gap-3 min-h-[168px]"
              style={{ ['--pc' as string]: colorCss(p.color) }}
              {...(reduce ? {} : { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.4, delay: Math.min(i, 8) * 0.03, ease: [0.22, 1, 0.36, 1] } })}>
              <span className="flex items-center gap-2.5">
                <ProjectMark p={p} size={30} />
                <span className="min-w-0 flex-1 text-[15px] font-medium text-ink truncate">{p.name}</span>
              </span>
              <span className={`text-[12.5px] leading-snug line-clamp-3 ${p.instructions ? 'text-ink-dim' : 'text-ink-mute italic'}`}>{p.instructions || 'No instructions yet.'}</span>
              <span className="mt-auto flex items-center gap-2 text-[11.5px] text-ink-mute">
                <span className="flex -space-x-1">{p.agents.slice(0, 4).map((a) => <span key={a} className="rounded-full ring-2 ring-[var(--t-panel)]"><AgentFace name={a} size={18} /></span>)}</span>
                <span>{n} chat{n === 1 ? '' : 's'} · {p.files.length} file{p.files.length === 1 ? '' : 's'}</span>
                {p.updated && <span className="ml-auto">{since(p.updated)}</span>}
              </span>
            </motion.button>
          )
        })}
      </div>
    </div>
  )
}
