import { useEffect, useMemo, useState } from 'react'

/* Code, SQL, JSON: mono 12.5/1.65 with a line gutter, highlighted once the highlighter chunk arrives (plain until
   then, never blank). JSON that parses is pretty-printed for reading; the stored bytes are untouched. */
export default function Code({ text, ext }: { text: string; ext: string }) {
  const shown = useMemo(() => {
    if (ext !== 'json' || text.length > 2_000_000) return text
    try { return JSON.stringify(JSON.parse(text), null, 2) } catch { return text }
  }, [text, ext])
  const [html, setHtml] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    setHtml(null)
    import('./hl').then(({ highlight }) => live && setHtml(highlight(shown, ext)))
    return () => { live = false }
  }, [shown, ext])
  const lines = useMemo(() => shown.split('\n').length, [shown])
  return (
    <div className="h-full overflow-auto ws-code">
      <div className="flex min-w-max py-5 pb-20">
        <pre className="ws-code-gutter select-none text-right pl-5 pr-4 sticky left-0" aria-hidden>
          {Array.from({ length: lines }, (_, i) => i + 1).join('\n')}
        </pre>
        {html != null
          ? <pre className="pr-8" dangerouslySetInnerHTML={{ __html: html }} />
          : <pre className="pr-8">{shown}</pre>}
      </div>
    </div>
  )
}
