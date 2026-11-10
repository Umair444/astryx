import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import '@fontsource/instrument-serif/400.css'
import '@fontsource/instrument-serif/400-italic.css'
import '@fontsource-variable/newsreader'
import './workspace.css'
import { api, apiPost, displayName } from '../api'
import { useStore } from '../store'
import type { Msg, Step } from '../types'
import { canvasBase } from '../cog'
import { nowLine } from '../ui/life'
import { startDictation } from './dictate'
import {
  bodyFor, isChat, loadCommands, loadWork, loadProjects, newThread, participants, saveProjects, slug, stepsOf, stripEmbeds,
  type McpTool, type Project, type Projects, type Skill, type Uploaded, type Work,
} from './model'
import {
  deskAgent, deskThread, liveAgentOf, loadWsAgents, saveThreadMeta, statusOf, surfaceOf, useNow, useWsThreads,
  type Status, type WsAgent, type WsThread,
} from './data'
import AgentRail, { Presence } from './shell/AgentRail'
import ConversationList from './shell/ConversationList'
import TopBar from './shell/TopBar'
import { Keys, NameProject, Palette } from './shell/Dialogs'
import Composer, { type Command, type ComposerHandle } from './thread/Composer'
import Turns from './thread/Turns'
import { plainLine, type Pending } from './thread/LiveActivity'
import TeamHome from './empty/TeamHome'
import ProjectHome from './empty/ProjectHome'
import Workforce from './shell/Workforce'
import Panel, { type Layout } from './artifacts/Panel'
import { usePanel } from './artifacts/usePanel'
import MediaDrawer from './artifacts/MediaDrawer'
import { distinctMedia, loadMedia, mediaOfRows, type MediaItem } from './artifacts/api'
import type { OpenRequest } from './artifacts/FileChip'
import { I } from './icons'

/* /chat, the WORKSPACE (plan-11884; rebuilt on feat/chat-workspace after homes/seed/chat-rebuild/DESIGN.md). Four
   columns: the AGENT RAIL (who is here, who is working), the CONVERSATION LIST (every conversation the owner has with
   agents, from any surface: /api/ws/threads), the CONVERSATION (one wire thread, flat turns, the live activity line,
   the composer), and beside it the ARTIFACT PANEL (the files this conversation made, with their versions) or the
   WORKFORCE (its agents at work); the MEDIA DRAWER lists every file in the thread. This file only wires state to those
   modules: the data lives in data.ts/model.ts, the look in shell/, thread/, artifacts/, empty/ and workspace.css.
   Everything is on a key. */

/* the window's width, for the layouts DESIGN.md names (the panel inline ≥1200, a sheet below, the screen on a phone) */
function useWidth() {
  const [w, setW] = useState(() => innerWidth)
  useEffect(() => { const f = () => setW(innerWidth); addEventListener('resize', f); return () => removeEventListener('resize', f) }, [])
  return w
}

