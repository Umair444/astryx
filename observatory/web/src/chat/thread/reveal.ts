import { createContext, useContext, useEffect, useState } from 'react'

/* THE REVEAL (owner 14247: "show it token by token … very fast"): an agent's reply that ARRIVES while the conversation is
   open types itself out, word by word, so the reader starts at its first line at once. The backend sends a whole
   message (Claude Code doesn't stream to the wire), so this is the page's own reveal, never a fake wait: ~4,000
   characters a second, a long answer done in 1.5 s at most. History, a refresh and a reopened thread draw at once:
   only a message newer than the conversation's newest when it loaded plays (LiveFrom, set by Turns). Reduced motion:
   off. Each message plays once per page. */

export const LiveFrom = createContext<number>(Infinity)       // ids above this arrived while the reader was here

const CHARS_PER_MS = 4
const MIN_MS = 250, MAX_MS = 1500
const played = new Set<number>()

const still = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

/* how many characters of `total` to show now: `total` for a message that doesn't play */
export function useReveal(id: number, total: number): number {
  const from = useContext(LiveFrom)
  const [plays] = useState(() => id > from && !played.has(id) && !still())
  const [n, setN] = useState(plays ? 0 : total)
  useEffect(() => {
    if (!plays) return
    played.add(id)
    const dur = Math.min(MAX_MS, Math.max(MIN_MS, total / CHARS_PER_MS))
    const t0 = performance.now()
    let raf = 0
    const tick = (now: number) => {
      const k = Math.min(1, (now - t0) / dur)
      setN(k >= 1 ? Infinity : Math.ceil(total * k))
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)        // unmounted mid-way: it was played, so next time it draws whole
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return plays ? n : Infinity
}

/* the first `n` characters of a reply's parts, cut at a word's end (never half a word); a file or canvas shows once
   the text before it has */
export function revealParts<P>(ps: P[], n: number, textOf: (p: P) => string | null, cut: (p: P, text: string) => P): P[] {
  if (n === Infinity) return ps
  const out: P[] = []
  let left = n
  for (const p of ps) {
    const t = textOf(p)
    if (t === null) { if (left > 0) out.push(p); else break; continue }
    if (t.length <= left) { out.push(p); left -= t.length; continue }
    const sp = t.slice(left).search(/\s/)
    out.push(cut(p, t.slice(0, sp < 0 ? t.length : left + sp)))
    break
  }
  return out
}

export const totalText = <P,>(ps: P[], textOf: (p: P) => string | null) => ps.reduce((a, p) => a + (textOf(p)?.length ?? 0), 0)
