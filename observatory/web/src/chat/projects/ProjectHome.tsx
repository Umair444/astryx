import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { apiSend, displayName, fmtAgo } from '../../api'
import AgentFace from '../../components/AgentFace'
import { I } from '../icons'
import type { Status, WsThread } from '../data'
import { upload, type Project } from '../model'
import { kindOfName, type Artifact } from '../artifacts/api'
import { loadArtifacts, type Item } from '../library/api'
import Instructions from './Instructions'
import Team from './Team'
import Files from './Files'
import FilePicker from './FilePicker'
import { EditableTitle, ProjectMark, since, Swatches } from './parts'

/* A PROJECT'S HOME (#/chat/project:<id>), canvas-calm: the serif name (click to rename) on its mark, the big composer
   ("New chat in <project>": a chat: thread that joins the project, its first message carrying the instructions and
   the files), the project's conversations newest first; and beside them what the project KNOWS: its Instructions
   (autosaved), its Team (who every new chat goes to) and its Files (pinned artifacts). Wide it is two columns; on a
   phone one, the composer first and the conversations last. */

export type ProjectEdit = (f: (p: Project) => Project) => Promise<boolean>

export default function ProjectHome({ p, threads, names, status, roles, composer, activeId, edit, go, onAgent, onOpenFile, onRemoveThread, onDelete, onRun, onAll, onNote }: {
  p: Project
  threads: WsThread[]
  names: string[]
  status: Record<string, Status>
  roles: Record<string, string>
  composer: ReactNode
  activeId: string | null
  edit: ProjectEdit
  go: (thread: string) => void
  onAgent: (a: string) => void
  onOpenFile: (id: string, it: Item) => void
  onRemoveThread: (thread: string) => void
  onDelete: () => void
  onRun: () => void
  onAll: () => void
  onNote: (s: string) => void
}) {
  const reduce = useReducedMotion()
  const [arts, setArts] = useState<Item[] | null>(null)
  const [busy, setBusy] = useState('')
  const [picking, setPicking] = useState(false)
  const filesKey = p.files.join(',')

  // the pinned files, as library items (one listing; the store is small and this is one owner's page)
  const loadFiles = useCallback(() => loadArtifacts().then((all) => {
    const by = new Map(all.map((a) => [a.id, a]))
    setArts(p.files.map((id) => by.get(id)).filter((a): a is NonNullable<typeof a> => !!a).map((a) => ({
      key: a.id, id: a.id, name: a.name, kind: a.kind === 'binary' ? kindOfName(a.name) : a.kind, thread: a.thread, title: a.title, author: a.author ?? 'owner',
      ts: a.updated ?? '', versions: a.versions.length, size: a.size, head: a.head,
    })))
  }).catch(() => setArts([])), [filesKey]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { void loadFiles() }, [loadFiles])

  const addFiles = (ids: string[]) => edit((x) => ({ ...x, files: [...x.files, ...ids.filter((i) => !x.files.includes(i))] }))
  const uploadFiles = async (files: File[]) => {
    const ids: string[] = []
    for (const [n, f] of files.entries()) {
      setBusy(files.length > 1 ? `Adding ${f.name} (${n + 1} of ${files.length})…` : `Adding ${f.name}…`)
      try {
        const u = await upload(f, f.name)
        const a = await apiSend<Artifact>('POST', '/ws/artifacts/open', { path: u.path, thread: `project:${p.id}`, author: 'owner', label: u.name })
        ids.push(a.id)
      } catch (e) { onNote(`${f.name}: ${(e as Error).message}`) }
    }
    setBusy('')
    if (ids.length) await addFiles(ids)
  }

  const mine = useMemo(() => {
    const by = new Map(threads.map((t) => [t.thread, t]))
    return p.threads.map((t) => by.get(t) ?? null).filter((t): t is WsThread => !!t)
      .sort((a, b) => Date.parse(b.last_ts ?? '0') - Date.parse(a.last_ts ?? '0'))
  }, [threads, p.threads])
  const team = p.agents.length ? p.agents : names.includes('seed') ? ['seed'] : []
  const rise = (d: number) => (reduce ? {} : { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.45, delay: d, ease: [0.22, 1, 0.36, 1] as const } })

  return (
    <div className="@container mx-auto w-full max-w-[1080px] px-4 md:px-10 pt-6 md:pt-10 pb-20">
      <motion.div {...rise(0)}>
        <button onClick={onAll} className="inline-flex items-center gap-1 text-[12.5px] text-ink-mute hover:text-ink transition-colors">{I.back('w-3.5 h-3.5')}All projects</button>
        <div className="mt-4 flex items-start gap-4">
          <Customize p={p} edit={edit} />
          <div className="min-w-0 flex-1">
            <EditableTitle value={p.name} onSave={(name) => void edit((x) => ({ ...x, name }))} className="text-[clamp(38px,5.4vw,56px)] leading-[1] text-ink" />
            <div className="mt-2 text-[12.5px] text-ink-mute">
              {[`${mine.length} conversation${mine.length === 1 ? '' : 's'}`, `${p.files.length} file${p.files.length === 1 ? '' : 's'}`,
                p.updated ? `updated ${since(p.updated)}` : ''].filter(Boolean).join(' · ')}
            </div>
          </div>
          <More onRun={onRun} onDelete={onDelete} canRun={p.agents.length > 0} />
        </div>
      </motion.div>

      <div className="mt-8 grid gap-x-10 gap-y-8 @4xl:grid-cols-[minmax(0,1fr)_340px] @4xl:grid-rows-[auto_1fr] items-start">
        <motion.div {...rise(0.06)} className="min-w-0 @4xl:col-start-1 @4xl:row-start-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mb-2.5 text-[12.5px] text-ink-mute">
            <span className="whitespace-nowrap truncate max-w-full">New chat in <span className="text-ink">{p.name}</span></span>
            <span aria-hidden className="max-sm:hidden">·</span>
            <span className="inline-flex items-center gap-1.5 min-w-0 whitespace-nowrap">goes to
              <span className="flex -space-x-1">{team.slice(0, 5).map((a) => <span key={a} className="rounded-full ring-2 ring-[var(--t-bg)]"><AgentFace name={a} size={16} /></span>)}</span>
              <span className="text-ink-dim truncate max-w-[200px]">{team.map(displayName).join(', ')}</span>
            </span>
          </div>
          {composer}
        </motion.div>

        <motion.aside {...rise(0.12)} className="min-w-0 @4xl:col-start-2 @4xl:row-start-1 @4xl:row-span-2" aria-label="what the project knows">
          <Instructions value={p.instructions} onSave={(instructions) => edit((x) => ({ ...x, instructions }))} />
          <Team agents={p.agents} missing={p.missing ?? []} names={names} status={status} roles={roles} onAgent={onAgent}
            onChange={(agents) => void edit((x) => ({ ...x, agents }))} />
          <Files items={arts ?? []} loading={arts === null} activeId={activeId} busy={busy}
            onOpen={(it) => onOpenFile(it.id!, it)} onUpload={(f) => void uploadFiles(f)} onPick={() => setPicking(true)}
            onRemove={(id) => void edit((x) => ({ ...x, files: x.files.filter((f) => f !== id) }))} />
        </motion.aside>

        <motion.section {...rise(0.18)} className="min-w-0 @4xl:col-start-1 @4xl:row-start-2" aria-label="conversations in this project">
          <h2 className="text-[13px] font-medium text-ink mb-1.5">Conversations</h2>
          {mine.length === 0 && (
            <p className="text-[13px] text-ink-mute leading-relaxed py-2 max-w-[520px]">
              None yet. Start one above: it opens with the instructions and the files. Or move any conversation here from its menu in the sidebar.
            </p>
          )}
          <div className="flex flex-col -mx-2.5">
            {mine.map((t) => <ConvRow key={t.thread} t={t} onGo={() => go(t.thread)} onRemove={() => onRemoveThread(t.thread)} />)}
          </div>
        </motion.section>
      </div>
      {picking && <FilePicker have={p.files} onClose={() => setPicking(false)} onAdd={(ids) => { setPicking(false); void addFiles(ids) }} />}
    </div>
  )
}