export default function ChatApp({ thread, go: nav }: { thread: string | null; go: (t: string | null) => void }) {
  const { agents: roster, messages, presence, send, who } = useStore()
  const reduce = useReducedMotion()
  const now = useNow(5000)
  // the rail's order: seed first, then the agents/ tree as /api/agents lists it
  const names = useMemo(() => {
    const all = roster.map((a) => a.agent)
    return [...all.filter((a) => a === 'seed'), ...all.filter((a) => a !== 'seed')]
  }, [roster])
  const status = useMemo(() => {
    const out: Record<string, Status> = {}
    for (const n of names) out[n] = statusOf(roster.find((r) => r.agent === n), presence[n], now)
    return out
  }, [names, roster, presence, now])
  const lines = useMemo(() => {
    const out: Record<string, string> = {}
    for (const a of roster) if (status[a.agent] !== 'down') out[a.agent] = plainLine(nowLine(a, presence[a.agent], status[a.agent] === 'working' ? 'working' : 'awake', now).line)
    return out
  }, [roster, presence, status, now])

  const { threads, loaded, reload, patch } = useWsThreads(messages)
  const [team, setTeam] = useState<WsAgent[]>([])
  const [history, setHistory] = useState<Msg[] | null>(null)
  const [steps, setSteps] = useState<Record<string, Step[]>>({})
  const [work, setWork] = useState<Work | null>(null)
  const [workforce, setWorkforce] = useState(false)
  const [filesOpen, setFilesOpen] = useState(false)
  const [media, setMedia] = useState<MediaItem[] | null>(null)
  const [dirty, setDirty] = useState(false)
  const winW = useWidth()
  const [drawer, setDrawer] = useState(false)
  const [palette, setPalette] = useState(false)
  const [help, setHelp] = useState(false)
  const [cmds, setCmds] = useState<{ skills: Skill[]; tools: McpTool[] }>({ skills: [], tools: [] })
  const [proj, setProj] = useState<Projects>({ etag: '', projects: [] })
  const [project, setProject] = useState<string | null>(null)
  const [asking, setAsking] = useState<null | 'project'>(null)
  const [note, setNote] = useState('')
  const composer = useRef<ComposerHandle>(null)
  const current = thread ?? ''
  const panel = usePanel(current)
  const go = useCallback((t: string | null) => { setDrawer(false); nav(t) }, [nav])

  useEffect(() => { loadCommands().then(setCmds); loadProjects().then(setProj).catch(() => {}); loadWsAgents().then(setTeam).catch(() => {}) }, [])

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

  // the thread's files: the store's list (GET /api/ws/media), else the embeds in the rows; refreshed as the thread moves
  const rowsRef = useRef(rows)
  rowsRef.current = rows
  useEffect(() => {
    let live = true
    if (!current) { setMedia([]); return }
    loadMedia(current, rowsRef.current).then((m) => live && setMedia(distinctMedia(m))).catch(() => live && setMedia(distinctMedia(mediaOfRows(rowsRef.current))))
    return () => { live = false }
  }, [current, newest])
  useEffect(() => { setMedia(null) }, [current])

  // the open conversation's row; a thread with no rows yet (a fresh desk) gets a provisional one, so it is never
  // missing from the list while it is open
  const listed = threads.find((t) => t.thread === current) ?? null
  const currentRow: WsThread | null = useMemo(() => {
    if (!current) return null
    if (listed) return listed
    const desk = deskAgent(current, names)
    return {
      thread: current, title: desk ? `Desk with ${displayName(desk)}` : 'New chat', custom_title: false, agents: desk ? [desk] : [],
      surface: surfaceOf(current), last_ts: new Date().toISOString(), preview: '', last_from: null, count: 0, pinned: false, project: null,
    }
  }, [current, listed, names])
  const listThreads = useMemo(() => (currentRow && !listed ? [currentRow, ...threads] : threads), [currentRow, listed, threads])

  const activeProject = proj.projects.find((p) => p.id === project) ?? null
  // who a message goes to: the thread's own agents (a desk's agent, a canvas chat's agent), then anyone who spoke;
  // a new chat defaults to seed, the owner's line to the org (an @mention always overrides)
  const inChat = useMemo(() => {
    const out = [...(currentRow?.agents ?? [])]
    for (const a of participants(rows, names)) if (!out.includes(a)) out.push(a)
    return out
  }, [currentRow, rows, names])
  const recipients = current ? inChat : activeProject ? activeProject.agents : names.includes('seed') ? ['seed'] : []
  const lanes = activeProject && !current ? activeProject.agents : inChat

  // D4: in a chat, the work comes filed by turn (/api/chat/work), refetched when the thread moves or one of its
  // agents does; a project's lanes (no thread open) show each agent's recent steps from any thread
  const pulse = roster.filter((a) => lanes.includes(a.agent)).map((a) => `${a.agent}:${a.steps}`).join(',')
  useEffect(() => {
    let live = true
    if (current) loadWork(current).then((w) => live && setWork(w)).catch(() => {})
    else for (const a of lanes) stepsOf(a).then((s) => live && setSteps((cur) => ({ ...cur, [a]: s }))).catch(() => {})
    return () => { live = false }
  }, [pulse, current, newest]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setWork(null) }, [current])
  const laneSteps = useMemo(() => {
    if (!current) return steps
    const out: Record<string, Step[]> = {}
    for (const a of lanes) {
      const filed = (work?.turns ?? []).filter((t) => t.agent === a).at(-1)?.steps ?? []
      out[a] = [...filed, ...(work?.live[a] ?? [])]
    }
    return out
  }, [current, steps, work, lanes.join(',')]) // eslint-disable-line react-hooks/exhaustive-deps

  // asked and not yet answered: an agent whose newest row here is older than the owner's newest row to it; its
  // live steps since the ask feed the activity line
  const pending: Pending[] = useMemo(() => {
    const out: Pending[] = []
    for (const a of inChat) {
      const ask = [...rows].reverse().find((m) => m.from === 'owner' && m.to === a)
      const saidAt = Math.max(0, ...rows.filter((m) => m.from === a).map((m) => m.id))
      if (ask && ask.id > saidAt) out.push({ agent: a, since: ask.ts, steps: (work?.live[a] ?? []).filter((s) => Date.parse(s.ts) >= Date.parse(ask.ts)) })
    }
    return out
  }, [inChat, rows, work])

  // a conversation is LIVE while one of its agents works on it
  const live = useMemo(() => {
    const out: Record<string, string> = {}
    for (const t of listThreads) { const a = liveAgentOf(t, status, presence); if (a) out[t.thread] = a }
    for (const p of pending) if (status[p.agent] === 'working' && current) out[current] = p.agent
    return out
  }, [listThreads, status, presence, pending, current])

  async function onSend(text: string, files: Uploaded[], to: string[]) {
    const t = current || newThread()
    const body = [text, ...files.map((f) => `[[file:${f.path}]] (${f.name})`)].filter(Boolean).join('\n')
    for (const a of to) await send(a, bodyFor(body, to, a), t)        // R4: one row per recipient, one thread
    if (!current) go(t)
    if (activeProject && isChat(t) && !activeProject.threads.includes(t)) await saveProject({ ...activeProject, threads: [...activeProject.threads, t] })
    reload()
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
    go(t); setWorkforce(true)
  }

  // a title or a pin: optimistic on the row, then the server's list
  async function setMeta(t: WsThread, p: { title?: string; pinned?: boolean }) {
    patch(t.thread, { ...(p.pinned !== undefined ? { pinned: p.pinned } : {}), ...(p.title ? { title: p.title, custom_title: true } : {}) })
    try { await saveThreadMeta(t.thread, p) } catch (e) { setNote(String((e as Error).message)) }
    reload()
  }

  const openAgent = (a: string) => { setProject(null); go(deskThread(a)) }
  const newChat = () => { setProject(null); go(null); requestAnimationFrame(() => composer.current?.focus()) }

  const commands: Command[] = [
    { key: 'new', label: 'New chat', hint: 'start an empty chat', run: newChat },
    { key: 'project', label: 'Make this a project', hint: 'name it; its agents work it together', run: () => { setAsking('project') } },
    { key: 'run', label: 'Run the project', hint: 'its agents start working it on their own', run: () => (activeProject ? void runProject(activeProject) : 'Open a project first (⌘K).') },
    { key: 'workforce', label: 'Workforce', hint: 'show the agents at work', run: () => setWorkforce(true) },
    { key: 'files', label: 'Files', hint: 'every file in this conversation (⌘⇧E)', run: () => setFilesOpen(true) },
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
  const chatIds = listThreads.map((t) => t.thread)
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      const typing = (e.target as HTMLElement)?.closest('textarea, input')
      if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette((p) => !p); return }
      if (mod && e.shiftKey && e.key.toLowerCase() === 'o') { e.preventDefault(); newChat(); return }
      if (mod && e.key.toLowerCase() === 'j') { e.preventDefault(); setWorkforce((w) => !w); return }
      if (mod && e.shiftKey && e.key.toLowerCase() === 'e') { e.preventDefault(); setFilesOpen((f) => !f); return }
      if (mod && e.key === '/') { e.preventDefault(); setHelp((h) => !h); return }
      if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
        e.preventDefault()
        const i = chatIds.indexOf(current), j = e.key === 'ArrowUp' ? i - 1 : i + 1
        if (chatIds[j]) go(chatIds[j])
        return
      }
      if (e.key === 'Escape') {
        if (palette) setPalette(false); else if (help) setHelp(false); else if (drawer) setDrawer(false)
        else if (filesOpen) setFilesOpen(false); else if (workforce) setWorkforce(false)
        else if (panel.tabs.length && !typing && !dirty) panel.closeAll()
        return
      }
      if (!typing && !mod && e.key === '/') { e.preventDefault(); composer.current?.focus(); composer.current?.set('/') }
    }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [palette, help, workforce, filesOpen, drawer, current, dirty, panel.tabs.length, chatIds.join('|')]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!who.owner) return (
    <div className="ws h-dvh grid place-items-center ws-backdrop text-ink p-8">
      <div className="max-w-sm text-center">
        <div className="ws-display text-[40px] leading-none">Chat is for the owner</div>
        <p className="mt-3 text-ink-dim text-[14px]">Sign in on the floor first, then come back here.</p>
        <a href="#/" className="ws-btn mt-6">Go to the floor</a>
      </div>
    </div>
  )

  const roles = Object.fromEntries(team.map((a) => [a.agent, a.role]))
  const title = currentRow?.title ?? (activeProject ? activeProject.name : 'New chat')
  const box = (hero: boolean) => (
    <Composer ref={composer} hero={hero} roster={names} inChat={recipients} skills={cmds.skills} tools={cmds.tools}
      commands={commands} onSend={onSendOrCommand}
      placeholder={hero ? 'Ask the team anything. @mention who should take it; seed routes the rest.' : undefined}
      lastMine={() => stripEmbeds([...rows].reverse().find((m) => m.from === 'owner')?.body ?? '')} />
  )
  const list = (phone: boolean) => (
    <ConversationList threads={listThreads} loaded={loaded} current={current || null} live={live} projects={proj.projects} project={project}
      onGo={(t) => { setProject(null); go(t) }} onNew={newChat}
      onProject={(id) => { setProject(id); go(null) }}
      onPin={(t) => setMeta(t, { pinned: !t.pinned })} onRename={(t, title) => setMeta(t, { title })}
      onClose={phone ? () => setDrawer(false) : undefined}
      className={phone ? '!w-[86vw] max-w-[340px]' : `max-md:hidden ${showPanel && layout === 'inline' && winW < 1440 ? '!hidden' : ''}`} />
  )
  const home = !current && !activeProject
  const layout: Layout = winW >= 1200 ? 'inline' : winW >= 768 ? 'sheet' : 'full'
  const showPanel = !!current && panel.tabs.length > 0 && !workforce
  const files = media ?? []
  const openFile = (r: OpenRequest) => { setWorkforce(false); panel.open(r); if (winW < 1200) setFilesOpen(false) }
  return (
    <div className="ws h-dvh flex ws-backdrop text-ink overflow-hidden">
      <AgentRail agents={names} status={status} lines={lines} current={current || null} onPick={openAgent}
        onHome={() => { setProject(null); go(null) }} onPalette={() => setPalette(true)} onKeys={() => setHelp(true)} />
      {list(false)}

      {/* ── the conversation, and beside it the artifact panel ─────────────────────────────── */}
      <div className="flex-1 min-w-0 flex">
      <main className="flex-1 min-w-[420px] max-md:min-w-0 flex flex-col relative">
        {home ? (
          <div className="h-12 shrink-0 flex items-center px-3 md:hidden">
            <button className="ws-icon" onClick={() => setDrawer(true)} aria-label="conversations">{I.menu()}</button>
          </div>
        ) : (
          <TopBar title={title} canRename={!!currentRow} surface={currentRow?.surface ?? null}
            project={(currentRow?.project && proj.projects.find((p) => p.id === currentRow.project)?.name) || (activeProject && !current ? 'Projects' : null)}
            agents={current ? inChat : activeProject?.agents ?? []} status={status} workforce={workforce}
            files={files.length} media={filesOpen}
            onRename={(t) => currentRow && setMeta(currentRow, { title: t })}
            onWorkforce={() => setWorkforce((w) => !w)} onMedia={() => setFilesOpen((f) => !f)}
            onMenu={() => setDrawer(true)} onAgent={openAgent} />
        )}
        <div className="flex-1 min-h-0 overflow-y-auto">
          {home && <TeamHome names={names} status={status} lines={lines} agents={team} threads={threads} composer={box(true)} onAgent={openAgent} onGo={go} />}
          {!current && activeProject && <ProjectHome p={activeProject} threads={threads} go={go} run={() => runProject(activeProject)}
            onBrief={(brief) => saveProject({ ...activeProject, brief })} onRemove={() => { saveProject(activeProject, true); setProject(null) }} />}
          {current && <Turns rows={rows} work={work} pending={pending} roster={names} roles={roles} loading={history === null}
            onOpenFile={openFile} onEdit={(m) => composer.current?.set(stripEmbeds(m.body))}
            empty={<FreshThread agents={inChat} status={status} roles={roles} lines={lines} />} />}
        </div>
        {note && <div className="mx-auto max-w-[760px] w-full px-6 pb-1 text-[12.5px] text-ink-dim cursor-pointer" role="status" onClick={() => setNote('')}>{note}</div>}
        {!home && box(false)}

        {/* the media drawer: over the conversation's right edge, under the top bar (the whole screen on a phone) */}
        <AnimatePresence>
          {filesOpen && current && (
            <motion.div key="files" className="absolute right-0 top-12 bottom-0 z-20 w-[360px] max-w-full max-md:fixed max-md:inset-0 max-md:w-full max-md:z-50"
              initial={reduce ? false : { opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} exit={reduce ? undefined : { opacity: 0, x: 16 }}
              transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}>
              <MediaDrawer items={files} loading={media === null} onOpen={openFile} onClose={() => setFilesOpen(false)}
                openKey={showPanel ? panel.active : null} />
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {showPanel && <Panel panel={panel} layout={layout} onAttach={(u) => composer.current?.attach(u)} onDirty={setDirty} />}
      </div>

      {/* ── the workforce ────────────────────────────────────────────────────────────────── */}
      <AnimatePresence initial={false}>
        {workforce && (
          <motion.aside key="workforce" className="ws-chrome w-[380px] shrink-0 border-l border-line max-lg:hidden"
            initial={reduce ? false : { opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={reduce ? undefined : { opacity: 0, x: 24 }}
            transition={{ type: 'spring', visualDuration: 0.22, bounce: 0 }}>
            <Workforce agents={lanes} steps={laneSteps} unlinked={current ? work?.unlinked ?? {} : {}} title={activeProject && !current ? `${activeProject.name}: the workforce` : 'The workforce'} />
          </motion.aside>
        )}
      </AnimatePresence>

      {/* ── the phone drawer: the agent strip and the list ──────────────────────────────── */}
      <AnimatePresence>
        {drawer && (
          <motion.div className="fixed inset-0 z-40 md:hidden flex" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
            <motion.div className="h-full flex flex-col bg-[var(--t-bg2)] shadow-2xl" initial={reduce ? false : { x: -40 }} animate={{ x: 0 }} exit={reduce ? undefined : { x: -40 }} transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}>
              <div className="flex gap-1.5 px-3 pt-3 pb-1 overflow-x-auto w-[86vw] max-w-[340px]" aria-label="agents">
                {names.map((a) => <button key={a} onClick={() => openAgent(a)} aria-label={`open a chat with ${displayName(a)}`} className="shrink-0 p-1 rounded-xl" style={{ ['--ws-pip-bg' as string]: 'var(--t-bg2)' }}><Presence agent={a} status={status[a]} size={34} /></button>)}
              </div>
              <div className="flex-1 min-h-0 flex">{list(true)}</div>
            </motion.div>
            <div className="flex-1 ws-scrim" onClick={() => setDrawer(false)} />
          </motion.div>
        )}
      </AnimatePresence>

      {palette && <Palette threads={listThreads} names={names} status={status} projects={proj.projects} commands={commands} onClose={() => setPalette(false)}
        go={(t) => { setPalette(false); setProject(null); go(t) }}
        openProject={(id) => { setPalette(false); setProject(id); go(null) }}
        openAgent={(n) => { setPalette(false); openAgent(n) }} />}
      {help && <Keys onClose={() => setHelp(false)} />}
      {asking === 'project' && <NameProject onClose={() => setAsking(null)} onSave={async (name) => {
        setAsking(null)
        const id = slug(name)
        await saveProject({ id, name, brief: '', agents: inChat, threads: isChat(current) ? [current] : [] })
        setProject(id); setNote(`Project "${name}" made with ${inChat.length ? inChat.map(displayName).join(', ') : 'no agents yet'}.`)
      }} />}
    </div>
  )
}

/* a conversation with nobody's words in it yet (a fresh desk): who you're talking to, and what they're doing */
function FreshThread({ agents, status, roles, lines }: { agents: string[]; status: Record<string, Status>; roles: Record<string, string>; lines: Record<string, string> }) {
  const a = agents[0]
  if (!a) return <div className="pt-[12vh] text-center text-[14px] text-ink-mute">Mention an agent with @ to start.</div>
  return (
    <div className="pt-[12vh] flex flex-col items-center text-center" style={{ ['--ws-pip-bg' as string]: 'var(--t-bg)' }}>
      <Presence agent={a} status={status[a]} size={56} />
      <div className="ws-display text-[40px] leading-none mt-4 text-ink">{displayName(a)}</div>
      {roles[a] && <div className="mt-2 text-[14px] text-ink-dim max-w-[440px]">{roles[a]}</div>}
      {lines[a] && <div className="mt-3 text-[12.5px] text-ink-mute max-w-[460px] line-clamp-2">{status[a] === 'working' ? 'Working now: ' : 'Last: '}{lines[a]}</div>}
    </div>
  )
}
