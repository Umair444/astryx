import { useEffect, useMemo, useState } from 'react'
import DOMPurify from 'dompurify'

/* Code, SQL, JSON: mono 12.5/1.65 with a line gutter, highlighted once the highlighter chunk arrives (escaped plain
   text until then, never blank). JSON that parses is pretty-printed for reading; the stored bytes are untouched. The
   highlighter's output is escaped text in <span class="hljs-*">, and it still goes through DOMPurify like every other
   markup this origin renders (the active-content gate, C4). The content <pre> is the annotation layer's text root. */
export default function Code({ text, ext }: { text: string; ext: string }) {
  const shown = useMemo(() => {
    if (ext !== 'json' || text.length > 2_000_000) return text
    try { return JSON.stringify(JSON.parse(text), null, 2) } catch { return text }
  }, [text, ext])
  const [lit, setLit] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    setLit(null)
    import('./hl').then(({ highlight }) => live && setLit(highlight(shown, ext)))
    return () => { live = false }
  }, [shown, ext])
  const html = useMemo(() => DOMPurify.sanitize(lit ?? escape(shown), { ALLOWED_TAGS: ['span'], ALLOWED_ATTR: ['class'] }), [lit, shown])
  const lines = useMemo(() => shown.split('\n').length, [shown])
  return (
    <div className="h-full overflow-auto ws-code">
      <div className="flex min-w-max py-5 pb-20">
        <pre className="ws-code-gutter select-none text-right pl-5 pr-4 sticky left-0" aria-hidden>
          {Array.from({ length: lines }, (_, i) => i + 1).join('\n')}
        </pre>
        <pre className="pr-8" data-ann-root dangerouslySetInnerHTML={{ __html: html }} />
      </div>
    </div>
  )
}
const escape = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
