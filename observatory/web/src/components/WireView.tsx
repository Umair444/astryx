import { useEffect, useMemo, useRef, useState } from 'react'
import { Drawer } from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { AnimatePresence, motion } from 'motion/react'
import { apiPost, fmtAgo, fmtDay } from '../api'
import { useStore } from '../store'
import { nav } from '../App'
import type { Route } from '../App'
import type { Msg } from '../types'
import Message, { IntentChip, partyLabel } from './Message'
import Composer from './Composer'
import OrgNewsView from './OrgNewsView'
import RoutesView from './RoutesView'
import AgentFace from './AgentFace'
import { Empty, FaceStack, LiveDot, Panel, Skeleton, Tabs, ViewHeader, useNow } from '../ui/kit'

/* THE WIRE — the org talking. Every message is a person speaking (a face, a name, who it's for);
   a named thread is a ROOM: a card with the people in it, how it opened and where it is now,
   which opens beside the feed. New words arrive live. Nothing here knows what any org does. */

const LIVE_MS = 2 * 60_000 // a thread whose last word is this recent is "live now"

/* Thread grouping — named-thread model. A thread key groups every message
   carrying it; the earliest message acts as the root card in the feed. */
function groupThreads(msgs: Msg[]) {
  const roots: Msg[] = []
  const byThread = new Map<string, Msg[]>()
  for (const m of msgs) {
    if (m.thread) {
      const arr = byThread.get(m.thread) ?? []
      arr.push(m)
      byThread.set(m.thread, arr)
    } else roots.push(m)
  }
  for (const [key, arr] of byThread) {
    arr.sort((a, b) => a.id - b.id)
    roots.push({ ...arr[0], thread: key })
  }
  roots.sort((a, b) => a.id - b.id)
  return { roots, byThread }
}

/** A thread key, said as a human would: plans by their goal, canvas chats as chats. */
function threadTitle(key: string) {
  const plan = /^plan-(\d+)$/.exec(key)
  if (plan) return `Plan · goal #${plan[1]}`
  if (key.startsWith('cv:')) return 'Canvas chat'
  if (/^t-[a-z0-9]+$/i.test(key)) return 'Conversation'
  return key
}

/** The AGENTS in a set of messages, in order of first word. Channel humans and peers are not
 *  faces here — a room shows who on the team is in it. */
function participants(msgs: Msg[], agents: Set<string>) {
  const out: string[] = []
  for (const m of msgs)
    for (const n of [m.from, m.to])
      if (n && agents.has(n) && !out.includes(n)) out.push(n)
  return out
}

function ThreadCard({ root, all, agents, open, fresh, now, onOpen }: {
  root: Msg; all: Msg[]; agents: Set<string>; open: boolean; fresh: boolean; now: number; onOpen: () => void
}) {
  const { overview } = useStore()
  const last = all[all.length - 1]
  const live = now - Date.parse(last.ts) < LIVE_MS
  const people = participants(all, agents)
  const home = overview?.org
  return (
    <motion.div className="mx-3 sm:mx-4 my-2"
      initial={fresh ? { opacity: 0, y: 14, filter: 'blur(3px)' } : false}
      animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }} transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}>
      <Panel as="button" interactive live={live} onClick={onOpen}
        className={`w-full p-3.5 sm:p-4 flex flex-col gap-2.5 ${open ? '!border-cyan/60' : ''}`}>
        <div className="flex items-center gap-2.5 w-full min-w-0">
          <FaceStack names={people} size={22} max={5} />
          <span className="text-[13px] font-semibold text-ink truncate">{threadTitle(root.thread!)}</span>
          {live && <span className="flex items-center gap-1.5 text-[11px] text-cyan shrink-0"><LiveDot state="working" />live</span>}
          <span className="ml-auto text-[11px] text-ink-mute shrink-0 tabular-nums">{all.length} msg · {fmtAgo(last.ts)}</span>
        </div>
        <div className="flex gap-2.5 w-full text-left">
          <AgentFace name={root.from} size={26} title={partyLabel(root.from, root.from_org, home)} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-[12px]">
              <span className="font-semibold text-ink">{partyLabel(root.from, root.from_org, home)}</span>
              {root.intent && root.intent !== 'chat' && <IntentChip intent={root.intent} />}
            </div>
            <div className="text-[13.5px] leading-snug text-ink/85 line-clamp-2 break-words mt-0.5">{root.body}</div>
          </div>
        </div>
        {all.length > 1 && (
          <div className="flex items-center gap-2 w-full text-left pl-2.5 ml-[13px] border-l border-line/80">
            <AgentFace name={last.from} size={18} title={partyLabel(last.from, last.from_org, home)} />
            <span className="text-[12px] font-medium text-ink-dim shrink-0">{partyLabel(last.from, last.from_org, home)}</span>
            <span className="text-[12px] text-ink-mute truncate min-w-0">{last.body}</span>
          </div>
        )}
      </Panel>
    </motion.div>
  )
}

