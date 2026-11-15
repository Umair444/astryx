import { Marked } from 'marked'
import DOMPurify from 'dompurify'

/* RICH COPY (owner 11-15: a member asked db for an email and had to copy it out by hand: the asterisks and pipes of
   markdown landed in Outlook as text). What leaves the chat carries BOTH forms: text/html for a mail client, a document
   or a sheet (tables keep their borders, bold stays bold), and the words as written for a plain editor. One helper for
   every copy in the chat: a whole message, a selection, a deliverable. A browser without ClipboardItem gets the text.
   The HTML is only ever handed to the clipboard, never drawn on this page. */

const md = new Marked({ gfm: true, breaks: true })
const CELL = 'border:1px solid #c8ccd4;padding:4px 8px;text-align:left;vertical-align:top'

/* markdown -> the HTML a paste should carry: sanitized, inline-styled (mail clients drop stylesheets) */
export function clipHtml(markdown: string): string {
  const html = DOMPurify.sanitize(md.parse(markdown, { async: false }) as string, { FORBID_TAGS: ['style', 'form', 'input', 'iframe', 'img', 'script'] })
  return styled(html)
}

/* markdown -> the words a PLAIN editor should get: the emphasis and heading marks gone, links as "text (url)", a
   fence's backticks gone (its code kept), tables and lists as written */
export function clipPlain(markdown: string): string {
  return markdown
    .replace(/^```[\w+-]*\s*$/gm, '')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/(\*\*|__)(.+?)\1/g, '$2')
    .replace(/(^|[^\w*])\*(?!\s)([^*\n]+?)\*(?!\w)/g, '$1$2')
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '$1 ($2)')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
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
  return { plain: s.toString().trim(), html: styled(DOMPurify.sanitize(box.innerHTML)) }
}
