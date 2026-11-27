import { lazy, Suspense, useEffect, useState } from 'react'
import { obsKey } from '../../../api'
import type { Opened } from '../api'
import { Failed, Loading } from './common'

const PdfView = lazy(() => import('./Pdf'))

/* An Office document (pptx, ppt, doc, xls, odt, odp, ods, rtf; and docx/xlsx "as authored") read as the PDF it is:
   the server converts it once with LibreOffice (/api/chat/preview, the converter canvas uses: core/office.py) and
   serve_untrusted hands the PDF back; pdf.js draws it to canvases. Nothing from the document is parsed into the page
   (the active-content gate's rule, as the docx/xlsx readers keep it). The header carries the key, never a ?key=. */
export default function OfficeView({ art }: { art: Opened }) {
  const [blob, setBlob] = useState<Blob | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let live = true
    setBlob(null); setErr('')
    fetch(`/api/chat/preview?path=${encodeURIComponent(art.source)}`, { headers: { 'x-obs-key': obsKey() } })
      .then(async (r) => {
        if (!r.ok) {
          const why = await r.json().then((j: { error?: string }) => j.error).catch(() => '')
          throw new Error(why || (r.status === 404 ? 'that file is not readable from here' : `the document did not render (${r.status})`))
        }
        return r.blob()
      })
      .then((b) => live && setBlob(b)).catch((e) => live && setErr(String((e as Error).message ?? e)))
    return () => { live = false }
  }, [art.source, art.head])
  if (err) return <Failed err={err} />
  if (!blob) return <Loading what="Rendering the document as authored" />
  return <Suspense fallback={<Loading />}><PdfView blob={blob} /></Suspense>
}
