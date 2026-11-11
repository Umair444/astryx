/* The call's eyes (iteration 17): what is on screen, read from the DOM, for the voice. This file only COLLECTS;
   pilot/egress.ts projectScreen() masks and cuts it before a byte leaves (read_screen's result and the context
   voice.ts pushes both go through it). Only what a person can see is read: elements in the viewport, not hidden,
   not inside the call's own layer ([data-call-layer]), headings and captions only, never a message body beyond the
   chat controller's own one-line headlines. */
import { chatCtl } from './chatctl'
import type { ScreenRaw } from './egress'

const OWN = '[data-call-layer]'

function visible(el: Element): boolean {
  if (el.closest(OWN)) return false
  const r = el.getBoundingClientRect()
  if (r.width < 2 || r.height < 2) return false
  if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return false
  const cs = getComputedStyle(el)
  return cs.visibility !== 'hidden' && cs.display !== 'none' && Number(cs.opacity) > 0.05
}
const text = (el: Element) => (el.textContent ?? '').replace(/\s+/g, ' ').trim()
function uniq(xs: string[], n: number): string[] {
  const out: string[] = []
  for (const x of xs) if (x && !out.includes(x)) { out.push(x); if (out.length >= n) break }
  return out
}

/** The open dialog's label, if one is up (a palette, a confirm, a sheet). */
function dialog(): string | null {
  for (const el of document.querySelectorAll('[role="dialog"],[role="alertdialog"]')) {
    if (!visible(el)) continue
    const l = el.getAttribute('aria-label') || text(el.querySelector('h1,h2,h3') ?? el).slice(0, 40)
    if (l) return l
  }
  return null
}

export function collectScreen(view: string): ScreenRaw {
  const chat = chatCtl()
  const headings = uniq([...document.querySelectorAll('h1,h2,h3,[role="heading"]')].filter(visible).map(text), 10)
  const captions = uniq([...document.querySelectorAll('caption,figcaption,[data-caption],svg > title,[aria-roledescription="chart"]')]
    .filter((el) => (el.tagName.toLowerCase() === 'title' ? visible(el.parentElement!) : visible(el)))
    .map((el) => el.getAttribute('data-caption') || el.getAttribute('aria-label') || text(el)), 8)
  return {
    surface: chat ? 'chat' : 'observatory',
    view: chat ? `chat ${chat.view()}` : view,
    title: chat?.title() ?? (document.querySelector('main h1') ? text(document.querySelector('main h1')!) : undefined),
    agent: chat?.agent() ?? undefined,
    headings, captions,
    lines: chat?.lines() ?? [],
    dialog: dialog(),
    draft: chat?.hasDraft() ?? false,
  }
}

/** The visible element best matching `words`: a button, link, heading, row or caption whose text or label holds them. */
export function findOnScreen(words: string): Element | null {
  const w = words.trim().toLowerCase()
  if (!w) return null
  const pool = [...document.querySelectorAll('button,a,[role="button"],[role="tab"],[role="listitem"],h1,h2,h3,h4,caption,figcaption,label,th,[data-caption],[aria-label]')]
    .filter(visible)
  let best: Element | null = null, score = 0
  for (const el of pool) {
    const t = `${el.getAttribute('aria-label') ?? ''} ${el.getAttribute('title') ?? ''} ${text(el)}`.toLowerCase()
    if (!t.includes(w)) continue
    // shorter text = a tighter hit; a heading or button beats a big container that merely contains the words
    const s = 1000 - Math.min(900, t.length) + (/^(h\d|button|a)$/i.test(el.tagName) ? 50 : 0)
    if (s > score) { best = el; score = s }
  }
  return best
}

/** Where a known thing is, for the figure to glide to. */
export function locateOnScreen(what: string, key?: string): Element | null {
  const q = (sel: string) => [...document.querySelectorAll(sel)].find(visible) ?? null
  const k = key ? CSS.escape(key) : ''
  switch (what) {
    case 'tab': return key ? q(`[data-tab="${k}"]`) ?? findOnScreen(key) : null
    case 'agent': return key ? q(`[data-agent="${k}"]`) ?? findOnScreen(key) : null
    case 'thread': return key ? q(`[data-thread="${k}"]`) : null
    case 'file': return key ? q(`[data-file-name="${k}"]`) ?? findOnScreen(key) : null
    case 'composer': return q('textarea[data-composer]') ?? q('textarea')
    case 'search': return q('[aria-label="search"]')
    case 'theme': return q('[aria-label="switch theme"]') ?? q('[data-theme-picker]')
    case 'scroll': return scrollerIn(chatCtl() ? '[data-chat-scroll]' : 'main')
  }
  return null
}

function scrollerIn(sel: string): HTMLElement | null {
  const root = document.querySelector<HTMLElement>(sel)
  if (!root) return null
  if (root.scrollHeight > root.clientHeight + 4 && /auto|scroll/.test(getComputedStyle(root).overflowY)) return root
  return null
}
