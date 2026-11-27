import type { Anchor } from './types'

/* ANCHORING (DESIGN.md principle 10): an annotation hangs from a QUOTE plus 32 characters of context each side, with
   the text offsets as a hint, never from DOM positions. Every render of a viewer is read back into a flat string (its
   text nodes, in document order), and each anchor is searched for in it: the hinted offsets if they still hold the
   quote, else the occurrence whose context matches best, else the same with whitespace collapsed (a PDF text layer or a
   re-wrapped paragraph), else the stretch between the surviving prefix and suffix (the quote itself was edited). What
   none of those places is ORPHANED and says so in the margin; it is never silently dropped. */

export const CONTEXT = 32

/* a text root: the element a viewer marks data-ann-root (a PDF has one per page, with its page number) */
export interface TextIndex { root: Element; page?: number; text: string; nodes: Text[]; starts: number[] }

/* text that is not the document's: a code gutter, a sort arrow, our own insert widgets */
const SKIP = '[data-ann-skip], [data-ann-widget], [aria-hidden="true"]'

export function indexOf(root: Element): TextIndex {
  const nodes: Text[] = [], starts: number[] = []
  let text = ''
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement?.closest(SKIP) && root.contains(n.parentElement.closest(SKIP)) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  })
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const t = n as Text
    if (!t.data) continue
    nodes.push(t); starts.push(text.length); text += t.data
  }
  const p = root.closest('[data-page]')?.getAttribute('data-page')
  return { root, page: p ? Number(p) : undefined, text, nodes, starts }
}

/* a DOM boundary point → a text offset (a point between nodes counts as the start of the next indexed text) */
export function offsetOf(ix: TextIndex, node: Node, offset: number): number {
  if (node.nodeType === Node.TEXT_NODE) {
    const i = ix.nodes.indexOf(node as Text)
    if (i >= 0) return ix.starts[i] + Math.min(offset, (node as Text).data.length)
  }
  const r = document.createRange()
  try { r.setStart(node, offset) } catch { return 0 }
  // the first indexed node at or after the point (binary search: the nodes are in document order)
  let lo = 0, hi = ix.nodes.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (r.comparePoint(ix.nodes[mid], 0) >= 0) hi = mid; else lo = mid + 1
  }
  return lo < ix.nodes.length ? ix.starts[lo] : ix.text.length
}

/* a selection inside one root → its anchor (whitespace at the edges trimmed off the quote) */
export function describe(ix: TextIndex, range: Range): Anchor | null {
  let start = offsetOf(ix, range.startContainer, range.startOffset)
  let end = ix.root.contains(range.endContainer) ? offsetOf(ix, range.endContainer, range.endOffset) : ix.text.length
  while (start < end && /\s/.test(ix.text[start])) start++
  while (end > start && /\s/.test(ix.text[end - 1])) end--
  if (end <= start) return null
  return {
    quote: ix.text.slice(start, end),
    prefix: ix.text.slice(Math.max(0, start - CONTEXT), start),
    suffix: ix.text.slice(end, end + CONTEXT),
    start, end,
    ...(ix.page ? { page: ix.page } : {}),
  }
}

export interface Placed { start: number; end: number; fuzzy?: boolean }

/* how much of the context still surrounds a candidate: the common tail of the prefix + the common head of the suffix */
function score(text: string, a: Anchor, s: number, e: number): number {
  let n = 0
  const pre = a.prefix ?? '', suf = a.suffix ?? ''
  for (let i = 1; i <= pre.length && s - i >= 0 && text[s - i] === pre[pre.length - i]; i++) n++
  for (let i = 0; i < suf.length && e + i < text.length && text[e + i] === suf[i]; i++) n++
  return n
}
/* the occurrence of `quote` in `hay` whose context (read in the ORIGINAL text) fits best, ties to the nearest hint */
function best(hay: string, orig: string, a: Anchor, quote: string, map?: (i: number) => number): Placed | null {
  let pick: Placed | null = null, top = -1, near = Infinity
  for (let i = hay.indexOf(quote), k = 0; i >= 0 && k < 2000; i = hay.indexOf(quote, i + 1), k++) {
    const s = map ? map(i) : i, e = map ? map(i + quote.length - 1) + 1 : i + quote.length
    const sc = score(orig, a, s, e)
    const d = Math.abs(s - (a.start ?? s))
    if (sc > top || (sc === top && d < near)) { pick = { start: s, end: e }; top = sc; near = d }
  }
  return pick
}

/* whitespace-collapsed copy of a text, with the map back to the original offsets */
function squash(text: string): { s: string; at: number[] } {
  let s = ''
  const at: number[] = []
  let gap = false
  for (let i = 0; i < text.length; i++) {
    if (/\s/.test(text[i])) { if (!gap && s) { s += ' '; at.push(i) } gap = true; continue }
    gap = false; s += text[i]; at.push(i)
  }
  return { s, at }
}

export function locate(text: string, a: Anchor): Placed | null {
  const q = a.quote
  if (!q) return null
  // 1. the hint still holds
  if (a.start != null && a.end != null && text.slice(a.start, a.end) === q) return { start: a.start, end: a.end }
  // 2. the quote, where its context fits best
  const exact = best(text, text, a, q)
  if (exact) return exact
  // 3. the quote with whitespace collapsed (a re-wrapped paragraph, a PDF's spacing)
  const sq = squash(text), qq = squash(q).s.trim()
  if (qq.length >= 3) {
    const m = best(sq.s, text, a, qq, (i) => sq.at[i])
    if (m) return { ...m, fuzzy: true }
  }
  // 4. the quote was edited: what now lies between its surviving context
  const pre = (a.prefix ?? '').slice(-16), suf = (a.suffix ?? '').slice(0, 16)
  if (pre.length >= 6 && suf.length >= 6) {
    let bestP: Placed | null = null, near = Infinity
    for (let i = text.indexOf(pre), k = 0; i >= 0 && k < 200; i = text.indexOf(pre, i + 1), k++) {
      const s = i + pre.length
      const j = text.indexOf(suf, s)
      if (j < 0) break
      const len = j - s
      if (len < Math.max(1, q.length * 0.4) || len > q.length * 2.5 + 20) continue
      const d = Math.abs(s - (a.start ?? s))
      if (d < near) { bestP = { start: s, end: j, fuzzy: true }; near = d }
    }
    if (bestP) return bestP
  }
  return null
}

/* text offsets → a live DOM Range over the root's text nodes */
export function toRange(ix: TextIndex, start: number, end: number): Range | null {
  const at = (pos: number, isEnd: boolean): [Text, number] | null => {
    let lo = 0, hi = ix.nodes.length - 1, hit = -1
    while (lo <= hi) {
      const mid = (lo + hi) >> 1
      if (ix.starts[mid] <= pos) { hit = mid; lo = mid + 1 } else hi = mid - 1
    }
    if (hit < 0) return null
    // an end exactly at a node's start belongs to the previous node's end (no empty leading fragment)
    if (isEnd && hit > 0 && ix.starts[hit] === pos) hit--
    const n = ix.nodes[hit]
    return [n, Math.min(pos - ix.starts[hit], n.data.length)]
  }
  const s = at(start, false), e = at(end, true)
  if (!s || !e) return null
  const r = document.createRange()
  try { r.setStart(s[0], s[1]); r.setEnd(e[0], e[1]) } catch { return null }
  return r
}
