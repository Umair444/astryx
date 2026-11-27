import { useLayoutEffect, useMemo, useRef } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

/* A markdown artifact as a page to read: Newsreader 17/1.65 at a book measure. Sanitized like the chat's prose (no
   style, form, frame); images are dropped too, since a remote <img> would fetch from wherever an agent's file pointed. */
export function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(marked.parse(text, { async: false, gfm: true, breaks: false }) as string, {
    FORBID_TAGS: ['style', 'form', 'input', 'iframe', 'img', 'video', 'audio', 'object', 'embed'], FORBID_ATTR: ['style'],
  })
}

export default function Markdown({ text }: { text: string }) {
  const html = useMemo(() => renderMarkdown(text), [text])
  return (
    <div className="h-full overflow-y-auto">
      <article className="ws-doc mx-auto max-w-[720px] px-8 md:px-12 pt-10 pb-24" data-ann-root dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  )
}

/* plain text (a .txt, a .log): the same page, the text as a text node. Set through the ref rather than as a React
   child, so the annotation layer may split it around a suggestion without React losing track of its node. */
export function Plain({ text }: { text: string }) {
  const el = useRef<HTMLElement>(null)
  useLayoutEffect(() => { if (el.current) el.current.textContent = text }, [text])
  return (
    <div className="h-full overflow-y-auto">
      <article ref={el} className="ws-doc mx-auto max-w-[720px] px-8 md:px-12 pt-10 pb-24 whitespace-pre-wrap" data-ann-root />
    </div>
  )
}
