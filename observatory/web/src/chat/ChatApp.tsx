import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { api, apiPost, displayName, fmtAgo } from '../api'
import { useStore } from '../store'
import type { Msg, Step } from '../types'
import { canvasBase } from '../cog'
import AgentFace from '../components/AgentFace'
import ChatComposer, { type Command, type ComposerHandle } from './ChatComposer'
import Thread from './Thread'
import { Viewer, Workforce } from './Side'
import { startDictation } from './dictate'
import {
  bodyFor, isChat, loadCommands, loadProjects, newThread, participants, saveProjects, slug, stepsOf, stripEmbeds,
  type McpTool, type Project, type Projects, type Skill, type Uploaded,
} from './model'

/* /chat (plan-11884): the long-form workspace on the org. The floor's sheet is for a word with one agent; this is for
   an hour of work with several. Three panes: the RAIL (chats, projects, ⌘K), the CONVERSATION (a wire thread
   `chat:<id>`), and the SIDE (a file, or the workforce at work). Everything is on a key; ⌘/ lists them. */

interface ThreadRow { thread: string; count: number; last_ts: string; starter: string; preview: string }
type Side = { kind: 'file'; path: string } | { kind: 'workforce' } | null

const KEYS: [string, string][] = [
  ['⌘K', 'Jump to a chat, an agent, a project or a command'],
  ['⌘⇧O', 'New chat'],
  ['⌘J', 'Show or hide the workforce'],
  ['⌘.', 'Dictate into the message box'],
  ['/', 'Commands, skills and tools (in the box), or focus the box'],
  ['@', 'Mention an agent: it joins the chat'],
  ['↑', 'In an empty box: your last message, to edit and send again'],
  ['Alt ↑ / Alt ↓', 'Previous or next chat'],
  ['Esc', 'Close a menu, the palette or the side panel'],
]

