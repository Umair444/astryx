import { useMemo, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Msg } from '../../types'
import TableActions from './TableActions'
import { splitProvenance } from './provenance'

/* An agent's answer as a page: full GFM (tables, lists, code, quotes), the way canvas renders it (canvas/web/src/ui.tsx
   Markdown). components/Md is a deliberately small renderer with no tables, and agents answer BI questions in tables.
   Agent text renders in the origin that holds the owner's key: sanitized, always; no style, form, input or frame. */

marked.setOptions({ gfm: true, breaks: true })

/* `msg` (an agent's turn): its tables get Chart / CSV / Excel on hover (TableActions, iteration 9) */
const PURIFY = { FORBID_TAGS: ['style', 'form', 'input', 'iframe', 'img'], FORBID_ATTR: ['style'] }

/* an answer's trailing provenance line ("Source: o.product_pl…", thread/provenance.ts) is drawn as a quiet footer
   under a hairline, not body text (iteration 12) */
export default function Prose({ text, msg }: { text: string; msg?: Msg }) {
  const { body, source } = useMemo(() => splitProvenance(text), [text])
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(body, { async: false }) as string, PURIFY), [body])
  const foot = useMemo(() => (source ? DOMPurify.sanitize(marked.parseInline(source, { async: false }) as string, PURIFY) : ''), [source])
  const [el, setEl] = useState<HTMLDivElement | null>(null)
  const prose = <div ref={setEl} className="ws-prose" dangerouslySetInnerHTML={{ __html: html }} />
  const footer = foot && (
    <div className="ws-source" role="note" aria-label="Where this came from">
      <svg viewBox="0 0 16 16" className="ws-source-glyph" aria-hidden><ellipse cx="8" cy="4" rx="5" ry="2" fill="none" stroke="currentColor" strokeWidth="1.3" /><path d="M3 4v8c0 1.1 2.2 2 5 2s5-.9 5-2V4M3 8c0 1.1 2.2 2 5 2s5-.9 5-2" fill="none" stroke="currentColor" strokeWidth="1.3" /></svg>
      <span dangerouslySetInnerHTML={{ __html: foot }} />
    </div>
  )
  if (!msg || !html.includes('<table')) return footer ? <>{prose}{footer}</> : prose
  return <div className="relative ws-has-tables">{prose}<TableActions host={el} text={body} m={msg} />{footer}</div>
}
