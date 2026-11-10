import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import '@fontsource/instrument-serif/400.css'
import '@fontsource/instrument-serif/400-italic.css'
import '@fontsource-variable/newsreader'
import './workspace.css'
import './presence.css'
import { api, apiPost, displayName } from '../api'
import { mergeMsgs, useStore } from '../store'
import type { Msg, Step } from '../types'
import { canvasBase } from '../cog'
import { nowLine } from '../ui/life'
import { startDictation } from './dictate'
import {
  bodyFor, loadCommands, loadWork, newThread, participants, stepsOf, stripEmbeds,
  type McpTool, type Project, type Skill, type Uploaded, type Work,
} from './model'
import {
  deskAgent, deskThread, liveAgentOf, loadWsAgents, saveThreadMeta, statusOf, surfaceOf, useNow, useWsThreads,
  type Status, type WsAgent, type WsThread,
} from './data'
import AgentRail, { Presence } from './shell/AgentRail'
import ConversationList from './shell/ConversationList'
import TopBar from './shell/TopBar'
import ConnStatus from './shell/ConnStatus'
import { Keys, Palette } from './shell/Dialogs'
import Composer, { type Command, type ComposerHandle } from './thread/Composer'
import Turns from './thread/Turns'
import { plainLine, type Pending } from './thread/LiveActivity'
import TeamHome from './empty/TeamHome'
import { useVisit } from './empty/visit'
import type { BriefingActions } from './empty/Briefing'
import type { Feature } from './empty/WhatsNew'
import NewProject from './projects/NewProject'
import { blank, moveThread, nextColor, patchOne, projectOf, removeOne, upsert, useProjects } from './projects/model'
import { projectContext } from './projects/context'
import type { View } from './projects/Sidebar'
import Workforce from './shell/Workforce'
import Panel, { type Layout } from './artifacts/Panel'
import { usePanel } from './artifacts/usePanel'
import MediaDrawer from './artifacts/MediaDrawer'
import { byId, createArtifact, distinctMedia, loadMedia, mediaOfRows, openArtifact, type MediaItem } from './artifacts/api'
import { preferChart } from './tables/DataView'
import { ChipCtx, useChipAwareness } from './artifacts/versions/awareness'
import { quoteText, TurnActionsCtx, type TurnActionsValue } from './thread/TurnActions'
import Outbox, { type Outgoing } from './thread/Outbox'
import type { OpenRequest } from './artifacts/FileChip'
import type { AnnotateCtx } from './artifacts/annotate/types'
import type { ParsedAsk } from './artifacts/annotate/ask'
import { I } from './icons'
import type { Jump, MessageHit } from './search'
import { friendly, toast } from './toast'