export default function ChatApp({ thread, go }: { thread: string | null; go: (t: string | null) => void }) {
  const { agents: roster, messages, send, who } = useStore()
  const reduce = useReducedMotion()
  const names = useMemo(() => roster.map((a) => a.agent).sort(), [roster])
  const [threads, setThreads] = useState<ThreadRow[]>([])
  const [history, setHistory] = useState<Msg[] | null>(null)
  const [steps, setSteps] = useState<Record<string, Step[]>>({})
  const [side, setSide] = useState<Side>({ kind: 'workforce' })
  const [palette, setPalette] = useState(false)
  const [help, setHelp] = useState(false)
  const [cmds, setCmds] = useState<{ skills: Skill[]; tools: McpTool[] }>({ skills: [], tools: [] })
  const [proj, setProj] = useState<Projects>({ etag: '', projects: [] })
  const [project, setProject] = useState<string | null>(null)
  const [asking, setAsking] = useState<null | 'project'>(null)
  const [note, setNote] = useState('')
  const composer = useRef<ComposerHandle>(null)
  const current = thread ?? ''

  // the rail: chats are the wire's chat: threads, newest first
  const loadThreads = useCallback(() => api<ThreadRow[]>('/threads').then((r) => setThreads(r.filter((t) => isChat(t.thread)))).catch(() => {}), [])
  useEffect(() => { loadThreads() }, [loadThreads])
  useEffect(() => { loadCommands().then(setCmds); loadProjects().then(setProj).catch(() => {}) }, [])

  // the thread: its history once, then the live feed, merged by id
  useEffect(() => {
    if (!current) { setHistory([]); return }
    let live = true
    setHistory(null)
    api<Msg[]>(`/messages?thread=${encodeURIComponent(current)}&limit=500`).then((h) => live && setHistory(h)).catch(() => live && setHistory([]))
    return () => { live = false }
  }, [current])
  const rows = useMemo(() => {
    const by = new Map<number, Msg>()
    for (const m of history ?? []) by.set(m.id, m)
    for (const m of messages) if (m.thread === current) by.set(m.id, m)
    return [...by.values()].sort((a, b) => a.id - b.id)
  }, [history, messages, current])
  const newest = rows.at(-1)?.id ?? 0
  useEffect(() => { if (newest) loadThreads() }, [newest, loadThreads])

  const activeProject = proj.projects.find((p) => p.id === project) ?? null
  const inChat = useMemo(() => participants(rows), [rows])
  const lanes = activeProject && !current ? activeProject.agents : inChat

  // each lane's steps: fetched when it appears, and again whenever the live feed says that agent moved
  const pulse = roster.filter((a) => lanes.includes(a.agent)).map((a) => `${a.agent}:${a.steps}`).join(',')
  useEffect(() => {
    let live = true
    for (const a of lanes) stepsOf(a).then((s) => live && setSteps((cur) => ({ ...cur, [a]: s }))).catch(() => {})
    return () => { live = false }
  }, [pulse]) // eslint-disable-line react-hooks/exhaustive-deps

  // asked and not yet answered: an agent whose newest row here is older than the owner's newest row to it
  const pending = useMemo(() => {
    const out: { agent: string; step: Step | null }[] = []
    for (const a of inChat) {
      const askedAt = Math.max(0, ...rows.filter((m) => m.from === 'owner' && m.to === a).map((m) => m.id))
      const saidAt = Math.max(0, ...rows.filter((m) => m.from === a).map((m) => m.id))
      if (askedAt > saidAt) out.push({ agent: a, step: (steps[a] ?? []).filter((s) => Date.parse(s.ts) >= Date.parse(rows.find((m) => m.id === askedAt)!.ts)).at(-1) ?? null })
    }
    return out
  }, [inChat, rows, steps])

  async function onSend(text: string, files: Uploaded[], to: string[]) {
    const t = current || newThread()
    const body = [text, ...files.map((f) => `[[file:${f.path}]]`)].filter(Boolean).join('\n')
    for (const a of to) await send(a, bodyFor(body, to, a), t)        // R4: one row per recipient, one thread
    if (!current) go(t)
    if (activeProject && !activeProject.threads.includes(t)) await saveProject({ ...activeProject, threads: [...activeProject.threads, t] })
  }

  async function saveProject(p: Project, remove = false) {
    const list = remove ? proj.projects.filter((x) => x.id !== p.id) : proj.projects.some((x) => x.id === p.id)
      ? proj.projects.map((x) => (x.id === p.id ? p : x)) : [...proj.projects, p]
    try { setProj(await saveProjects(proj.etag, list)) } catch (e) {
      const fresh = (e as { fresh?: Projects }).fresh
      if (fresh) { setProj(fresh); setNote('Projects changed somewhere else; reloaded them. Try again.') } else setNote(String((e as Error).message))
    }
  }

  async function runProject(p: Project) {
    if (!p.agents.length) { setNote('Add agents to this project first: open one of its chats and @mention them.'); return }
    const t = `chat:project-${p.id}`
    const kick = `Project "${p.name}" is running.${p.brief ? `\nBrief: ${p.brief}` : ''}\nWork it together and autonomously: split it between you, say who takes what on this thread, and post progress and results here as you go. Ask me only what you can't decide.`
    for (const a of p.agents) await send(a, bodyFor(kick, p.agents, a), t)
    if (!p.threads.includes(t)) await saveProject({ ...p, threads: [t, ...p.threads] })
    go(t); setSide({ kind: 'workforce' })
  }

  const commands: Command[] = [
    { key: 'new', label: 'New chat', hint: 'start an empty chat', run: () => { setProject(null); go(null) } },
    { key: 'project', label: 'Make this a project', hint: 'name it; its agents work it together', run: () => { setAsking('project') } },
    { key: 'run', label: 'Run the project', hint: 'its agents start working it on their own', run: () => (activeProject ? void runProject(activeProject) : 'Open a project first (⌘K).') },
    { key: 'workforce', label: 'Workforce', hint: 'show the agents at work', run: () => setSide({ kind: 'workforce' }) },
    { key: 'voice', label: 'Dictate', hint: 'speak into the message box (⌘.)', run: () => void startDictation((t) => composer.current?.insert(t)) },
    { key: 'remember', label: 'Remember', hint: 'propose the rest of the line to the memory agent', run: () => composer.current?.set('/remember ') },
    { key: 'canvas', label: 'Open in canvas', hint: 'build a page with the first agent here', run: () => void window.open(`${canvasBase()}#/new/${encodeURIComponent(inChat[0] ?? 'painter')}`, '_blank') },
    { key: 'keys', label: 'Keyboard', hint: 'every shortcut', run: () => setHelp(true) },
  ]
  // "/remember text" is sent to memory's proposal route, not to the chat
  async function onSendOrCommand(text: string, files: Uploaded[], to: string[]) {
    const r = /^\/remember\s+([\s\S]+)/.exec(text)
    if (r) { await apiPost('/memory/propose', { text: r[1], nodes: [] }); setNote('Proposed to the memory agent.'); return }
    return onSend(text, files, to)
  }

  // ------------------------------------------------------------------------------------------------- keys
  const chatIds = threads.map((t) => t.thread)
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      const typing = (e.target as HTMLElement)?.closest('textarea, input')
      if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette((p) => !p); return }
      if (mod && e.shiftKey && e.key.toLowerCase() === 'o') { e.preventDefault(); setProject(null); go(null); composer.current?.focus(); return }
      if (mod && e.key.toLowerCase() === 'j') { e.preventDefault(); setSide((s) => (s?.kind === 'workforce' ? null : { kind: 'workforce' })); return }
      if (mod && e.key === '/') { e.preventDefault(); setHelp((h) => !h); return }
      if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
        e.preventDefault()
        const i = chatIds.indexOf(current), j = e.key === 'ArrowUp' ? i - 1 : i + 1
        if (chatIds[j]) go(chatIds[j])
        return
      }
      if (e.key === 'Escape') { if (palette) setPalette(false); else if (help) setHelp(false); else if (side?.kind === 'file') setSide({ kind: 'workforce' }); return }
      if (!typing && !mod && e.key === '/') { e.preventDefault(); composer.current?.focus(); composer.current?.set('/') }
    }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [palette, help, side, current, chatIds.join('|')]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!who.owner) return (
    <div className="h-dvh grid place-items-center bg-deck text-ink p-8">
      <div className="max-w-sm text-center">
        <div className="text-[22px] font-semibold">Chat is for the owner</div>
        <p className="mt-2 text-ink-dim text-[14px]">Sign in on the floor first, then come back here.</p>
        <a href="#/" className="inline-block mt-5 text-cyan text-[14px]">Go to the floor</a>
      </div>
    </div>
  )

  const title = current ? (threads.find((t) => t.thread === current)?.preview ? stripEmbeds(threads.find((t) => t.thread === current)!.preview) : 'New chat') : activeProject ? activeProject.name : 'New chat'
  return (
    <div className="h-dvh flex bg-deck text-ink overflow-hidden">
      {/* ── the rail ─────────────────────────────────────────────────────────────────────── */}
      <nav className="w-[264px] shrink-0 border-r border-line bg-chrome flex flex-col max-md:hidden" aria-label="chats">
        <div className="h-12 flex items-center gap-2 px-3 border-b border-line">
          <a href="#/" className="text-[13px] text-ink-dim hover:text-ink px-1.5 py-1 rounded-md" title="Back to the floor">Floor</a>
          <span className="text-ink-mute" aria-hidden>/</span>
          <span className="text-[13px] font-semibold">Chat</span>
          <button onClick={() => setPalette(true)} className="ml-auto chat-tool" title="Search everything (⌘K)">⌘K</button>
        </div>
        <button onClick={() => { setProject(null); go(null); composer.current?.focus() }}
          className="m-3 mb-2 rounded-xl border border-line hover:border-line-2 px-3 py-2 text-left text-[13.5px] text-ink">New chat <span className="float-right text-ink-mute text-[11.5px]">⌘⇧O</span></button>
        <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-3">
          <div className="px-2 pt-2 pb-1 text-[12px] text-ink-mute">Projects</div>
          {proj.projects.length === 0 && <div className="px-2 py-1 text-[12.5px] text-ink-mute">Type /project in a chat to make one.</div>}
          {proj.projects.map((p) => (
            <button key={p.id} onClick={() => { setProject(p.id); go(null); setSide({ kind: 'workforce' }) }}
              className={`w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-left ${project === p.id && !current ? 'bg-deck-3' : 'hover:bg-deck-2'}`}>
              <span className="text-[13px] text-ink truncate flex-1">{p.name}</span>
              <span className="flex -space-x-1.5">{p.agents.slice(0, 3).map((a) => <AgentFace key={a} name={a} size={16} />)}</span>
            </button>
          ))}
          <div className="px-2 pt-4 pb-1 text-[12px] text-ink-mute">Recent</div>
          {threads.length === 0 && <div className="px-2 py-1 text-[12.5px] text-ink-mute">Your chats appear here.</div>}
          {threads.map((t) => (
            <button key={t.thread} onClick={() => go(t.thread)} aria-current={t.thread === current}
              className={`w-full text-left rounded-lg px-2 py-1.5 ${t.thread === current ? 'bg-deck-3' : 'hover:bg-deck-2'}`}>
              <div className="text-[13px] text-ink truncate">{stripEmbeds(t.preview) || 'Attachment'}</div>
              <div className="text-[11.5px] text-ink-mute">{fmtAgo(t.last_ts)}, {t.count} {t.count === 1 ? 'message' : 'messages'}</div>
            </button>
          ))}
        </div>
      </nav>

      {/* ── the conversation ─────────────────────────────────────────────────────────────── */}
      <main className="flex-1 min-w-0 flex flex-col">
        <header className="h-12 shrink-0 flex items-center gap-3 px-5 border-b border-line">
          <a href="#/" className="md:hidden text-[13px] text-ink-dim">Floor</a>
          <h1 className="text-[14px] font-medium truncate">{title}</h1>
          {activeProject && <span className="text-[12px] text-ink-mute shrink-0">in {activeProject.name}</span>}
          <div className="ml-auto flex items-center gap-1.5">
            {lanes.slice(0, 6).map((a) => <span key={a} title={displayName(a)}><AgentFace name={a} size={22} /></span>)}
            <button className="chat-tool ml-1" onClick={() => setSide((s) => (s?.kind === 'workforce' ? null : { kind: 'workforce' }))} aria-pressed={side?.kind === 'workforce'} title="Workforce (⌘J)">Workforce</button>
          </div>
        </header>
        <div className="flex-1 min-h-0 overflow-y-auto">
          {!current && !activeProject && <Empty names={names} onPick={(n) => composer.current?.set(`@${n} `)} />}
          {!current && activeProject && <ProjectHome p={activeProject} threads={threads} go={go} run={() => runProject(activeProject)}
            onBrief={(brief) => saveProject({ ...activeProject, brief })} onRemove={() => { saveProject(activeProject, true); setProject(null) }} />}
          {current && <Thread rows={rows} steps={steps} pending={pending} loading={history === null}
            onOpenFile={(p) => setSide({ kind: 'file', path: p })} onEdit={(m) => composer.current?.set(stripEmbeds(m.body))} />}
        </div>
        {note && <div className="mx-auto max-w-[760px] w-full px-6 pb-1 text-[12.5px] text-ink-dim" role="status" onClick={() => setNote('')}>{note}</div>}
        <ChatComposer ref={composer} roster={names} inChat={current ? inChat : activeProject?.agents ?? []} skills={cmds.skills} tools={cmds.tools}
          commands={commands} onSend={onSendOrCommand}
          lastMine={() => stripEmbeds([...rows].reverse().find((m) => m.from === 'owner')?.body ?? '')} />
      </main>

      {/* ── the side ─────────────────────────────────────────────────────────────────────── */}
      <AnimatePresence initial={false}>
        {side && (
          <motion.aside key={side.kind === 'file' ? side.path : 'workforce'} className="w-[380px] shrink-0 border-l border-line bg-chrome max-lg:hidden"
            initial={reduce ? false : { opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={reduce ? undefined : { opacity: 0, x: 24 }}
            transition={{ type: 'spring', visualDuration: 0.3, bounce: 0 }}>
            {side.kind === 'file'
              ? <Viewer path={side.path} onClose={() => setSide({ kind: 'workforce' })} onAttach={(u) => composer.current?.attach(u)} />
              : <Workforce agents={lanes} steps={steps} title={activeProject && !current ? `${activeProject.name}: the workforce` : 'The workforce'} />}
          </motion.aside>
        )}
      </AnimatePresence>

      {palette && <Palette threads={threads} names={names} projects={proj.projects} commands={commands} onClose={() => setPalette(false)}
        go={(t) => { setPalette(false); setProject(null); go(t) }}
        openProject={(id) => { setPalette(false); setProject(id); go(null) }}
        mention={(n) => { setPalette(false); setProject(null); go(null); composer.current?.set(`@${n} `) }} />}
      {help && <Keys onClose={() => setHelp(false)} />}
      {asking === 'project' && <NameProject onClose={() => setAsking(null)} onSave={async (name) => {
        setAsking(null)
        const id = slug(name)
        await saveProject({ id, name, brief: '', agents: inChat, threads: current ? [current] : [] })
        setProject(id); setNote(`Project "${name}" made with ${inChat.length ? inChat.map(displayName).join(', ') : 'no agents yet'}.`)
      }} />}
    </div>
  )
}

function Empty({ names, onPick }: { names: string[]; onPick: (n: string) => void }) {
  return (
    <div className="mx-auto max-w-[760px] px-6 pt-[14vh]">
      <h2 className="chat-display text-[44px] leading-[1.05] text-ink">Who should work on this?</h2>
      <p className="mt-3 text-[15px] text-ink-dim max-w-[520px]">Mention one agent, or several: they share this thread, split the work, and you watch it happen in the workforce.</p>
      <div className="mt-7 flex flex-wrap gap-2">
        {names.map((n) => (
          <button key={n} onClick={() => onPick(n)} className="inline-flex items-center gap-2 rounded-full border border-line hover:border-line-2 bg-deck-2 pl-1 pr-3 py-1 text-[13px] text-ink-dim hover:text-ink">
            <AgentFace name={n} size={22} />{displayName(n)}
          </button>
        ))}
      </div>
    </div>
  )
}

function ProjectHome({ p, threads, go, run, onBrief, onRemove }: { p: Project; threads: ThreadRow[]; go: (t: string) => void; run: () => void; onBrief: (b: string) => void; onRemove: () => void }) {
  const [brief, setBrief] = useState(p.brief)
  useEffect(() => setBrief(p.brief), [p.brief])
  return (
    <div className="mx-auto max-w-[760px] px-6 pt-12 pb-8">
      <h2 className="chat-display text-[40px] leading-[1.05]">{p.name}</h2>
      <div className="mt-3 flex items-center gap-2">
        {p.agents.map((a) => <span key={a} className="inline-flex items-center gap-1.5 text-[13px] text-ink-dim"><AgentFace name={a} size={20} />{displayName(a)}</span>)}
      </div>
      <label className="block mt-6 text-[13px] text-ink-dim" htmlFor="brief">What the project is for</label>
      <textarea id="brief" value={brief} onChange={(e) => setBrief(e.target.value)} onBlur={() => brief !== p.brief && onBrief(brief)} rows={4}
        className="mt-1.5 w-full rounded-xl bg-deck-2 border border-line focus:border-line-2 outline-none p-3 text-[14.5px] leading-relaxed" placeholder="The outcome you want, and anything the agents should know." />
      <div className="mt-4 flex items-center gap-2">
        <button onClick={run} className="rounded-lg px-3.5 py-2 text-[13.5px] font-medium bg-cyan text-on">Run the project</button>
        <span className="text-[12.5px] text-ink-mute">Its agents start working it together; you watch in the workforce.</span>
        <button onClick={onRemove} className="ml-auto text-[12.5px] text-ink-mute hover:text-bad">Remove project</button>
      </div>
      <div className="mt-8 text-[12px] text-ink-mute">Chats in this project</div>
      {p.threads.length === 0 && <div className="mt-1 text-[13px] text-ink-mute">None yet. A chat you start from here joins it.</div>}
      {p.threads.map((t) => {
        const row = threads.find((x) => x.thread === t)
        return <button key={t} onClick={() => go(t)} className="block w-full text-left mt-1 rounded-lg px-2 py-1.5 hover:bg-deck-2 text-[13.5px] text-ink truncate">{row ? stripEmbeds(row.preview) : t}</button>
      })}
    </div>
  )
}

function Palette({ threads, names, projects, commands, onClose, go, openProject, mention }: {
  threads: ThreadRow[]; names: string[]; projects: Project[]; commands: Command[]
  onClose: () => void; go: (t: string | null) => void; openProject: (id: string) => void; mention: (n: string) => void
}) {
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const items = useMemo(() => {
    const s = q.toLowerCase()
    const all = [
      ...commands.map((c) => ({ id: 'c:' + c.key, label: c.label, hint: c.hint, act: () => { onClose(); c.run('') } })),
      ...projects.map((p) => ({ id: 'p:' + p.id, label: p.name, hint: 'project', act: () => openProject(p.id) })),
      ...names.map((n) => ({ id: 'a:' + n, label: displayName(n), hint: 'start a chat with this agent', act: () => mention(n) })),
      ...threads.map((t) => ({ id: 't:' + t.thread, label: stripEmbeds(t.preview) || 'Attachment', hint: fmtAgo(t.last_ts), act: () => go(t.thread) })),
    ]
    return all.filter((i) => !s || i.label.toLowerCase().includes(s) || i.hint.toLowerCase().includes(s)).slice(0, 60)
  }, [q, threads, names, projects, commands]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setSel(0), [q])
  return (
    <div className="fixed inset-0 z-50 bg-black/40 grid place-items-start justify-center pt-[12vh] px-4" onMouseDown={onClose}>
      <div role="dialog" aria-label="jump to" className="w-full max-w-[560px] rounded-2xl border border-line bg-deck-2 shadow-2xl overflow-hidden" onMouseDown={(e) => e.stopPropagation()}>
        <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Chats, agents, projects, commands"
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)) }
            if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)) }
            if (e.key === 'Enter') { e.preventDefault(); items[sel]?.act() }
            if (e.key === 'Escape') { e.preventDefault(); onClose() }
          }}
          className="w-full bg-transparent px-4 py-3.5 text-[15px] outline-none border-b border-line" />
        <ul className="max-h-[50vh] overflow-y-auto p-1.5" role="listbox">
          {items.length === 0 && <li className="px-3 py-2 text-[13px] text-ink-mute">Nothing matches.</li>}
          {items.map((it, i) => (
            <li key={it.id} role="option" aria-selected={i === sel} onMouseEnter={() => setSel(i)} onMouseDown={(e) => { e.preventDefault(); it.act() }}
              className={`flex items-baseline gap-3 rounded-lg px-3 py-2 cursor-pointer ${i === sel ? 'bg-deck-3' : ''}`}>
              <span className="text-[13.5px] text-ink truncate">{it.label}</span>
              <span className="ml-auto text-[12px] text-ink-mute shrink-0">{it.hint}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function Keys({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/40 grid place-items-center px-4" onMouseDown={onClose}>
      <div role="dialog" aria-label="keyboard shortcuts" className="w-full max-w-[480px] rounded-2xl border border-line bg-deck-2 p-5" onMouseDown={(e) => e.stopPropagation()}>
        <div className="text-[15px] font-semibold mb-3">Keyboard</div>
        <dl className="grid grid-cols-[110px_1fr] gap-y-2 text-[13px]">
          {KEYS.flatMap(([k, v]) => [<dt key={k} className="font-mono text-ink">{k}</dt>, <dd key={k + ':d'} className="text-ink-dim">{v}</dd>])}
        </dl>
      </div>
    </div>
  )
}

function NameProject({ onClose, onSave }: { onClose: () => void; onSave: (name: string) => void }) {
  const [v, setV] = useState('')
  return (
    <div className="fixed inset-0 z-50 bg-black/40 grid place-items-start justify-center pt-[18vh] px-4" onMouseDown={onClose}>
      <form role="dialog" aria-label="new project" className="w-full max-w-[440px] rounded-2xl border border-line bg-deck-2 p-4" onMouseDown={(e) => e.stopPropagation()}
        onSubmit={(e) => { e.preventDefault(); if (v.trim()) onSave(v.trim()) }}>
        <label className="text-[13px] text-ink-dim" htmlFor="pname">Name the project. This chat and its agents join it.</label>
        <input id="pname" autoFocus value={v} onChange={(e) => setV(e.target.value)} onKeyDown={(e) => e.key === 'Escape' && onClose()} maxLength={80}
          className="mt-2 w-full rounded-lg bg-deck border border-line focus:border-line-2 outline-none px-3 py-2 text-[14.5px]" />
        <div className="mt-3 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="chat-tool">Cancel</button>
          <button type="submit" disabled={!v.trim()} className="rounded-lg px-3 py-1.5 text-[13px] font-medium bg-cyan text-on disabled:opacity-40">Make project</button>
        </div>
      </form>
    </div>
  )
}