function ThreadPane({ thread, onOpenAgent }: { thread: string; onOpenAgent: (n: string) => void }) {
  const { messages, who, agents } = useStore()
  const msgs = messages.filter((m) => m.thread === thread)
  const names = useMemo(() => new Set(agents.map((a) => a.agent)), [agents])
  const people = participants(msgs, names)
  const boxRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight, behavior: 'smooth' })
  }, [msgs.length])
  // Opening the pane is the owner reading it: the server marks the pending replies to him on this thread,
  // up to the newest one shown here (never the feed, which only shows). A reply arriving while it is open is
  // read too, so the mark follows the newest id.
  const toOwner = msgs.filter((m) => m.to === 'owner' && m.from !== 'owner' && (m.to_org ?? 'local') === 'local')
  const upto = toOwner.length ? toOwner[toOwner.length - 1].id : 0
  useEffect(() => {
    if (who.owner && upto) apiPost('/thread/read', { thread, upto }).catch(() => {})
  }, [thread, upto, who.owner])
  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-3 border-b border-line flex items-center gap-3 shrink-0">
        <FaceStack names={people} size={26} max={4} />
        <div className="min-w-0">
          <div className="text-[14px] font-semibold text-ink truncate">{threadTitle(thread)}</div>
          <div className="text-[11px] text-ink-mute truncate font-mono">{thread} · {msgs.length} messages</div>
        </div>
        <button
          onClick={() => nav({ tab: 'wire' })}
          aria-label="close thread"
          className="ml-auto w-8 h-8 shrink-0 grid place-items-center rounded-lg text-ink-mute hover:text-ink hover:bg-deck-3 text-lg leading-none transition-colors"
        >
          ×
        </button>
      </div>
      <div ref={boxRef} className="flex-1 overflow-y-auto py-2">
        {msgs.length === 0 && <Empty title="This thread is outside the loaded window" hint="Load older messages in the feed to bring it in." />}
        {msgs.map((m, i) => {
          const prev = msgs[i - 1]
          const compact = !!prev && prev.from === m.from && +new Date(m.ts) - +new Date(prev.ts) < 4 * 60e3
          return <Message key={m.id} m={m} compact={compact} onOpenAgent={onOpenAgent} />
        })}
      </div>
      {who.owner && <Composer thread={thread} />}
    </div>
  )
}

function FeedSkeleton() {
  return (
    <div className="px-5 py-4 space-y-5">
      {[0.9, 0.6, 0.75, 0.5, 0.8].map((w, i) => (
        <div key={i} className="flex gap-3">
          <Skeleton className="w-9 h-9 !rounded-full shrink-0" />
          <div className="flex-1 space-y-2 pt-1">
            <Skeleton className="h-3 w-40" />
            <Skeleton className="h-3" />
            <Skeleton className="h-3 block" />
            <span className="block" style={{ width: `${w * 100}%` }}><Skeleton className="h-3 w-full" /></span>
          </div>
        </div>
      ))}
    </div>
  )
}

const VIEWS = [
  { id: 'feed', label: 'Feed' },
  { id: 'press', label: 'Press' },
  { id: 'wiring', label: 'Wiring' },
] as const

