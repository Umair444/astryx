import { useEffect, useMemo, useRef, useState } from 'react'
import { Drawer, TextInput } from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { AnimatePresence, motion } from 'motion/react'
import { fmtDay } from '../api'
import { useStore } from '../store'
import { nav } from '../App'
import type { Route } from '../App'
import type { Msg } from '../types'
import Message from './Message'
import Composer from './Composer'

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

function ThreadPane({ thread, onOpenAgent }: { thread: string; onOpenAgent: (n: string) => void }) {
  const { messages, who } = useStore()
  const msgs = messages.filter((m) => m.thread === thread)
  const boxRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight })
  }, [msgs.length])
  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-2 border-b border-line flex items-center gap-2 shrink-0">
        <span className="text-xs font-mono text-cyan truncate">🧵 {thread}</span>
        <span className="text-xs text-ink-mute">{msgs.length} messages</span>
        <button
          onClick={() => nav({ tab: 'wire' })}
          className="ml-auto w-6 h-6 grid place-items-center rounded-md text-ink-mute hover:text-ink hover:bg-deck-3 text-lg leading-none transition-colors duration-75"
        >
          ×
        </button>
      </div>
      <div ref={boxRef} className="flex-1 overflow-y-auto py-2">
        {msgs.map((m, i) => (
          <Message key={m.id} m={m} compact={i > 0 && msgs[i - 1].from === m.from} onOpenAgent={onOpenAgent} />
        ))}
      </div>
      {who.owner && <Composer thread={thread} />}
    </div>
  )
}

export default function WireView({ route, onOpenAgent }: { route: Route & { tab: 'wire' }; onOpenAgent: (n: string) => void }) {
  const { messages, loadMax, loadOlder, who } = useStore()
  const isMobile = useMediaQuery('(max-width: 48em)')
  const [query, setQuery] = useState('')
  const [pill, setPill] = useState(false)
  const [loading, setLoading] = useState(false)
  const [exhausted, setExhausted] = useState(false)
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

  const feed = (
    <div className="h-full flex flex-col min-w-0 relative">
      <div className="px-4 py-1.5 border-b border-line shrink-0 flex items-center gap-2">
        <span className="font-semibold text-ink">The Wire</span>
        <span className="text-xs text-ink-mute">{msgs.length} messages</span>
        <TextInput
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
          placeholder="search…"
          size="xs"
          variant="filled"
          ml="auto"
          w={isMobile ? 130 : 220}
          styles={{ input: { background: '#141c3a', border: '1px solid #1d2647' } }}
        />
      </div>
      <div ref={boxRef} onScroll={onScroll} className="flex-1 overflow-y-auto pb-2 relative">
        {!query.trim() && messages.length > 0 && (
          <div className="text-center py-2">
            <button
              onClick={onLoadOlder}
              disabled={loading || exhausted}
              className="text-[11px] px-3 py-1 rounded-full border border-line text-ink-mute hover:text-cyan-soft hover:border-cyan/40 disabled:opacity-40 transition-colors duration-75"
            >
              {exhausted ? 'start of the wire' : loading ? 'loading…' : '↑ load older'}
            </button>
          </div>
        )}
        {!msgs.length && (
          <div className="h-full grid place-items-center text-center text-ink-mute">
            <div>
              <div className="text-3xl mb-2">🌌</div>
              Nothing on the wire{query.trim() ? ' matches' : ' yet'}.
            </div>
          </div>
        )}
        {roots.map((m, i) => {
          const prev = roots[i - 1]
          const day = fmtDay(m.ts)
          const newDay = !prev || fmtDay(prev.ts) !== day
          const replies = m.thread ? byThread.get(m.thread) : null
          const compact =
            !newDay && prev && prev.from === m.from && +new Date(m.ts) - +new Date(prev.ts) < 4 * 60e3 && !m.thread
          return (
            <div key={m.id}>
              {newDay && (
                <div className="flex items-center gap-3 px-4 py-2">
                  <div className="h-px bg-line flex-1" />
                  <span className="text-[11px] text-ink-mute">{day}</span>
                  <div className="h-px bg-line flex-1" />
                </div>
              )}
              <Message
                m={m}
                compact={compact}
                fresh={m.id > loadMax}
                replies={replies && replies.length > 1 ? { count: replies.length - 1, last: replies[replies.length - 1].ts } : null}
                onThread={m.thread ? () => nav({ tab: 'wire', thread: m.thread! }) : undefined}
                onOpenAgent={onOpenAgent}
              />
            </div>
          )
        })}
      </div>
      <AnimatePresence>
        {pill && (
          <motion.button
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            onClick={() => {
              atBottom.current = true
              setPill(false)
              boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight, behavior: 'smooth' })
            }}
            className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10 px-3.5 py-1.5 rounded-full bg-cyan text-deck text-xs font-semibold shadow-lg shadow-cyan/20"
          >
            ↓ new messages
          </motion.button>
        )}
      </AnimatePresence>
      {/* owner composer — thread pane owns it while a thread is open */}
      {who.owner && !route.thread && <Composer />}
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
          styles={{ body: { height: '100%', padding: 0 } }}
        >
          {route.thread && <ThreadPane thread={route.thread} onOpenAgent={onOpenAgent} />}
        </Drawer>
      </>
    )
  }

  return (
    <div className="h-full flex min-w-0">
      <div className="flex-1 min-w-0">{feed}</div>
      {route.thread && (
        <div className="w-[380px] shrink-0 border-l border-line bg-deck-2/40">
          <ThreadPane thread={route.thread} onOpenAgent={onOpenAgent} />
        </div>
      )}
    </div>
  )
}
