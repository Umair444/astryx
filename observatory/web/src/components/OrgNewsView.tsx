import { useEffect, useMemo, useState } from 'react'
import { motion } from 'motion/react'
import { api, avatarInitial, displayName, fmtDay, fmtTime } from '../api'
import { useStore } from '../store'
import type { Msg } from '../types'
import Md from './Md'

/* The Press — org-news rendered as a news surface (Ground-News-style cards).
   Category = who actually wrote it, not decoration:
     charter  — the scribe's auto-post on a ratified charter commit
     tools    — tool_ship_watch's auto-receipt for new capabilities
     dispatch — an agent posting a milestone in its own voice
   Issue numbers appear only on posts that carry one (#N) — real sequence,
   not ornament. */

type Kind = 'charter' | 'tools' | 'dispatch'

const KIND: Record<Kind, { label: string; color: string; bg: string; border: string }> = {
  charter: { label: 'CHARTER', color: 'text-amber-400', bg: 'bg-amber-400/10', border: 'border-amber-400/30' },
  tools: { label: 'TOOLING', color: 'text-cyan', bg: 'bg-cyan/10', border: 'border-cyan/30' },
  dispatch: { label: 'DISPATCH', color: 'text-violet-400', bg: 'bg-violet-400/10', border: 'border-violet-400/30' },
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

function Byline({ s, expanded }: { s: Story; expanded: boolean }) {
  return (
    <div className="flex items-center gap-2 mt-auto pt-3">
      <span className="w-5 h-5 rounded-full grid place-items-center text-[10px] font-bold bg-deck-3 border border-line text-cyan-soft shrink-0">
        {avatarInitial(s.m.from)}
      </span>
      <span className="text-xs text-ink-mute font-mono">{displayName(s.m.from)}</span>
      <span className="text-[11px] text-ink-mute/60">·</span>
      <span className="text-[11px] text-ink-mute/80" title={new Date(s.m.ts).toLocaleString()}>
        {fmtDay(s.m.ts)} {fmtTime(s.m.ts)}
      </span>
      {s.dek && (
        <span className="ml-auto text-[11px] text-ink-mute/60 group-hover:text-cyan-soft transition-colors duration-75">
          {expanded ? '▴ collapse' : '▾ read'}
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

const serif = { fontFamily: "Georgia, 'Iowan Old Style', 'Times New Roman', serif" }

function LeadStory({ s }: { s: Story }) {
  const [open, setOpen] = useState(false)
  const k = KIND[s.kind]
  return (
    <motion.article
      layout="position"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      onClick={() => s.dek && setOpen((v) => !v)}
      className={`group relative rounded-xl border ${k.border} bg-deck-2/60 hover:bg-deck-2 transition-colors duration-100 p-5 pl-7 flex flex-col ${s.dek ? 'cursor-pointer' : ''}`}
    >
      {/* signature: the lead's category rail */}
      <div className={`absolute left-0 top-0 bottom-0 w-[5px] rounded-l-xl ${k.bg.replace('/10', '/70')}`} />
      <div className="flex items-center gap-2">
        <Kicker s={s} />
        <span className="ml-auto text-[10px] font-mono tracking-[0.2em] text-ink-mute/50">LATEST</span>
      </div>
      <h2 style={serif} className="text-ink text-[22px] leading-snug font-semibold mt-2.5 [text-wrap:balance]">
        {s.headline}
      </h2>
      {s.dek && !open && (
        <p className="text-sm text-ink-mute leading-relaxed mt-2 line-clamp-3 whitespace-pre-line">{s.dek}</p>
      )}
      {s.dek && open && (
        <div className="text-sm mt-2" onClick={(e) => e.stopPropagation()}>
          <Md text={s.dek} />
        </div>
      )}
      <Byline s={s} expanded={open} />
    </motion.article>
  )
}

function StoryCard({ s, i }: { s: Story; i: number }) {
  const [open, setOpen] = useState(false)
  const k = KIND[s.kind]
  return (
    <motion.article
      layout="position"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(i * 0.03, 0.3) }}
      onClick={() => s.dek && setOpen((v) => !v)}
      className={`group rounded-xl border border-line bg-deck-2/40 hover:bg-deck-2 hover:border-line/80 transition-colors duration-100 p-4 flex flex-col ${s.dek ? 'cursor-pointer' : ''} ${open ? 'md:col-span-2' : ''}`}
    >
      <Kicker s={s} />
      <h3 style={serif} className="text-ink text-[16.5px] leading-snug font-semibold mt-2 [text-wrap:balance]">
        {s.headline}
      </h3>
      {s.dek && !open && (
        <p className="text-[13px] text-ink-mute leading-relaxed mt-1.5 line-clamp-3 whitespace-pre-line">{s.dek}</p>
      )}
      {s.dek && open && (
        <div className="text-[13px] mt-1.5" onClick={(e) => e.stopPropagation()}>
          <Md text={s.dek} />
        </div>
      )}
      <Byline s={s} expanded={open} />
    </motion.article>
  )
}

export default function OrgNewsView() {
  const { messages } = useStore()
  const [history, setHistory] = useState<Msg[]>([])
  const [filter, setFilter] = useState<Kind | 'all'>('all')

  useEffect(() => {
    api<Msg[]>('/messages?thread=org-news&limit=500').then(setHistory).catch(() => {})
  }, [])

  const stories = useMemo(() => {
    // full fetched history + anything fresh the SSE stream delivered since
    const seen = new Set(history.map((m) => m.id))
    const live = messages.filter((m) => m.thread === 'org-news' && !seen.has(m.id))
    return [...history, ...live]
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

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto px-4 py-5">
        {/* masthead */}
        <div className="flex items-end gap-3 flex-wrap">
          <h1 style={serif} className="text-ink text-[26px] font-bold tracking-tight leading-none">
            The Org Press
          </h1>
          <span className="text-[11px] font-mono text-ink-mute/70 tracking-[0.14em] pb-0.5">
            SHIPPING LOG OF RECORD · {stories.length} {stories.length === 1 ? 'STORY' : 'STORIES'}
          </span>
        </div>
        <p className="text-xs text-ink-mute mt-1">
          Everything that ships is announced here — agents read it before proposing, so the org never builds twice.
        </p>

        {/* category filters */}
        <div className="flex items-center gap-1.5 mt-4 flex-wrap">
          <button
            onClick={() => setFilter('all')}
            className={`text-[11px] font-mono px-2.5 py-1 rounded-full border transition-colors duration-75 ${
              filter === 'all' ? 'border-cyan/50 text-cyan bg-cyan/10' : 'border-line text-ink-mute hover:text-ink'
            }`}
          >
            All
          </button>
          {(Object.keys(KIND) as Kind[]).map((kd) => (
            <button
              key={kd}
              onClick={() => setFilter(filter === kd ? 'all' : kd)}
              className={`text-[11px] font-mono px-2.5 py-1 rounded-full border transition-colors duration-75 ${
                filter === kd ? `${KIND[kd].border} ${KIND[kd].color} ${KIND[kd].bg}` : 'border-line text-ink-mute hover:text-ink'
              }`}
            >
              {KIND[kd].label.charAt(0) + KIND[kd].label.slice(1).toLowerCase()} <span className="opacity-60">{counts[kd]}</span>
            </button>
          ))}
        </div>

        {!stories.length && (
          <div className="text-center text-ink-mute py-16">
            <div className="text-3xl mb-2">📰</div>
            Nothing on the record yet.
          </div>
        )}

        {lead && (
          <div className="mt-4">
            <LeadStory s={lead} />
          </div>
        )}

        {rest.length > 0 && (
          <div className="grid md:grid-cols-2 gap-3 mt-3 pb-8">
            {rest.map((s, i) => (
              <StoryCard key={s.m.id} s={s} i={i} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
