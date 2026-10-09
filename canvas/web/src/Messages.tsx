import { useEffect, useRef } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { BASE } from './api'
import { useStore } from './store'
import type { Msg } from './types'
import { Avatar, Markdown, ago } from './ui'

const FILE_TOKEN = /\[\[file:([^\]]+)\]\]/g
const ATTACHED = /<(file|voice) attached(?:, fetch failed: [^>]*)?: ([^>]+)>/g

function prettify(body: string) {
  return body
    .replace(ATTACHED, (_, kind, p) => `\`${kind === 'voice' ? '🎙' : '📎'} ${String(p).split('/').pop()}\``)
    .replace(/\(transcript: ([^)]*)\)/g, '> $1')
}

export function Messages({ thread, msgs, compact }: { thread: string; msgs: Msg[]; compact?: boolean }) {
  const me = useStore(s => s.me)!
  const progress = useStore(s => s.progress[thread])
  const end = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)

  useEffect(() => {
    if (pinned.current) end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [msgs.length, progress?.line])

  return (
    <div ref={box} className="flex-1 min-h-0 overflow-y-auto"
      onScroll={e => { const el = e.currentTarget; pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120 }}>
      <div className={`mx-auto ${compact ? 'px-4' : 'max-w-3xl px-5 md:px-8'} py-6 space-y-6`}>
        {msgs.map(m => <Bubble key={m.id} m={m} mine={m.from === me.wire} msgId={m.id} />)}
        <AnimatePresence>
          {progress && (
            <motion.div key="p" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="flex items-center gap-3">
              <div className="relative">
                <Avatar name={progress.agent} size={28} />
                <span className="absolute inset-0 rounded-full border-2 border-violet/70 border-t-transparent animate-spin" />
              </div>
              <span className="shimmer text-sm font-mono truncate">{progress.line}</span>
            </motion.div>
          )}
        </AnimatePresence>
        <div ref={end} />
      </div>
    </div>
  )
}

function Bubble({ m, mine, msgId }: { m: Msg; mine: boolean; msgId: number }) {
  const page = m.from.startsWith('canvas-')
  const files = [...m.body.matchAll(FILE_TOKEN)].map(x => x[1].trim())
  const text = prettify(m.body.replace(FILE_TOKEN, '').trim())
  if (page) {
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-center">
        <div className="max-w-[90%] text-[12px] text-fg-mute border border-dashed border-line rounded-xl px-3 py-1.5">
          <span className="text-cyan/80">page</span> · {m.intent === 'error' ? 'reported an error' : text.split('\n').slice(1).join(' ').slice(0, 220)}
        </div>
      </motion.div>
    )
  }
  if (mine) {
    return (
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end">
        <div className="max-w-[85%] bg-white/[.07] border border-line rounded-[20px] rounded-br-md px-4 py-2.5">
          <Markdown text={text} />
        </div>
      </motion.div>
    )
  }
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3">
      <Avatar name={m.from} size={28} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2 mb-1">
          <span className="text-sm font-medium">{m.from}</span>
          {m.intent !== 'chat' && <span className="text-[10px] uppercase tracking-wider text-violet/90">{m.intent}</span>}
          <span className="text-[11px] text-fg-mute">{ago(m.ts)}</span>
        </div>
        {text && <Markdown text={text} className="text-[15px]" />}
        {files.map((f, i) => <FileChip key={i} msgId={msgId} n={i} path={f} />)}
      </div>
    </motion.div>
  )
}

function FileChip({ msgId, n, path }: { msgId: number; n: number; path: string }) {
  const url = `${BASE}api/file?msg=${msgId}&n=${n}`
  const name = path.split('/').pop() ?? path
  if (/\.(png|jpe?g|gif|webp|svg)$/i.test(name)) {
    return <a href={url} target="_blank" rel="noreferrer"><img src={url} alt={name} className="mt-2 max-h-80 rounded-2xl border border-line" /></a>
  }
  if (/\.(mp3|ogg|wav|m4a|webm)$/i.test(name)) return <audio controls src={url} className="mt-2 w-full max-w-sm" />
  return (
    <a href={url} download={name} className="mt-2 inline-flex items-center gap-2 text-sm bg-white/[.06] hover:bg-white/[.1] border border-line rounded-xl px-3 py-2">
      📎 {name}
    </a>
  )
}
