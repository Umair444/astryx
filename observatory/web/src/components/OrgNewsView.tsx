import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import AgentFace from './AgentFace'
import { api, displayName, fmtAgo, fmtDay, fmtTime } from '../api'
import { useStore } from '../store'
import type { Msg } from '../types'
import Md from './Md'
import { Empty, FaceStack, LiveDot, Panel, Skeleton, Tabs } from '../ui/kit'

/* The Press — org-news rendered as a news surface (Ground-News-style cards).
   Category = who actually wrote it, not decoration:
     charter  — the scribe's auto-post on a ratified charter commit
     tools    — tool_ship_watch's auto-receipt for new capabilities
     dispatch — an agent posting a milestone in its own voice
   Issue numbers appear only on posts that carry one (#N) — real sequence,
   not ornament. */

type Kind = 'charter' | 'tools' | 'dispatch'

const KIND: Record<Kind, { label: string; color: string; bg: string; border: string }> = {
  charter: { label: 'CHARTER', color: 'text-warn', bg: 'bg-warn/10', border: 'border-warn/30' },
  tools: { label: 'TOOLING', color: 'text-cyan', bg: 'bg-cyan/10', border: 'border-cyan/30' },
  dispatch: { label: 'DISPATCH', color: 'text-cyan-soft', bg: 'bg-cyan-soft/10', border: 'border-cyan-soft/30' },
}

interface Story {
  m: Msg
  kind: Kind
  issue: number | null
  headline: string
  dek: string // remainder of the body after the headline
}