// the library and the project pages load on first visit (their own chunk); the sidebar's project rows are eager
const Library = lazy(() => import('./library/Library'))
const ProjectHome = lazy(() => import('./projects/ProjectHome'))
const ProjectsIndex = lazy(() => import('./projects/ProjectsIndex'))
// iteration 13: a painted canvas in the panel, and Talk (canvas's voice mode): their own chunks, loaded on first use
const CanvasPanel = lazy(() => import('./canvas/CanvasPanel'))
const TalkMode = lazy(() => import('./talk/TalkMode'))
import { canvasIdOf, useCanvases } from './canvas/api'
import { interruptAgent, loadHandoffs, useTabTitle, useUnread, type Handoff } from './live'
import ListSeam, { useListWidth } from './shell/ListSeam'
import MoreMenu from './shell/MoreMenu'
import { NotifyPrompt, useReplyNotifications } from './shell/notify'
import { useInstallable } from './shell/pwa'
import { exportConversation } from './thread/exportMd'

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
  const { agents: roster, messages, presence, send, who, conn } = useStore()
  const reduce = useReducedMotion()
  const now = useNow(5000)
  // the rail's order: seed first, then by name. STABLE on purpose (iteration 10): /api/agents lists by latest step, so
  // following it reshuffled the rail every time someone worked, and a face never stayed where the hand remembers it
  // keyed on the NAMES, not the roster rows: a step event freshens a row, and must not hand every view a new list
  // (iteration 14: that re-rendered the whole open thread once per step)
  const nameKey = roster.map((a) => a.agent).sort().join(',')
  const names = useMemo(() => {
    const all = nameKey ? nameKey.split(',') : []
    return [...all.filter((a) => a === 'seed'), ...all.filter((a) => a !== 'seed')]
  }, [nameKey])
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
  useEffect(() => { if (conn.resync) reload() }, [conn.resync, reload])     // back from a lost stream: the list catches up
  // iteration 9: an agent's reply while the tab is hidden → an OS notification (opt-in; name + title only); the chat
  // is installable (manifest + icons in <head> only while it is on screen)
  useReplyNotifications(messages, threads, names, useCallback((t: string) => nav(t), [nav]))
  useInstallable()
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
  const [asking, setAsking] = useState<null | 'project' | 'new'>(null)
  const [note, setNote] = useState('')
  // iteration 5: the route also names the workspace's own pages — #/chat/library, #/chat/projects, #/chat/project:<id>
  const proj = useProjects(setNote)
  const view: View = thread === 'library' ? 'library' : thread === 'projects' ? 'projects' : thread?.startsWith('project:') ? 'project' : 'thread'
  const project = view === 'project' ? thread!.slice(8) : null
  const [listFilter, setListFilter] = useState<string | null>(null)     // the list focused on one project's conversations
  const [annFocus, setAnnFocus] = useState<AnnotateCtx['focus']>(null)
  // iteration 13: the painted canvas open in the panel (a canvas's conversation, the library, ⌘K), and Talk
  const canvases = useCanvases()
  const [canvasOpen, setCanvasOpen] = useState<number | null>(null)
  const canvasNext = useRef<number | null>(null)               // ⌘K: open this canvas once its conversation is on screen
  const [talk, setTalk] = useState<{ agent: string; thread: string } | null>(null)
  const composer = useRef<ComposerHandle>(null)
  const current = view === 'thread' ? thread ?? '' : ''
  const panel = usePanel(view === 'thread' ? current : thread ?? '')    // the library and a project keep their own tabs
  const go = useCallback((t: string | null) => { setDrawer(false); nav(t) }, [nav])
  // a canvas belongs to where it was opened: moving to another conversation or page closes it
  useEffect(() => { setCanvasOpen(canvasNext.current); canvasNext.current = null }, [thread])
  // iteration 15: the owner's visit (what "while you were away" covers), and a file the briefing opens once its
  // conversation (or the library) is on screen, in THAT page's panel
  const visit = useVisit()
  const fileNext = useRef<{ at: string; req: OpenRequest } | null>(null)
  // a search hit opens its conversation AT that message (thread/focus.ts scrolls to it and pulses it once)
  const [jump, setJump] = useState<Jump | null>(null)
  const onJump = useCallback((h: MessageHit) => { setPalette(false); setJump({ thread: h.thread, id: h.msg_id, n: Date.now() }); go(h.thread) }, [go])

  useEffect(() => { loadCommands().then(setCmds); loadWsAgents().then(setTeam).catch(() => {}) }, [])

  // the thread: its history once, then the live feed, merged by id
  // a history that failed to load is SAID, and retried: shown as an empty thread it read as a conversation that had
  // only its last few live rows (iteration 11, the API down mid-session)
  const [histErr, setHistErr] = useState(false)
  const [histTry, setHistTry] = useState(0)
  const histFor = useRef('')
  useEffect(() => {
    if (!current) { histFor.current = ''; setHistory([]); setHistErr(false); return }
    let live = true
    const fresh = histFor.current !== current
    if (fresh) { histFor.current = current; setHistory(null); setOlder(false) }    // a retry keeps what's shown
    api<Msg[]>(`/messages?thread=${encodeURIComponent(current)}&limit=500`)
      .then((h) => { if (live) { setHistory((cur) => mergeMsgs(cur ?? [], h)); if (fresh) setOlder(h.length >= 500); setHistErr(false) } })
      .catch(() => { if (live) { setHistory((cur) => cur ?? []); setHistErr(true) } })
    return () => { live = false }
  }, [current, histTry])
  // STAMINA (iteration 14): back from a lost stream (a laptop that slept, a dropped network, the API restarted), the
  // open thread fetches what it missed, every row past the newest it holds, paged; merged by id so nothing doubles
  const histRef = useRef<Msg[] | null>(null)
  histRef.current = history
  useEffect(() => {
    if (!conn.resync || !current) return
    const have = histRef.current
    if (!have || histErr) { setHistTry((n) => n + 1); return }
    let live = true
    ;(async () => {
      let after = have.length ? have[have.length - 1].id : 0
      for (let page = 0; page < 10; page++) {
        const got = await api<Msg[]>(`/messages?thread=${encodeURIComponent(current)}&after_id=${after}&limit=500`)
        if (!live) return
        if (got.length) setHistory((cur) => mergeMsgs(cur ?? [], got))
        if (got.length < 500) break
        after = got[got.length - 1].id
      }
    })().catch(() => { if (live) setHistTry((n) => n + 1) })
    return () => { live = false }
  }, [conn.resync]) // eslint-disable-line react-hooks/exhaustive-deps
  // a thread longer than one page: its older rows load a page at a time when "Show earlier" reaches the top
  const [older, setOlder] = useState(false)
  const loadOlderRows = useCallback(async () => {
    const have = histRef.current
    if (!current || !have?.length) return
    const got = await api<Msg[]>(`/messages?thread=${encodeURIComponent(current)}&before_id=${have[0].id}&limit=500`).catch(() => null)
    if (!got) return
    if (histFor.current !== current) return
    setOlder(got.length >= 500)
    if (got.length) setHistory((cur) => mergeMsgs(cur ?? [], got))
  }, [current])
  useEffect(() => { setHistErr(false) }, [current])
  useEffect(() => {
    if (!histErr) return
    const t = setTimeout(() => setHistTry((n) => n + 1), 5000)
    return () => clearTimeout(t)
  }, [histErr, histTry])
  // the SAME array while this thread's rows are unchanged: a row on another thread (most of the wire) must not re-render
  // the conversation, re-run its blocks, or refetch its files (iteration 14)
  const rowsPrev = useRef<Msg[]>([])
  const rows = useMemo(() => {
    const by = new Map<number, Msg>()
    for (const m of history ?? []) by.set(m.id, m)
    for (const m of messages) if (m.thread === current && !by.has(m.id)) by.set(m.id, m)
    const next = [...by.values()].sort((a, b) => a.id - b.id)
    const prev = rowsPrev.current
    if (prev.length === next.length && next.every((m, i) => prev[i] === m)) return prev
    rowsPrev.current = next
    return next
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
  // iteration 7: a chip knows its version ("v3 · updated"); the stored list refreshes when a panel tab's head moves
  const openRef = useRef<(r: OpenRequest) => void>(() => {})
  const chipAware = useChipAwareness(current, rows, panel.tabs.map((t) => t.art?.head ?? '').join(','), useCallback((r: OpenRequest) => openRef.current(r), []))
  useEffect(() => {          // the briefing's file, once its page is the one on screen (openRef = this render's openFile)
    const f = fileNext.current
    if (f && f.at === (thread ?? '')) { fileNext.current = null; openRef.current(f.req) }
  }, [thread])
  // the owner's messages on their way: shown at once, kept with Retry when a send fails (thread/Outbox.tsx)
  const [outbox, setOutbox] = useState<Outgoing[]>([])

  // the open conversation's row; a thread with no rows yet (a fresh desk) gets a provisional one, so it is never
  // missing from the list while it is open
  const listed = threads.find((t) => t.thread === current) ?? null
  const currentRow: WsThread | null = useMemo(() => {
    if (!current) return null
    if (listed) return listed
    const desk = deskAgent(current, names)
    // the server names a conversation by the owner's first line (workspace.derive_title); until its list catches up
    // (a fresh chat, the moment after the first send), name it the same way here instead of "New chat"
    const first = stripEmbeds(rows.find((m) => m.from === 'owner')?.body ?? '').split('\n').find((l) => l.trim())?.replace(/\s+/g, ' ').trim() ?? ''
    const said = first.length > 80 ? `${first.slice(0, 79)}…` : first
    return {
      thread: current, title: said || (desk ? `Desk with ${displayName(desk)}` : 'New chat'), custom_title: false, agents: desk ? [desk] : participants(rows, names),
      surface: surfaceOf(current), last_ts: new Date().toISOString(), preview: '', last_from: null, count: 0, pinned: false, project: null,
    }
  }, [current, listed, names, rows])
  const listThreads = useMemo(() => (currentRow && !listed ? [currentRow, ...threads] : threads), [currentRow, listed, threads])
  // replies the owner hasn't opened (per browser), and the tab's "(n) Chat · astryx"
  const unread = useUnread(threads, current || null)
  useTabTitle(unread.size)
  const listW = useListWidth()

  const activeProject = proj.projects.find((p) => p.id === project) ?? null
  // who a message goes to: the thread's own agents (a desk's agent, a canvas chat's agent), then anyone who spoke;
  // a new chat defaults to seed, the owner's line to the org (an @mention always overrides)
  const inChat = useMemo(() => {
    const out = [...(currentRow?.agents ?? [])]
    for (const a of participants(rows, names)) if (!out.includes(a)) out.push(a)
    return out
  }, [currentRow, rows, names])
  const seedOnly = names.includes('seed') ? ['seed'] : []
  const recipients = current ? inChat : activeProject?.agents.length ? activeProject.agents : seedOnly
  const lanes = activeProject && !current ? activeProject.agents : inChat
  // Talk: with the agent this box writes to, on this conversation (a new one from the home or a project page)
  const openTalk = (agent?: string) => {
    const a = agent ?? recipients[0]
    if (!a) { setNote('Mention an agent with @ first: Talk speaks with one agent.'); return }
    setTalk({ agent: a, thread: current || newThread() })
  }
  const talkRows = useMemo(() => (!talk ? [] : talk.thread === current ? rows : messages.filter((m) => m.thread === talk.thread)), [talk, current, rows, messages])

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
  // handoffs INTO this conversation (a turn answering here, started by another agent's message elsewhere)
  const [handoffs, setHandoffs] = useState<Handoff[]>([])
  useEffect(() => {
    let live = true
    if (!current) { setHandoffs([]); return }
    loadHandoffs(current).then((h) => live && setHandoffs(h)).catch(() => live && setHandoffs([]))
    return () => { live = false }
  }, [current, newest])
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

  // one outgoing message to its remaining recipients; a failure keeps it, naming who it did not reach
  async function deliver(o: Outgoing) {
    setOutbox((xs) => xs.map((x) => (x.key === o.key ? { ...x, failed: null } : x)))
    const left = [...o.to]
    try {
      for (const a of o.to) { await send(a, await o.body(a), o.thread); left.shift() }
      setOutbox((xs) => xs.filter((x) => x.key !== o.key))
      reload()
    } catch (e) {
      setOutbox((xs) => xs.map((x) => (x.key === o.key ? { ...x, to: left, failed: friendly(e, 'This message') } : x)))   // the toasts' wording (chat/toast.tsx)
    }
  }
  async function onSend(text: string, files: Uploaded[], to: string[]) {
    if (current) {             // an open conversation: optimistic, never blocking the composer
      const body = [text, ...files.map((f) => `[[file:${f.path}]] (${f.name})`)].filter(Boolean).join('\n')
      const pj = projectOf(current, proj.projects)
      const ctx = pj && !rows.some((m) => m.from === 'owner') ? projectContext(pj) : Promise.resolve('')
      const o: Outgoing = { key: `o${Date.now()}${Math.random()}`, thread: current, text, files, to: [...to], failed: null, body: async (a) => (await ctx) + bodyFor(body, to, a) }
      setOutbox((xs) => [...xs, o])
      void deliver(o)
      return
    }
    const t = current || newThread()
    const body = [text, ...files.map((f) => `[[file:${f.path}]] (${f.name})`)].filter(Boolean).join('\n')
    // a project chat's FIRST message carries the project's instructions and files (projects/context.ts)
    const pj = !current && activeProject ? activeProject : projectOf(t, proj.projects)
    const ctx = pj && (!current || !rows.some((m) => m.from === 'owner')) ? await projectContext(pj) : ''
    for (const a of to) await send(a, ctx + bodyFor(body, to, a), t)        // R4: one row per recipient, one thread
    if (!current && activeProject) await proj.mutate(moveThread(t, activeProject.id))
    if (!current) go(t)
    reload()
  }

  async function runProject(p: Project) {
    if (!p.agents.length) { setNote('Add agents to the project’s team first.'); return }
    const t = `chat:project-${p.id}`
    const ctx = await projectContext(p)
    const kick = `Project "${p.name}" is running.\nWork it together and autonomously: split it between you, say who takes what on this thread, and post progress and results here as you go. Ask me only what you can't decide.`
    for (const a of p.agents) await send(a, ctx + bodyFor(kick, p.agents, a), t)
    if (!p.threads.includes(t)) await proj.mutate(moveThread(t, p.id))
    go(t); setWorkforce(true)
  }
  const openProject = (id: string) => go(`project:${id}`)
  // a stored artifact (the library, a project's files) opens by id in this page's own panel: nothing re-imports
  const openStored = (id: string, it: { name: string; author: string }) => { setWorkforce(false); panel.open({ path: byId(id), label: it.name, from: it.author }) }
  const storedActive = panel.active?.startsWith('art:') ? panel.active.slice(4) : null

  // a title or a pin: optimistic on the row, then the server's list
  async function setMeta(t: WsThread, p: { title?: string; pinned?: boolean }) {
    patch(t.thread, { ...(p.pinned !== undefined ? { pinned: p.pinned } : {}), ...(p.title ? { title: p.title, custom_title: true } : {}) })
    try { await saveThreadMeta(t.thread, p) } catch (e) { toast(friendly(e, 'Saving that')) }
    reload()
  }

  const openAgent = (a: string) => go(deskThread(a))
  const newChat = () => { go(null); requestAnimationFrame(() => composer.current?.focus()) }

  const commands: Command[] = [
    { key: 'new', label: 'New chat', hint: 'start an empty chat', run: newChat },
    { key: 'project', label: 'Make this a project', hint: 'name it; its agents work it together', run: () => { setAsking('project') } },
    { key: 'newproject', label: 'New project', hint: 'instructions, a team, files, its own chats (g n)', run: () => setAsking('new') },
    { key: 'library', label: 'Library', hint: 'every file, every version (g l)', run: () => go('library') },
    { key: 'run', label: 'Run the project', hint: 'its agents start working it on their own', run: () => (activeProject ? void runProject(activeProject) : 'Open a project first (⌘K).') },
    { key: 'workforce', label: 'Workforce', hint: 'show the agents at work', run: () => setWorkforce(true) },
    { key: 'files', label: 'Files', hint: 'every file in this conversation (⌘⇧E)', run: () => setFilesOpen(true) },
    { key: 'voice', label: 'Dictate', hint: 'speak into the message box (⌘.)', run: () => void startDictation((t) => composer.current?.insert(t)) },
    { key: 'talk', label: 'Talk', hint: 'a voice conversation with the agent here (⌘⇧.)', run: () => openTalk() },
    { key: 'remember', label: 'Remember', hint: 'propose the rest of the line to the memory agent', run: () => composer.current?.set('/remember ') },
    { key: 'canvas', label: 'Open in canvas', hint: 'build a page with the first agent here', run: () => void window.open(`${canvasBase()}#/new/${encodeURIComponent(inChat[0] ?? 'painter')}`, '_blank') },
    { key: 'keys', label: 'Keyboard', hint: 'every shortcut', run: () => setHelp(true) },
  ]
  // "/remember text" is sent to memory's proposal route, not to the chat
  // in an open conversation a failed send stays in the OUTBOX with Retry (deliver, above); what still blocks the box (a
  // NEW chat's first message, /remember) keeps the draft on failure (the composer clears only on success), a toast says
  // what happened in the same words, and the box says "not sent" (chat/toast.tsx)
  async function onSendOrCommand(text: string, files: Uploaded[], to: string[]) {
    try {
      const r = /^\/remember\s+([\s\S]+)/.exec(text)
      if (r) { await apiPost('/memory/propose', { text: r[1], nodes: [] }); setNote('Proposed to the memory agent.'); return }
      return await onSend(text, files, to)
    } catch (e) {
      toast(`${friendly(e, 'Your message')} It’s still in the box.`, { key: 'send' })
      throw new Error('Not sent')
    }
  }

  // ------------------------------------------------------------------------------------------------- keys
  const chatIds = listThreads.map((t) => t.thread)
  const gAt = useRef(0)
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      const typing = (e.target as HTMLElement)?.closest('textarea, input')
      if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette((p) => !p); return }
      if (mod && e.key === '\\') { e.preventDefault(); listW.toggle(); return }
      if (mod && e.shiftKey && e.key.toLowerCase() === 'o') { e.preventDefault(); newChat(); return }
      if (mod && e.key.toLowerCase() === 'j') { e.preventDefault(); setWorkforce((w) => !w); return }
      if (mod && e.shiftKey && e.key.toLowerCase() === 'e') { e.preventDefault(); setFilesOpen((f) => !f); return }
      if (mod && e.key === '/') { e.preventDefault(); setHelp((h) => !h); return }
      if (mod && e.shiftKey && e.code === 'Period' && (view === 'thread' || view === 'project')) { e.preventDefault(); openTalk(); return }
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
      // g then l / p / n: the library, the projects, a new project (Linear's go-to chords; never while typing)
      if (!typing && !mod && !e.altKey && !(e.target as HTMLElement)?.closest('select')) {
        const k2 = e.key.toLowerCase()
        if (gAt.current && Date.now() - gAt.current < 1200 && ['l', 'p', 'n'].includes(k2)) {
          e.preventDefault(); gAt.current = 0
          if (k2 === 'l') go('library'); else if (k2 === 'p') go('projects'); else setAsking('new')
          return
        }
        gAt.current = k2 === 'g' && !e.shiftKey ? Date.now() : 0
      }
    }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [palette, help, workforce, filesOpen, drawer, current, dirty, panel.tabs.length, chatIds.join('|'), recipients.join(','), view]) // eslint-disable-line react-hooks/exhaustive-deps

  // signed out, offline and a rotated key are the gate's (chat/Gate.tsx): this renders only for the owner
  if (!who.owner) return null

  const roles = Object.fromEntries(team.map((a) => [a.agent, a.role]))
  const title = currentRow?.title ?? (activeProject ? activeProject.name : 'New chat')
  const box = (hero: boolean, placeholder?: string) => (
    <Composer ref={composer} hero={hero} roster={names} inChat={recipients} skills={cmds.skills} tools={cmds.tools}
      commands={commands} onSend={onSendOrCommand} draftKey={view === 'thread' ? current : thread ?? ''}
      placeholder={placeholder ?? (hero ? 'Ask the team anything. @mention who should take it; seed routes the rest.' : undefined)}
      lastMine={() => stripEmbeds([...rows].reverse().find((m) => m.from === 'owner')?.body ?? '')} onTalk={openTalk} />
  )
  const list = (phone: boolean) => (
    <ConversationList threads={listThreads} loaded={loaded} current={current || null} live={live} projects={proj.projects} project={project}
      onGo={(t) => go(t)} onNew={newChat} onProject={openProject}
      view={view} filter={listFilter} onFilter={setListFilter} onLibrary={() => go('library')} onProjects={() => go('projects')}
      onNewProject={() => setAsking('new')} onMove={(t, to) => void proj.mutate(moveThread(t.thread, to))}
      onPin={(t) => setMeta(t, { pinned: !t.pinned })} onRename={(t, title) => setMeta(t, { title })}
      onClose={phone ? () => setDrawer(false) : undefined}
      unread={unread} onJump={onJump}
      className={phone ? '!w-[86vw] max-w-[340px]' : `max-md:hidden ${listHidden ? '!hidden' : ''}`} />
  )
  const home = view === 'thread' && !current
  const layout: Layout = winW >= 1200 ? 'inline' : winW >= 768 ? 'sheet' : 'full'
  const canvasHere = (!!current || view === 'library' || view === 'project') && canvasOpen !== null && !workforce
  const showPanel = (!!current || view === 'library' || view === 'project') && panel.tabs.length > 0 && !workforce && !canvasHere
  const threadCanvas = canvasIdOf(current)
  // ⌘K / the library: a canvas opens beside its own conversation when it has one listed, else right where you are
  const openCanvas = (id: number, toThread: boolean) => {
    setWorkforce(false)
    const t = canvases?.find((c) => c.id === id)?.thread
    if (toThread && t && threads.some((x) => x.thread === t) && t !== current) { canvasNext.current = id; go(t) } else setCanvasOpen(id)
  }
  const files = media ?? []
  // the drawer docks beside the panel where there is room for rail + chat + panel + drawer; narrower it floats
  const docked = winW >= 1320
  // the list steps aside for the panel below 1440, and for panel + docked drawer below 1720 (⌘\ hides it any time)
  // a painted page wants room: the list steps aside for a canvas below 1600
  const listHidden = listW.collapsed || (canvasHere && layout === 'inline' && winW < 1600) || ((showPanel || canvasHere) && layout === 'inline' && (winW < 1440 || (filesOpen && !!current && docked && winW < 1720)))
  const openFile = (r: OpenRequest) => { setWorkforce(false); panel.open(r); if (winW < 1200) setFilesOpen(false) }
  openRef.current = openFile
  // the briefing's chips: a conversation AT the message (iteration 8's jump pulse); a file in its conversation's panel
  // (as that message's chip would open it), or — from a conversation the workspace doesn't open (WhatsApp) — stored
  // under its own thread first and shown in the library's panel
  const brief: BriefingActions = {
    onJump: (t, id) => { setJump({ thread: t, id, n: Date.now() }); go(t) },
    onAgent: openAgent,
    onSeen: visit.markSeen,
    onFile: async (agent, f) => {
      const msg = { id: f.msg_id, ts: f.ts }
      const req: OpenRequest = { path: f.path, label: f.label ?? f.name, from: agent, msg }
      if (f.thread && /^(chat|obs|cv):/.test(f.thread)) {
        fileNext.current = { at: f.thread, req }
        setJump({ thread: f.thread, id: f.msg_id, n: Date.now() }); go(f.thread)
        return
      }
      try {
        const a = f.artifact ? { id: f.artifact, name: f.name } : await openArtifact(f.path, f.thread ?? 'library', agent, f.label ?? f.name, msg)
        fileNext.current = { at: 'library', req: { path: a.id.startsWith('file:') ? f.path : byId(a.id), label: a.name, from: agent } }
        go('library')
      } catch (e) { toast(friendly(e, `Opening ${f.name}`)) }
    },
  }
  const onShow = (k: Feature) => {
    if (k === 'projects') go('projects')
    else if (k === 'search') setPalette(true)
    else if (k === 'keys') setHelp(true)
    else if (k === 'map') dispatchEvent(new KeyboardEvent('keydown', { key: 'm', metaKey: true, ctrlKey: true, shiftKey: true }))
    else if (k === 'stop') { const t = threads[0]?.thread; if (t) go(t); setNote('While an agent works, the line under the conversation names it, with Stop beside it.') }
    else if (k === 'phone') {
      const url = `${location.origin}${location.pathname}#/chat`
      void navigator.clipboard?.writeText(url).then(() => toast('Link copied. Open it on your phone, then Share → Add to Home Screen.', { kind: 'info' }),
        () => toast('Open this page on your phone, then Share → Add to Home Screen.', { kind: 'info' }))
    } else go('library')
  }
  // a turn's actions: quote into the composer (to whoever said it, when several share the thread); open as a document
  const turnActsNow: TurnActionsValue = {
    quote: (text, m) => composer.current?.insert(quoteText(text, m.from !== 'owner' && inChat.length > 1 ? m.from : null)),
    openDoc: async (m, text) => {
      const a = await createArtifact({ thread: current, name: docName(text), text, author: m.from, msg: { id: m.id, ts: m.ts } })
      openFile({ path: byId(a.id), label: a.name, from: m.from })
    },
    // iteration 9: a table in a turn → a CSV artifact by that agent, opened as its chart
    openTable: async (m, csv, name) => {
      const a = await createArtifact({ thread: current, name, text: csv, author: m.from, msg: { id: m.id, ts: m.ts } })
      preferChart(a.id)
      openFile({ path: byId(a.id), label: a.name, from: m.from })
    },
  }
  // ONE identity for the context (iteration 14): a new object per render re-rendered every turn's actions on every tick
  const turnActsRef = useRef(turnActsNow)
  turnActsRef.current = turnActsNow
  const turnActs = useMemo<TurnActionsValue>(() => ({
    quote: (t, m) => turnActsRef.current.quote(t, m),
    openDoc: (m, t) => turnActsRef.current.openDoc(m, t),
    openTable: (m, csv, name) => turnActsRef.current.openTable!(m, csv, name),
  }), [])
  // a quoted ask in the chat: open its file (by name, from this thread's files) at the highlight it came from
  const openAsk = (a: ParsedAsk) => {
    const f = files.find((x) => x.name === a.name)
    if (!f) { setNote(`${a.name} is not among this conversation's files any more.`); return }
    openFile({ path: f.path, label: f.label, from: f.from })
    setAnnFocus({ name: a.name, ann: a.ann, n: Date.now() })
  }
  // what the annotation layer borrows from the conversation; an ask is one ordinary message on this thread
  const annotate: AnnotateCtx = {
    rows, roster: names, agents: inChat, focus: annFocus,
    ask: async (agent, body) => { const m = await send(agent, body, current); reload(); return m },
  }
  return (
    <div className="ws h-dvh flex ws-backdrop text-ink overflow-hidden" style={{ ['--ws-list' as string]: `${listW.width}px` }}>
      {/* the first Tab stop: past the rail's agents and the list, straight to the box (a hash link would route) */}
      <button onClick={() => composer.current?.focus()}
        className="sr-only focus:not-sr-only focus:fixed focus:z-[80] focus:left-3 focus:top-3 ws-btn !bg-[var(--t-panel)]">Skip to the message box</button>
      <AgentRail agents={names} status={status} lines={lines} current={current || null} onPick={openAgent}
        onHome={() => { setListFilter(null); go(null) }} onPalette={() => setPalette(true)} onKeys={() => setHelp(true)} />
      {list(false)}
      {!listHidden && <ListSeam list={listW} />}

      {/* ── the conversation, and beside it the artifact panel ─────────────────────────────── */}
      <div className="flex-1 min-w-0 flex">
      <main className="flex-1 min-w-[420px] max-md:min-w-0 flex flex-col relative">
        <ConnStatus />
        {home || view !== 'thread' ? (
          <div className="h-12 shrink-0 flex items-center px-3 md:hidden">
            <button className="ws-icon" onClick={() => setDrawer(true)} aria-label="conversations">{I.menu()}</button>
          </div>
        ) : (
          <TopBar title={title} canRename={!!currentRow} surface={currentRow?.surface ?? null}
            project={projectOf(current, proj.projects)?.name ?? null}
            onProject={() => { const p = projectOf(current, proj.projects); if (p) openProject(p.id) }}
            agents={current ? inChat : activeProject?.agents ?? []} status={status} workforce={workforce}
            files={files.length} media={filesOpen}
            onRename={(t) => currentRow && setMeta(currentRow, { title: t })}
            onWorkforce={() => setWorkforce((w) => !w)} onMedia={() => setFilesOpen((f) => !f)}
            onMenu={() => setDrawer(true)} onAgent={openAgent} names={names} lines={lines}
            more={<MoreMenu onExport={() => exportConversation(rows, title, current, names)} />}
            canvas={threadCanvas ? { version: canvases?.find((c) => c.id === threadCanvas)?.version ?? 0, open: canvasOpen === threadCanvas,
              onToggle: () => { setWorkforce(false); setCanvasOpen((o) => (o === threadCanvas ? null : threadCanvas)) } } : null} />
        )}
        <div className="flex-1 min-h-0 overflow-y-auto">
          {home && <TeamHome names={names} status={status} lines={lines} agents={team} threads={threads} composer={box(true)} onAgent={openAgent} onGo={go}
            since={visit.since} brief={brief} onShow={onShow} />}
          <Suspense fallback={null}>
          {view === 'library' && <Library projects={proj.projects} activeId={canvasHere ? null : storedActive} onOpen={(id, it) => { setCanvasOpen(null); openStored(id, it) }} onThread={go}
            activeCanvas={canvasHere ? canvasOpen : null} onCanvas={(id) => openCanvas(id, false)}
            onAddToProject={(pid, aid) => void proj.mutate(patchOne(pid, (x) => (x.files.includes(aid) ? x : { ...x, files: [...x.files, aid] })))} />}
          {view === 'projects' && <ProjectsIndex projects={proj.projects} threads={threads} loaded={proj.loaded} onOpen={openProject} onNew={() => setAsking('new')} />}
          {view === 'project' && activeProject && <ProjectHome key={activeProject.id} p={activeProject} threads={threads} names={names} status={status} roles={roles}
            composer={box(true, `New chat in ${activeProject.name}…`)} activeId={storedActive} go={go} onAgent={openAgent} onOpenFile={openStored}
            edit={(f) => proj.mutate(patchOne(activeProject.id, f))} onRun={() => void runProject(activeProject)} onAll={() => go('projects')} onNote={setNote}
            onRemoveThread={(t) => void proj.mutate(moveThread(t, null))}
            onDelete={() => { void proj.mutate(removeOne(activeProject.id)); setListFilter(null); go('projects') }} />}
          {view === 'project' && !activeProject && proj.loaded && (
            <div className="pt-[18vh] text-center text-[14px] text-ink-dim">This project is gone. <button className="underline underline-offset-2" onClick={() => go('projects')}>All projects</button></div>
          )}
          </Suspense>
          <ChipCtx.Provider value={chipAware}><TurnActionsCtx.Provider value={turnActs}>
          {current && histErr && (
            <div className="mx-auto max-w-[760px] w-full px-6 pt-4 text-[12.5px] text-ink-dim flex items-center gap-2" role="status">
              <span className="ws-live-dot" aria-hidden />Couldn’t load this conversation’s history: the org isn’t answering. Trying again…
              <button className="underline underline-offset-2 hover:text-ink" onClick={() => setHistTry((n) => n + 1)}>Retry now</button>
            </div>
          )}
          {current && <Turns key={current} older={older} onOlder={loadOlderRows} focus={jump?.thread === current ? jump : null} rows={rows} work={work} pending={pending} roster={names} roles={roles} loading={history === null} handoffs={handoffs} onStop={interruptAgent}
            onOpenFile={openFile} onOpenAsk={openAsk} onEdit={(m) => composer.current?.set(stripEmbeds(m.body))}
            empty={histErr ? null : <FreshThread agents={inChat} status={status} roles={roles} lines={lines} />} />}
          {current && <Outbox items={outbox.filter((o) => o.thread === current)} onRetry={(o) => void deliver(o)}
            onDiscard={(o) => setOutbox((xs) => xs.filter((x) => x.key !== o.key))}
            onEdit={(o) => { setOutbox((xs) => xs.filter((x) => x.key !== o.key)); composer.current?.set(o.text); o.files.forEach((f) => composer.current?.attach(f)) }} />}
          </TurnActionsCtx.Provider></ChipCtx.Provider>
        </div>
        {note && <div className="mx-auto max-w-[760px] w-full px-6 pb-1 text-[12.5px] text-ink-dim cursor-pointer" role="status" onClick={() => setNote('')}>{note}</div>}
        {view === 'thread' && !home && <NotifyPrompt waiting={pending.length > 0 || outbox.some((o) => o.thread === current)} />}
        {view === 'thread' && !home && box(false)}

        {/* the media drawer: over the conversation's right edge, under the top bar (the whole screen on a phone) */}
        <AnimatePresence>
          {filesOpen && current && !docked && (
            <motion.div key="files" className="absolute right-0 top-12 bottom-0 z-20 w-[360px] max-w-full max-md:fixed max-md:inset-0 max-md:w-full max-md:z-50"
              initial={reduce ? false : { opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} exit={reduce ? undefined : { opacity: 0, x: 16 }}
              transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}>
              <MediaDrawer items={files} loading={media === null} onOpen={openFile} onClose={() => setFilesOpen(false)}
                openKey={showPanel ? panel.active : null} />
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {showPanel && <Panel panel={panel} layout={layout} onDirty={setDirty} annotate={current ? annotate : undefined}
        onAttach={(u) => { if (view === 'library') { newChat(); setTimeout(() => composer.current?.attach(u), 80) } else composer.current?.attach(u) }} />}
      {canvasHere && <Suspense fallback={null}><CanvasPanel key={canvasOpen} id={canvasOpen!} layout={layout} onClose={() => setCanvasOpen(null)}
        onThread={canvases?.find((c) => c.id === canvasOpen)?.thread === current ? undefined : (t) => { canvasNext.current = canvasOpen; go(t) }} /></Suspense>}
      </div>

      {/* wide: the media drawer DOCKS as a column beside the artifact panel (the panel's row narrows; nothing floats
          over the conversation) */}
      {filesOpen && current && docked && (
        <div className="ws-dock w-[340px] shrink-0">
          <MediaDrawer items={files} loading={media === null} onOpen={openFile} onClose={() => setFilesOpen(false)} openKey={showPanel ? panel.active : null} />
        </div>
      )}

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
        lines={lines} files={files} unread={unread} live={live} onOpenFile={(f) => { setPalette(false); openFile(f) }} onJump={onJump}
        canvases={canvases ?? []} onCanvas={(id) => { setPalette(false); openCanvas(id, true) }}
        go={(t) => { setPalette(false); go(t) }}
        openProject={(id) => { setPalette(false); openProject(id) }}
        openAgent={(n) => { setPalette(false); openAgent(n) }} />}
      {help && <Keys onClose={() => setHelp(false)} />}
      <AnimatePresence>
        {talk && (
          <Suspense key="talk" fallback={null}>
            <TalkMode agent={talk.agent} thread={talk.thread} title={talk.thread === current ? title : null} rows={talkRows}
              send={async (to, body, t) => { const m = await send(to, body, t); reload(); return m }}
              onSent={(t) => { if (t !== current) { if (activeProject && view === 'project') void proj.mutate(moveThread(t, activeProject.id)); go(t) } }}
              onClose={() => setTalk(null)} />
          </Suspense>
        )}
      </AnimatePresence>
      {asking && <NewProject suggest={nextColor(proj.projects)} onClose={() => setAsking(null)}
        seedAgents={asking === 'project' && current ? inChat : []} seedThread={asking === 'project' && current ? title : null}
        onCreate={async (d) => {
          const seeded = asking === 'project' && !!current
          setAsking(null)
          const p = blank(d.name, proj.projects, { instructions: d.instructions, color: d.color, emoji: d.emoji, agents: seeded ? inChat : [] })
          if (await proj.mutate((list) => (seeded ? moveThread(current, p.id)(upsert(p)(list)) : upsert(p)(list)))) openProject(p.id)
        }} />}
    </div>
  )
}

/* a turn kept as a document is named by its first heading, else its first words */
function docName(text: string): string {
  const h = /^#{1,3}\s+(.+)$/m.exec(text)?.[1] ?? text.replace(/[#>*_`|[\]()]/g, ' ').trim().split(/\s+/).slice(0, 7).join(' ')
  return `${h.replace(/[*_`]/g, '').slice(0, 60).trim() || 'answer'}.md`
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
