import { Marked } from 'marked'
import DOMPurify from 'dompurify'
import { fenceBareSql } from './code'

/* RICH COPY (owner 11-15: a member asked db for an email and had to copy it out by hand: the asterisks and pipes of
   markdown landed in Outlook as text). What leaves the chat carries BOTH forms: text/html for a mail client, a document
   or a sheet (tables keep their borders, bold stays bold), and the words as written for a plain editor. One helper for
   every copy in the chat: a whole message, a selection, a deliverable. A browser without ClipboardItem gets the text.
   The HTML is only ever handed to the clipboard, never drawn on this page. */

const md = new Marked({ gfm: true, breaks: true })
const CELL = 'border:1px solid #c8ccd4;padding:4px 8px;text-align:left;vertical-align:top'
/* the page's own sanitizer settings (Prose.tsx uses these): a copy is never more permissive than what was SEEN */
export const PURIFY = { FORBID_TAGS: ['style', 'form', 'input', 'iframe', 'img'], FORBID_ATTR: ['style'] }

/* markdown -> the HTML a paste should carry: the page's own preprocessing (bare SQL fenced) and sanitizer, then
   inline styles (mail clients drop stylesheets) */
export function clipHtml(markdown: string): string {
  return styled(DOMPurify.sanitize(clipMarkup(markdown), PURIFY))
}
/* the parse before sanitizing, the page's own (bare SQL fenced first): pure, so tests run it under node */
export const clipMarkup = (markdown: string): string => md.parse(fenceBareSql(markdown), { async: false }) as string

/* markdown -> the words a PLAIN editor should get, from marked's OWN parse (medic 12241: regexes over the raw text
   turned x**2 into x2 and my_db__stage__x into my_dbstagex). Code and code spans stay byte-exact; only what marked
   reads as emphasis loses its marks; a heading is its text; a link reads "text (url)"; a table's cells are tab-separated;
   a list item starts "- " */
export function clipPlain(markdown: string): string {
  return blocks(md.lexer(fenceBareSql(markdown))).replace(/\n{3,}/g, '\n\n').trim()
}
type Tok = { type: string; raw: string; text?: string; tokens?: Tok[]; items?: { tokens: Tok[] }[]; href?: string;
             header?: { tokens: Tok[] }[]; rows?: { tokens: Tok[] }[][]; ordered?: boolean; start?: number | '' }
function inline(ts: Tok[] | undefined): string {
  const list = ts ?? []
  return list.map((t, i) => {
    switch (t.type) {
      case 'codespan': return t.text ?? ''
      // emphasis INSIDE a word (2*3*4, a*b*c: CommonMark lets * do it) is arithmetic or a name, not emphasis: as typed
      case 'strong': case 'em': case 'del':
        return /\w$/.test(list[i - 1]?.raw ?? '') && /^\w/.test(list[i + 1]?.raw ?? '') ? t.raw : inline(t.tokens)
      case 'link': { const label = inline(t.tokens); return t.href && t.href !== label ? `${label} (${t.href})` : label }
      case 'br': return '\n'
      case 'escape': return t.text ?? ''
      case 'text': return t.tokens ? inline(t.tokens) : (t.text ?? '')
      default: return t.raw
    }
  }).join('')
}
function blocks(ts: Tok[]): string {
  return ts.map((t) => {
    switch (t.type) {
      case 'code': return (t.text ?? '') + '\n\n'
      case 'heading': case 'paragraph': return inline(t.tokens) + '\n\n'
      case 'blockquote': return blocks(t.tokens ?? []).split('\n').map((l) => (l ? `> ${l}` : l)).join('\n')
      case 'list': return (t.items ?? []).map((it, i) => `${t.ordered ? `${Number(t.start || 1) + i}.` : '-'} ${blocks(it.tokens).trim()}`).join('\n') + '\n\n'
      case 'table': return [t.header ?? [], ...(t.rows ?? [])].map((r) => r.map((c) => inline(c.tokens)).join('\t')).join('\n') + '\n\n'
      case 'text': return (t.tokens ? inline(t.tokens) : (t.text ?? '')) + '\n'
      case 'space': case 'hr': return '\n'
      default: return t.raw
    }
  }).join('')
}

/* tables and code, styled inline, the way a mail client keeps them */
export function styled(html: string): string {
  return html
    .replace(/<table>/g, '<table style="border-collapse:collapse;margin:6px 0">')
    .replace(/<(th|td)([^>]*)>/g, (_m, t, a) => `<${t}${a} style="${CELL}${t === 'th' ? ';font-weight:600;background:#f3f4f6' : ''}">`)
    .replace(/<pre>/g, '<pre style="background:#f6f7f9;padding:8px;border-radius:4px;white-space:pre-wrap">')
}

/* put both forms on the clipboard; true when it took */
export async function copyRich(plain: string, html: string): Promise<boolean> {
  try {
    if (typeof ClipboardItem !== 'undefined' && navigator.clipboard?.write) {
      // strings, not Blobs: the page never types a Blob as markup (test_active_content G4), and the clipboard takes both
      await navigator.clipboard.write([new ClipboardItem({ 'text/html': `<meta charset="utf-8">${html}`, 'text/plain': plain })])
      return true
    }
  } catch { /* fall through to text */ }
  try { await navigator.clipboard.writeText(plain); return true } catch { return false }
}

/* the selection inside `el`, as both forms: the page's own rendered nodes (already sanitized), code bars left out */
export function selectionClip(el: Element | null): { plain: string; html: string } | null {
  const s = getSelection()
  if (!el || !s || s.isCollapsed || !s.anchorNode || !el.contains(s.anchorNode)) return null
  const box = document.createElement('div')
  for (let i = 0; i < s.rangeCount; i++) box.append(s.getRangeAt(i).cloneContents())
  box.querySelectorAll('.ws-cb-bar, button').forEach((n) => n.remove())
  const html = styled(DOMPurify.sanitize(box.innerHTML, PURIFY))
  // the plain words from the SAME cleaned clone (a code bar's "sql · Copy" left out), a line break after each block
  box.querySelectorAll('p, div, li, tr, pre, h1, h2, h3, h4, h5, h6, br, blockquote').forEach((n) => n.after('\n'))
  box.querySelectorAll('td, th').forEach((n) => n.after('\t'))
  return { plain: (box.textContent ?? '').replace(/\t\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim(), html }
}