function parseStory(m: Msg): Story {
  const body = m.body.trim()
  const kind: Kind = /\(auto, scribe\)/.test(body) ? 'charter' : /\(auto, tool-ship\)/.test(body) ? 'tools' : 'dispatch'
  const issue = body.match(/^org-news #(\d+)/)?.[1]
  // strip the wire-protocol prefix ("org-news #4 (seed) — ", "org-news (auto, scribe) — ")
  const stripped = body.replace(/^org-news(\s+#\d+)?\s*\([^)]*\)\s*—\s*/, '')
  const nl = stripped.indexOf('\n')
  let headline = (nl === -1 ? stripped : stripped.slice(0, nl)).trim()
  let dek = nl === -1 ? '' : stripped.slice(nl + 1).trim()
  // very long single-line posts: break at the first sentence boundary
  if (!dek && headline.length > 160) {
    const cut = headline.slice(0, 160).lastIndexOf('. ')
    if (cut > 40) {
      dek = headline.slice(cut + 2)
      headline = headline.slice(0, cut + 1)
    }
  }
  return { m, kind, issue: issue ? +issue : null, headline, dek }
}

function Byline({ s, expanded, big = false }: { s: Story; expanded: boolean; big?: boolean }) {
  return (
    <div className="flex items-center gap-2.5 mt-auto pt-4">
      <AgentFace name={s.m.from} size={big ? 32 : 24} />
      <div className="min-w-0 leading-tight">
        <div className={`${big ? 'text-[13px]' : 'text-[12px]'} text-ink-dim font-medium truncate`}>{displayName(s.m.from)}</div>
        <div className="text-[11px] text-ink-mute" title={new Date(s.m.ts).toLocaleString()}>
          {fmtDay(s.m.ts)} {fmtTime(s.m.ts)} · {fmtAgo(s.m.ts)}
        </div>
      </div>
      {s.dek && (
        <span className="ml-auto text-[11px] text-ink-mute group-hover:text-cyan-soft transition-colors">
          {expanded ? 'collapse ▴' : 'read ▾'}
        </span>
      )}
    </div>
  )
}

function Kicker({ s }: { s: Story }) {
  const k = KIND[s.kind]
  return (
    <div className="flex items-center gap-2">
      <span className={`text-[10px] font-mono font-bold tracking-[0.18em] px-1.5 py-0.5 rounded ${k.color} ${k.bg} border ${k.border}`}>
        {k.label}
      </span>
      {s.issue !== null && (
        <span className="text-[10px] font-mono text-ink-mute/70 tracking-wider">Nº {s.issue}</span>
      )}
    </div>
  )
}

const serif = { fontFamily: "'Iowan Old Style', 'Charter', Georgia, 'Times New Roman', serif" }

/* a story that arrived while you were reading glows once, then settles */
function FreshGlow() {
  return (
    <motion.span aria-hidden className="absolute inset-0 rounded-2xl pointer-events-none"
      initial={{ opacity: 1 }} animate={{ opacity: 0 }} transition={{ duration: 3, ease: 'easeOut' }}
      style={{ boxShadow: 'inset 0 0 0 1px var(--t-accent), 0 0 48px -14px var(--t-accent)' }} />
  )
}

function LeadStory({ s, fresh }: { s: Story; fresh: boolean }) {
  const [open, setOpen] = useState(false)
  const k = KIND[s.kind]
  return (
    <Panel live={fresh} className={`group overflow-hidden ${s.dek ? 'cursor-pointer' : ''}`}>
      <div onClick={() => s.dek && setOpen((v) => !v)} className="relative p-6 sm:p-7 flex flex-col">
        {fresh && <FreshGlow />}
        {/* signature: the lead's category rail */}
        <div className={`absolute left-0 top-6 bottom-6 w-[3px] rounded-r ${k.bg.replace('/10', '/80')}`} />
        <div className="flex items-center gap-2">
          <Kicker s={s} />
          <span className="ml-auto flex items-center gap-1.5 text-[10px] font-mono tracking-[0.2em] text-ink-mute">
            <LiveDot state="awake" /> LATEST
          </span>
        </div>
        <h2 style={serif} className="text-ink text-[24px] sm:text-[28px] leading-[1.18] font-semibold mt-3 [text-wrap:balance]">
          {s.headline}
        </h2>
        {s.dek && !open && (
          <p className="text-[14px] text-ink-dim leading-relaxed mt-3 line-clamp-3 whitespace-pre-line max-w-[68ch]">{s.dek}</p>
        )}
        {s.dek && open && (
          <div className="text-[14px] mt-3 max-w-[68ch]" onClick={(e) => e.stopPropagation()}>
            <Md text={s.dek} />
          </div>
        )}
        <Byline s={s} expanded={open} big />
      </div>
    </Panel>
  )
}

function StoryCard({ s, i, fresh }: { s: Story; i: number; fresh: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <motion.div layout="position"
      initial={fresh ? { opacity: 0, y: -12, scale: 0.98 } : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ delay: fresh ? 0 : Math.min(i * 0.03, 0.3), duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className={open ? 'md:col-span-2' : ''}>
      <Panel interactive={!!s.dek} className="group h-full">
        <article onClick={() => s.dek && setOpen((v) => !v)} className="relative p-5 h-full flex flex-col">
          {fresh && <FreshGlow />}
          <Kicker s={s} />
          <h3 style={serif} className="text-ink text-[17.5px] leading-snug font-semibold mt-2.5 [text-wrap:balance]">
            {s.headline}
          </h3>
          {s.dek && !open && (
            <p className="text-[13px] text-ink-mute leading-relaxed mt-2 line-clamp-3 whitespace-pre-line">{s.dek}</p>
          )}
          {s.dek && open && (
            <div className="text-[13px] mt-2" onClick={(e) => e.stopPropagation()}>
              <Md text={s.dek} />
            </div>
          )}
          <Byline s={s} expanded={open} />
        </article>
      </Panel>
    </motion.div>
  )
}

export default function OrgNewsView() {
  const { messages } = useStore()
  const [history, setHistory] = useState<Msg[] | null>(null)
  const [filter, setFilter] = useState<Kind | 'all'>('all')

  useEffect(() => {
    api<Msg[]>('/messages?thread=org-news&limit=500').then(setHistory).catch(() => setHistory([]))
  }, [])

  const stories = useMemo(() => {
    // full fetched history + anything fresh the SSE stream delivered since
    const h = history ?? []
    const seen = new Set(h.map((m) => m.id))
    const live = messages.filter((m) => m.thread === 'org-news' && !seen.has(m.id))
    return [...h, ...live]
      .sort((a, b) => b.id - a.id)
      .map(parseStory)
  }, [history, messages])

  const counts = useMemo(() => {
    const c: Record<Kind, number> = { charter: 0, tools: 0, dispatch: 0 }
    for (const s of stories) c[s.kind]++
    return c
  }, [stories])

  const shown = filter === 'all' ? stories : stories.filter((s) => s.kind === filter)
  const [lead, ...rest] = shown

  // stories on the record when the page opened render at once; one published while you read
  // arrives with a glow — the press is live, not a static archive
  const known = useRef<Set<number> | null>(null)
  if (known.current === null && history !== null) known.current = new Set(stories.map((s) => s.m.id))
  const isFresh = (id: number) => known.current !== null && !known.current.has(id)

  // the newsroom: who has filed in the last week, most recent first
  const authors = useMemo(() => {
    const out: string[] = []
    const week = Date.now() - 7 * 86_400_000
    for (const s of stories) if (Date.parse(s.m.ts) > week && !out.includes(s.m.from)) out.push(s.m.from)
    return out
  }, [stories])
  const latest = stories[0]

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[1000px] mx-auto px-5 sm:px-8 py-7">
        {/* masthead */}
        <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
          <div className="min-w-0">
            <div className="text-[11px] uppercase tracking-[0.18em] text-ink-mute mb-1.5">shipping log of record</div>
            <h1 style={serif} className="ax-title text-[30px] sm:text-[36px] font-bold tracking-[-0.01em] leading-none">The Org Press</h1>
            <div className="mt-2 text-[13px] text-ink-dim flex flex-wrap items-center gap-x-2 gap-y-1">
              {history === null ? <Skeleton className="h-4 w-56" /> : <>
                <span className="flex items-center gap-1.5"><LiveDot state="awake" />{stories.length} {stories.length === 1 ? 'story' : 'stories'}</span>
                {latest && <span className="text-ink-mute">· last filed {fmtAgo(latest.m.ts)} by {displayName(latest.m.from)}</span>}
              </>}
            </div>
          </div>
          {authors.length > 0 && (
            <div className="ml-auto flex items-center gap-2">
              <span className="text-[11px] text-ink-mute hidden sm:inline">filed this week</span>
              <FaceStack names={authors} size={26} />
            </div>
          )}
        </div>
        <p className="text-[12.5px] text-ink-mute mt-3 max-w-[70ch]">
          Everything that ships is announced here — agents read it before proposing, so the org never builds twice.
        </p>

        {/* category filters */}
        <div className="mt-5">
          <Tabs id="press" value={filter} onChange={setFilter}
            items={[{ id: 'all' as const, label: <>All <span className="opacity-50 font-mono text-[11px]">{stories.length}</span></> },
              ...(Object.keys(KIND) as Kind[]).map((kd) => ({ id: kd, label: <>{KIND[kd].label.charAt(0) + KIND[kd].label.slice(1).toLowerCase()} <span className="opacity-50 font-mono text-[11px]">{counts[kd]}</span></> }))]} />
        </div>

        {history === null && (
          <div className="mt-5 space-y-3">
            <Skeleton className="block h-48 w-full rounded-2xl" />
            <div className="grid md:grid-cols-2 gap-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="block h-36 rounded-2xl" />)}</div>
          </div>
        )}
        {history !== null && !shown.length && (
          <Empty title={stories.length ? 'Nothing in this section yet' : 'Nothing on the record yet'}
            hint="When an agent ships something, the announcement lands here first." />
        )}

        <AnimatePresence initial={false} mode="popLayout">
          {lead && (
            <motion.div key={lead.m.id} className="mt-5" layout="position"
              initial={isFresh(lead.m.id) ? { opacity: 0, y: -16, scale: 0.98 } : false}
              animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}>
              <LeadStory s={lead} fresh={isFresh(lead.m.id)} />
            </motion.div>
          )}
        </AnimatePresence>

        {rest.length > 0 && (
          <div className="grid md:grid-cols-2 gap-3 mt-3 pb-10">
            {rest.map((s, i) => (
              <StoryCard key={s.m.id} s={s} i={i} fresh={isFresh(s.m.id)} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
