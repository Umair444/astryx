/* PAINTING. Where the browser has the CSS Custom Highlight API (Chromium 105+, Safari 17.2+, Firefox 140+), a
   highlight is a set of live Ranges registered under a name and styled by `::highlight(name)` in workspace.css: the
   viewer's DOM is never touched, so React, pdf.js and docx-preview keep their nodes. Elsewhere each range is wrapped
   in <mark data-ann-mark> (and unwrapped before the next paint).

   One thing the API cannot draw is NEW text: a suggestion's replacement is a small <ins data-ann-widget> placed right
   after the struck words. Widgets (and fallback marks) are the only nodes this layer adds; the text index skips them,
   and the caller pauses its MutationObserver around paint() so they don't trigger a repaint of their own. */

export type Group = 'yellow' | 'green' | 'blue' | 'pink' | 'comment' | 'ask' | 'suggest' | 'active' | 'focus'
export const GROUPS: Group[] = ['yellow', 'green', 'blue', 'pink', 'comment', 'ask', 'suggest', 'active', 'focus']

type HL = { new (...r: Range[]): unknown }
const api = typeof CSS !== 'undefined' && 'highlights' in CSS && typeof (globalThis as { Highlight?: HL }).Highlight === 'function'
const registry = () => (CSS as unknown as { highlights: Map<string, unknown> }).highlights
const Highlight = () => (globalThis as unknown as { Highlight: HL }).Highlight

export const hasHighlightApi = api

export interface Widget { id: string; at: Range; text: string }

export function createPainter(host: Element) {
  const added: Element[] = []

  function clear(): void {
    for (const el of added.splice(0)) {
      if (el.hasAttribute('data-ann-mark')) {
        const parent = el.parentNode
        if (!parent) continue
        while (el.firstChild) parent.insertBefore(el.firstChild, el)
        parent.removeChild(el)
        parent.normalize()
      } else el.remove()
    }
    if (api) for (const g of GROUPS) if (g !== 'focus') registry().delete(`ax-${g}`)
  }

  function paint(groups: Partial<Record<Group, Range[]>>, widgets: Widget[]): void {
    clear()
    // widgets first, last in the document first, so an earlier insertion never shifts a later range's container
    const ws = [...widgets].sort((a, b) => b.at.compareBoundaryPoints(Range.END_TO_END, a.at))
    for (const w of ws) {
      const ins = document.createElement('ins')
      ins.setAttribute('data-ann-widget', '')
      ins.setAttribute('data-ann-id', w.id)
      ins.setAttribute('contenteditable', 'false')
      ins.className = 'ax-ins'
      ins.textContent = w.text
      const at = w.at.cloneRange()
      at.collapse(false)
      try { at.insertNode(ins); added.push(ins) } catch { /* a range in a node that went away */ }
    }
    if (api) {
      for (const g of GROUPS) {
        if (g === 'focus') continue
        const rs = groups[g] ?? []
        if (rs.length) registry().set(`ax-${g}`, new (Highlight())(...rs))
      }
      return
    }
    for (const g of GROUPS) for (const r of groups[g] ?? []) wrap(r, g)
  }

  /* the fallback: each text node a range crosses gets its slice wrapped */
  function wrap(r: Range, g: Group): void {
    const nodes: Text[] = []
    const walk = document.createTreeWalker(r.commonAncestorContainer, NodeFilter.SHOW_TEXT)
    for (let n = walk.currentNode.nodeType === Node.TEXT_NODE ? walk.currentNode : walk.nextNode(); n; n = walk.nextNode()) {
      if (r.intersectsNode(n) && (n as Text).data) nodes.push(n as Text)
    }
    for (const n of nodes) {
      let t = n
      const s = n === r.startContainer ? r.startOffset : 0
      const e = n === r.endContainer ? r.endOffset : n.data.length
      if (e <= s || !host.contains(t)) continue
      if (s > 0) t = t.splitText(s)
      if (e - s < t.data.length) t.splitText(e - s)
      const m = document.createElement('mark')
      m.setAttribute('data-ann-mark', '')
      m.className = `ax-mark ax-mark-${g}`
      t.parentNode!.insertBefore(m, t)
      m.appendChild(t)
      added.push(m)
    }
  }

  /* the pulse when a card is clicked: the range glows, dims, glows, then lets go (static with reduced motion) */
  let timers: number[] = []
  function flash(r: Range | null, reduce: boolean): void {
    for (const t of timers) clearTimeout(t)
    timers = []
    const set = (on: boolean) => {
      if (api) { if (on && r) registry().set('ax-focus', new (Highlight())(r)); else registry().delete('ax-focus') }
      else host.querySelectorAll('mark.ax-mark-active').forEach((m) => m.classList.toggle('ax-flash', on))
    }
    if (!r) { set(false); return }
    set(true)
    if (!reduce) { timers.push(window.setTimeout(() => set(false), 320), window.setTimeout(() => set(true), 520)) }
    timers.push(window.setTimeout(() => set(false), 1500))
  }

  function dispose(): void {
    for (const t of timers) clearTimeout(t)
    clear()
    if (api) registry().delete('ax-focus')
  }

  return { paint, clear, flash, dispose }
}
export type Painter = ReturnType<typeof createPainter>