function ConvRow({ t, onGo, onRemove }: { t: WsThread; onGo: () => void; onRemove: () => void }) {
  return (
    <div className="group relative">
      <button onClick={onGo} className="ws-row w-full flex items-start gap-3 rounded-[12px] px-2.5 py-2.5 text-left pr-10">
        <span className="mt-0.5"><AgentFace name={t.agents[0] ?? 'owner'} size={24} /></span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className="truncate text-[14px] text-ink">{t.title}</span>
            <span className="ml-auto shrink-0 text-[11.5px] text-ink-mute tabular-nums">{fmtAgo(t.last_ts)}</span>
          </span>
          {t.preview && <span className="block truncate text-[12.5px] text-ink-mute mt-0.5">{t.last_from && t.last_from !== 'owner' ? `${displayName(t.last_from)}: ` : ''}{t.preview}</span>}
        </span>
      </button>
      <button onClick={onRemove} title="Take out of this project (the conversation stays)" aria-label={`take ${t.title} out of the project`}
        className="absolute right-1.5 top-2.5 ws-icon !w-7 !h-7 opacity-0 group-hover:opacity-100 focus:opacity-100 max-md:hidden">{I.x('w-3.5 h-3.5')}</button>
    </div>
  )
}

/* the mark, and behind it the project's colour and emoji */
function Customize({ p, edit }: { p: Project; edit: ProjectEdit }) {
  const [open, setOpen] = useState(false)
  const [emoji, setEmoji] = useState(p.emoji ?? '')
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { setEmoji(p.emoji ?? '') }, [p.emoji])
  useEffect(() => {
    if (!open) return
    const off = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) } }
    addEventListener('mousedown', off); addEventListener('keydown', esc, true)
    return () => { removeEventListener('mousedown', off); removeEventListener('keydown', esc, true) }
  }, [open])
  const seg = typeof Intl !== 'undefined' && 'Segmenter' in Intl ? new Intl.Segmenter(undefined, { granularity: 'grapheme' }) : null
  const saveEmoji = (raw: string) => {
    const e = seg ? ([...seg.segment(raw.trim())][0]?.segment ?? '') : raw.trim().slice(0, 2)
    if (e && /[\sA-Za-z0-9<>&"']/.test(e)) return
    if ((e || null) !== (p.emoji ?? null)) void edit((x) => ({ ...x, emoji: e || null }))
  }
  return (
    <div className="relative mt-1.5 shrink-0" ref={box}>
      <button onClick={() => setOpen((o) => !o)} aria-label="colour and emoji" title="Colour and emoji" aria-expanded={open}
        className="rounded-[16px] hover:brightness-110 transition"><ProjectMark p={p} size={46} /></button>
      {open && (
        <div className="ws-menu absolute left-0 top-[calc(100%+6px)] z-30 p-3.5 w-[260px]">
          <div className="text-[12px] text-ink-mute mb-2">Colour</div>
          <Swatches value={p.color} onPick={(color) => void edit((x) => ({ ...x, color }))} />
          <div className="text-[12px] text-ink-mute mt-3.5 mb-1.5">Emoji</div>
          <div className="flex items-center gap-2">
            <input value={emoji} onChange={(e) => setEmoji(e.target.value)} onBlur={() => saveEmoji(emoji)} onKeyDown={(e) => e.key === 'Enter' && saveEmoji(emoji)}
              maxLength={8} placeholder="📈" aria-label="emoji" className="w-14 h-8 text-center rounded-[10px] bg-[var(--t-bg)] border border-line outline-none text-[16px]" />
            {p.emoji && <button onClick={() => { setEmoji(''); void edit((x) => ({ ...x, emoji: null })) }} className="text-[12.5px] text-ink-mute hover:text-ink">Remove</button>}
          </div>
        </div>
      )}
    </div>
  )
}

function More({ onRun, onDelete, canRun }: { onRun: () => void; onDelete: () => void; canRun: boolean }) {
  const [open, setOpen] = useState(false)
  const [sure, setSure] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) { setSure(false); return }
    const off = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    addEventListener('mousedown', off)
    return () => removeEventListener('mousedown', off)
  }, [open])
  return (
    <div className="relative mt-2 shrink-0" ref={box}>
      <button className="ws-icon" onClick={() => setOpen((o) => !o)} aria-label="project actions" aria-expanded={open}>{I.dots()}</button>
      {open && (
        <div className="ws-menu absolute right-0 top-[calc(100%+4px)] z-30 w-[250px] p-1" role="menu">
          <button role="menuitem" disabled={!canRun} onClick={() => { setOpen(false); onRun() }}
            className="ws-row w-full flex items-start gap-2 rounded-lg px-2.5 py-2 text-left disabled:opacity-40">
            <span className="mt-0.5 text-ink-dim">{I.spark('w-3.5 h-3.5')}</span>
            <span><span className="block text-[13px] text-ink">Run with the team</span><span className="block text-[11.5px] text-ink-mute leading-snug">{canRun ? 'Its agents split the work and post progress on one thread' : 'Add agents to the team first'}</span></span>
          </button>
          <button role="menuitem" onClick={() => (sure ? (setOpen(false), onDelete()) : setSure(true))}
            className="ws-row w-full flex items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] text-bad">
            {I.x('w-3.5 h-3.5')}{sure ? 'Click again: delete the project' : 'Delete project'}
          </button>
          {sure && <p className="px-2.5 pb-1.5 text-[11.5px] text-ink-mute leading-snug">Its conversations and files stay; only the project goes.</p>}
        </div>
      )}
    </div>
  )
}
