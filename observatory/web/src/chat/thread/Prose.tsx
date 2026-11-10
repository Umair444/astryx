import { useMemo } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

/* An agent's answer as a page: full GFM (tables, lists, code, quotes), the way canvas renders it (canvas/web/src/ui.tsx
   Markdown). components/Md is a deliberately small renderer with no tables, and agents answer BI questions in tables.
   Agent text renders in the origin that holds the owner's key: sanitized, always; no style, form, input or frame. */

marked.setOptions({ gfm: true, breaks: true })

export default function Prose({ text }: { text: string }) {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(text, { async: false }) as string, {
    FORBID_TAGS: ['style', 'form', 'input', 'iframe', 'img'], FORBID_ATTR: ['style'],
  }), [text])
  return <div className="ws-prose" dangerouslySetInnerHTML={{ __html: html }} />
}
