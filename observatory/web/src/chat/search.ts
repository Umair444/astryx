import { useEffect, useState } from 'react'
import { api } from '../api'
import './search.css'

/* Full-text search over the owner's conversations (iteration 8): GET /api/ws/search (observatory/api/workspace.py)
   matches the bodies of the threads the list shows and answers newest first, each hit a snippet already stripped of
   file embeds, project blocks and margin markers, with the matched spans as offsets into it. The list and the ⌘K
   palette both ask through useMessageSearch: debounced, at least two characters, the stale answer never lands. */

export interface MessageHit {
  thread: string
  msg_id: number
  ts: string
  from: string
  to: string | null
  snippet: string
  marks: [number, number][]
}

export const SEARCH_MIN = 2
/* scope (cog-gaps): the same VIEW as the list: 'mine' (the server's default) or every human's conversations */
export const searchMessages = (q: string, limit = 20, scope: 'mine' | 'everyone' = 'mine') =>
  api<{ q: string; results: MessageHit[] }>(`/ws/search?q=${encodeURIComponent(q)}&limit=${limit}${scope === 'everyone' ? '&scope=everyone' : ''}`).then((r) => r.results)

/* null = not asked (too short) or still asking the first time; [] = asked, nothing */
export function useMessageSearch(q: string, limit = 20, delay = 180, scope: 'mine' | 'everyone' = 'mine'): { hits: MessageHit[] | null; busy: boolean } {
  const [hits, setHits] = useState<MessageHit[] | null>(null)
  const [busy, setBusy] = useState(false)
  const s = q.trim()
  useEffect(() => {
    if (s.length < SEARCH_MIN) { setHits(null); setBusy(false); return }
    let live = true
    setBusy(true)
    const t = setTimeout(() => {
      searchMessages(s, limit, scope)
        .then((r) => { if (live) setHits(r) })
        .catch(() => { if (live) setHits([]) })
        .finally(() => { if (live) setBusy(false) })
    }, delay)
    return () => { live = false; clearTimeout(t) }
  }, [s, limit, delay, scope])
  return { hits: s.length < SEARCH_MIN ? null : hits, busy }
}

/* a hit's snippet with less before the first match (the server keeps ~48 characters of lead for the list's two lines;
   the palette's narrower first line wants the match in view): cut at a word, "…" kept, the marks shifted with it */
export function tighten(h: Pick<MessageHit, 'snippet' | 'marks'>, lead = 22): { text: string; marks: [number, number][] } {
  const first = h.marks[0]?.[0] ?? 0
  if (first <= lead + 2) return { text: h.snippet, marks: h.marks }
  let cut = first - lead
  const sp = h.snippet.indexOf(' ', cut)
  if (sp >= 0 && sp < first) cut = sp + 1
  return { text: '…' + h.snippet.slice(cut), marks: h.marks.filter(([a]) => a >= cut).map(([a, b]) => [a - cut + 1, b - cut + 1]) }
}

/* A request to open a thread AT a message: the conversation scrolls to it and pulses it once (thread/focus.ts).
   `n` makes the same message, asked twice, a second request. */
export interface Jump { thread: string; id: number; n: number }
