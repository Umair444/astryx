import { useEffect, useRef, useState } from 'react'
import { Failed, Loading } from './common'

/* A Word document rendered as pages (docx-preview, loaded with this module): paper on the panel's backdrop, its own
   fonts and widths kept (scaled down to fit when a page is wider than the panel). Alt-chunks (embedded HTML) are never rendered; the document's styles are scoped to its
   wrapper class and live inside this viewer, so they leave with it. */
export default function DocxView({ blob }: { blob: Blob }) {
  const host = useRef<HTMLDivElement>(null)
  const styles = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<'loading' | 'ok' | string>('loading')
  const bed = useRef<HTMLDivElement>(null)
  // a page wider than the panel is scaled down to fit (CSS zoom keeps the text layout and selection exact)
  useEffect(() => {
    const el = bed.current
    if (!el || state !== 'ok') return
    const fit = () => {
      const page = host.current?.querySelector<HTMLElement>('section.axdocx')
      if (!page || !host.current) return
      host.current.style.zoom = String(Math.min(1, (el.clientWidth - 40) / page.offsetWidth))
    }
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(el)
    return () => ro.disconnect()
  }, [state])
  useEffect(() => {
    let live = true
    setState('loading')
    import('docx-preview').then(({ renderAsync }) => {
      if (!live || !host.current || !styles.current) return
      host.current.replaceChildren(); styles.current.replaceChildren()
      return renderAsync(blob, host.current, styles.current, {
        className: 'axdocx', inWrapper: true, breakPages: true, ignoreLastRenderedPageBreak: true, renderAltChunks: false,
        renderHeaders: true, renderFooters: true, renderFootnotes: true, renderComments: false, useBase64URL: false,
      }).then(() => live && setState('ok'))
    }).catch((e) => live && setState(`This document could not be rendered (${(e as Error).message}).`))
    return () => { live = false }
  }, [blob])
  return (
    <div ref={bed} className="relative h-full overflow-auto ws-paperbed">
      <div ref={styles} hidden />
      <div ref={host} className="ws-docx" data-ann-root />
      {state === 'loading' && <div className="absolute inset-0"><Loading what="Rendering the document" /></div>}
      {state !== 'loading' && state !== 'ok' && <div className="absolute inset-0"><Failed err={state} /></div>}
    </div>
  )
}
