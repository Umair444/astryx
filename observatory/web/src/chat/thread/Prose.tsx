import { useMemo, useState, type MouseEvent } from 'react'
import { Marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Msg } from '../../types'
import TableActions from './TableActions'
import { splitProvenance } from './provenance'
import { codeBlock, fenceBareSql } from './code'

/* An agent's answer as a page: full GFM (tables, lists, code, quotes), the way canvas renders it (canvas/web/src/ui.tsx
   Markdown). components/Md is a deliberately small renderer with no tables, and agents answer BI questions in tables.
   Agent text renders in the origin that holds the owner's key: sanitized, always; no style, form, input or frame. */

/* this answer's own parser (not the shared `marked`): a fenced block draws as code with its language and a Copy
   button (./code.ts), and SQL pasted without a fence is fenced first */
const md = new Marked({ gfm: true, breaks: true }, { renderer: { code: ({ text, lang }) => codeBlock(text, lang) } })

/* `msg` (an agent's turn): its tables get Chart / CSV / Excel on hover (TableActions, iteration 9) */
const PURIFY = { FORBID_TAGS: ['style', 'form', 'input', 'iframe', 'img'], FORBID_ATTR: ['style'] }

/* an answer's trailing provenance line ("Source: o.product_pl…", thread/provenance.ts) is drawn as a quiet footer
   under a hairline, not body text (iteration 12) */
export default function Prose({ text, msg }: { text: string; msg?: Msg }) {
  const { body, source } = useMemo(() => splitProvenance(text), [text])
  const html = useMemo(() => DOMPurify.sanitize(md.parse(fenceBareSql(body), { async: false }) as string, PURIFY), [body])
  const foot = useMemo(() => (source ? DOMPurify.sanitize(md.parseInline(source, { async: false }) as string, PURIFY) : ''), [source])
  const [el, setEl] = useState<HTMLDivElement | null>(null)
  const prose = <div ref={setEl} className="ws-prose" onClick={copyCode} dangerouslySetInnerHTML={{ __html: html }} />
  const footer = foot && (
    <div className="ws-source" role="note" aria-label="Where this came from">
      <svg viewBox="0 0 16 16" className="ws-source-glyph" aria-hidden><ellipse cx="8" cy="4" rx="5" ry="2" fill="none" stroke="currentColor" strokeWidth="1.3" /><path d="M3 4v8c0 1.1 2.2 2 5 2s5-.9 5-2V4M3 8c0 1.1 2.2 2 5 2s5-.9 5-2" fill="none" stroke="currentColor" strokeWidth="1.3" /></svg>
      <span dangerouslySetInnerHTML={{ __html: foot }} />
    </div>
  )
  if (!msg || !html.includes('<table')) return footer ? <>{prose}{footer}</> : prose
  return <div className="relative ws-has-tables">{prose}<TableActions host={el} text={body} m={msg} />{footer}</div>
}

/* a code block's Copy (delegated: the sanitized HTML carries no handler). The code's own text, never the bar's; a
   browser with no clipboard API (an http page, an old WebView) copies through a hidden textarea */
function copyCode(e: MouseEvent<HTMLDivElement>) {
  const btn = (e.target as HTMLElement).closest<HTMLButtonElement>('button[data-copy]')
  const code = btn?.closest('.ws-code')?.querySelector('pre')?.textContent
  if (!btn || code == null) return
  const done = (ok: boolean) => { btn.textContent = ok ? 'Copied' : 'Copy failed'; setTimeout(() => { btn.textContent = 'Copy' }, 1500) }
  const fallback = () => {
    const t = document.createElement('textarea')
    t.value = code; t.setAttribute('readonly', ''); t.style.position = 'fixed'; t.style.opacity = '0'
    document.body.appendChild(t); t.select()
    let ok = false
    try { ok = document.execCommand('copy') } catch { ok = false }
    t.remove(); done(ok)
  }
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(code).then(() => done(true), fallback)
  else fallback()
}
