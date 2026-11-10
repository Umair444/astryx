import { useMemo, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Msg } from '../../types'
import TableActions from './TableActions'

/* An agent's answer as a page: full GFM (tables, lists, code, quotes), the way canvas renders it (canvas/web/src/ui.tsx
   Markdown). components/Md is a deliberately small renderer with no tables, and agents answer BI questions in tables.
   Agent text renders in the origin that holds the owner's key: sanitized, always; no style, form, input or frame. */

marked.setOptions({ gfm: true, breaks: true })

/* `msg` (an agent's turn): its tables get Chart / CSV / Excel on hover (TableActions, iteration 9) */
export default function Prose({ text, msg }: { text: string; msg?: Msg }) {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(text, { async: false }) as string, {
    FORBID_TAGS: ['style', 'form', 'input', 'iframe', 'img'], FORBID_ATTR: ['style'],
  }), [text])
  const [el, setEl] = useState<HTMLDivElement | null>(null)
  const prose = <div ref={setEl} className="ws-prose" dangerouslySetInnerHTML={{ __html: html }} />
  if (!msg || !html.includes('<table')) return prose
  return <div className="relative ws-has-tables">{prose}<TableActions host={el} text={text} m={msg} /></div>
}