export default function WireView({ route, onOpenAgent }: { route: Route & { tab: 'wire' }; onOpenAgent: (n: string) => void }) {
  const { messages, loadMax, loadOlder, who, agents } = useStore()
  const isMobile = useMediaQuery('(max-width: 48em)')
  const now = useNow(10_000)
  // Feed / Press (org-news) / Wiring (routes) — ?press=1 deep-links to the Press
  const [view, setView] = useState<'feed' | 'press' | 'wiring'>(() =>
    new URLSearchParams(location.search).has('press') ? 'press' : 'feed',
  )
  const [query, setQuery] = useState('')
  const [pill, setPill] = useState(false)
  const [loading, setLoading] = useState(false)
  const [exhausted, setExhausted] = useState(false)
  // the store has no "loaded" flag: the feed counts as settled once rows arrive, or after a grace
  // period — so an empty wire says so instead of shimmering forever, and a loading one never says "empty"
  const [settled, setSettled] = useState(false)
  useEffect(() => {
    if (messages.length) { setSettled(true); return }
    const t = setTimeout(() => setSettled(true), 3500)
    return () => clearTimeout(t)
  }, [messages.length])

  const names = useMemo(() => new Set(agents.map((a) => a.agent)), [agents])
  const msgs = useMemo(() => {
    if (!query.trim()) return messages
    const q = query.toLowerCase()
    return messages.filter(
      (m) =>
        m.body.toLowerCase().includes(q) ||
        m.from.toLowerCase().includes(q) ||
        (m.to ?? '').toLowerCase().includes(q) ||
        (m.intent ?? '').toLowerCase().includes(q),
    )
  }, [messages, query])
  const boxRef = useRef<HTMLDivElement>(null)
  const atBottom = useRef(true)
  const didInitialScroll = useRef(false)

  // stick to bottom only if the reader is already there; otherwise offer the pill
  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    if (atBottom.current) {
      el.scrollTo({ top: el.scrollHeight, behavior: didInitialScroll.current ? 'smooth' : 'auto' })
      didInitialScroll.current = true
    } else {
      setPill(true)
    }
  }, [msgs.length]) // eslint-disable-line react-hooks/exhaustive-deps

  function onScroll() {
    const el = boxRef.current
    if (!el) return
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
    if (atBottom.current) setPill(false)
  }

  async function onLoadOlder() {
    const el = boxRef.current
    const keep = el ? el.scrollHeight - el.scrollTop : 0
    setLoading(true)
    const n = await loadOlder()
    setLoading(false)
    if (n === 0) setExhausted(true)
    // hold the viewport still while history grows above
    requestAnimationFrame(() => {
      if (el) el.scrollTop = el.scrollHeight - keep
    })
  }

  const { roots, byThread } = useMemo(() => groupThreads(msgs), [msgs])

  // the live sentence: how busy the wire is this hour, and whose voices are in it
  const hour = useMemo(() => messages.filter((m) => now - Date.parse(m.ts) < 3600_000), [messages, now])
  const rooms = new Set(hour.map((m) => m.thread).filter(Boolean)).size
  const voices = useMemo(() => {
    const out: string[] = []
    for (let i = messages.length - 1; i >= 0 && out.length < 6; i--) {
      const m = messages[i]
      if (now - Date.parse(m.ts) > 30 * 60_000) break
      if (names.has(m.from) && !out.includes(m.from)) out.push(m.from)
    }
    return out
  }, [messages, names, now])

  const tabs = who.owner ? VIEWS : VIEWS.filter((v) => v.id !== 'wiring')

  const feed = (
    <div className="h-full flex flex-col min-w-0 relative">
      <div className="px-4 sm:px-8 pt-5 sm:pt-7 shrink-0">
        {/* the Press and the Wiring carry their own mastheads; the wire's header is the Feed's */}
        {view === 'feed' && <ViewHeader
          kicker="the wire"
          title="The Wire"
          live={settled ? (
            <>
              <span className="flex items-center gap-1.5"><LiveDot state={hour.length ? 'working' : 'awake'} />{hour.length} message{hour.length === 1 ? '' : 's'} this hour</span>
              <span className="text-ink-mute">·</span>
              <span>{rooms} active thread{rooms === 1 ? '' : 's'}</span>
              <span className="text-ink-mute hidden sm:inline">· every word the org says, as it says it</span>
            </>
          ) : <Skeleton className="h-3.5 w-64" />}
          faces={voices}
        />}
        <div className={`flex items-center gap-2 flex-wrap mb-3 ${view === 'feed' ? '-mt-2' : ''}`}>
          <Tabs id="wire" items={tabs} value={view} onChange={setView} />
          {view === 'feed' && (
            <label className="ax-panel ml-auto flex items-center gap-2 rounded-xl px-3 h-[38px] w-full sm:w-[260px] focus-within:border-cyan/50 transition-colors">
              <span className="text-ink-mute text-[13px]">⌕</span>
              <input
                value={query}
                onChange={(e) => setQuery(e.currentTarget.value)}
                placeholder="Search the wire…"
                aria-label="search the wire"
                className="flex-1 min-w-0 bg-transparent outline-none text-[13px] text-ink placeholder:text-ink-mute"
              />
              {query && <button onClick={() => setQuery('')} className="text-ink-mute hover:text-ink text-[13px]" aria-label="clear search">×</button>}
            </label>
          )}
        </div>
      </div>
      {view === 'press' && (
        <div className="flex-1 min-h-0">
          <OrgNewsView />
        </div>
      )}
      {view === 'wiring' && (
        <div className="flex-1 min-h-0">
          <RoutesView />
        </div>
      )}
      {view === 'feed' && (
        <div ref={boxRef} onScroll={onScroll} className="flex-1 overflow-y-auto pb-2 relative border-t border-line/60">
          <div className="max-w-[960px] mx-auto">
            {!query.trim() && messages.length > 0 && (
              <div className="text-center py-3">
                <button
                  onClick={onLoadOlder}
                  disabled={loading || exhausted}
                  className="text-[11px] px-3.5 py-1.5 rounded-full border border-line bg-deck-2/50 text-ink-mute hover:text-ink hover:border-cyan/40 disabled:opacity-40 transition-colors"
                >
                  {exhausted ? 'the start of the wire' : loading ? 'loading…' : '↑ load older'}
                </button>
              </div>
            )}
            {!settled && !msgs.length && <FeedSkeleton />}
            {settled && !msgs.length && (
              <Empty
                title={query.trim() ? `Nothing on the wire matches “${query.trim()}”` : 'The wire is quiet'}
                hint={query.trim() ? 'Try a name, an intent, or fewer words.' : 'When the agents speak to each other — or to you — it appears here as it happens.'}
              />
            )}
            {roots.map((m, i) => {
              const prev = roots[i - 1]
              const day = fmtDay(m.ts)
              const newDay = !prev || fmtDay(prev.ts) !== day
              const thread = m.thread ? byThread.get(m.thread)! : null
              const compact =
                !newDay && prev && prev.from === m.from && !prev.thread && +new Date(m.ts) - +new Date(prev.ts) < 4 * 60e3 && !m.thread
              return (
                <div key={m.thread ? `t:${m.thread}` : m.id}>
                  {newDay && (
                    <div className="flex items-center gap-3 px-6 pt-5 pb-2">
                      <div className="h-px bg-gradient-to-r from-transparent to-line flex-1" />
                      <span className="text-[11px] uppercase tracking-[0.14em] text-ink-mute">{day}</span>
                      <div className="h-px bg-gradient-to-l from-transparent to-line flex-1" />
                    </div>
                  )}
                  {thread ? (
                    <ThreadCard
                      root={m}
                      all={thread}
                      agents={names}
                      open={route.thread === m.thread}
                      fresh={m.id > loadMax}
                      now={now}
                      onOpen={() => nav({ tab: 'wire', thread: m.thread! })}
                    />
                  ) : (
                    <Message m={m} compact={compact} fresh={m.id > loadMax} onOpenAgent={onOpenAgent} />
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      <AnimatePresence>
        {pill && view === 'feed' && (
          <motion.button
            initial={{ opacity: 0, y: 10, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.96 }}
            onClick={() => {
              atBottom.current = true
              setPill(false)
              boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight, behavior: 'smooth' })
            }}
            className="ax-action absolute bottom-24 left-1/2 -translate-x-1/2 z-10 !px-4 !py-1.5 !rounded-full !text-[12px]"
          >
            ↓ new messages
          </motion.button>
        )}
      </AnimatePresence>
      {/* owner composer — thread pane owns it while a thread is open */}
      {who.owner && !route.thread && view === 'feed' && <Composer />}
    </div>
  )

  if (isMobile) {
    return (
      <>
        {feed}
        <Drawer
          opened={!!route.thread}
          onClose={() => nav({ tab: 'wire' })}
          position="right"
          size="100%"
          withCloseButton={false}
          padding={0}
          styles={{ body: { height: '100%', padding: 0 }, content: { background: 'var(--t-bg)' } }}
        >
          {route.thread && <ThreadPane thread={route.thread} onOpenAgent={onOpenAgent} />}
        </Drawer>
      </>
    )
  }

  return (
    <div className="h-full flex min-w-0">
      <div className="flex-1 min-w-0">{feed}</div>
      <AnimatePresence>
        {route.thread && (
          <motion.div key="pane"
            initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="w-[420px] xl:w-[460px] shrink-0 border-l border-line bg-deck-2/55 backdrop-blur-xl">
            <ThreadPane thread={route.thread} onOpenAgent={onOpenAgent} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

