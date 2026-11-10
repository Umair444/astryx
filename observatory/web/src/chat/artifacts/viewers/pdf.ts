/// <reference types="vite/client" />
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

/* pdf.js, loaded only when a PDF opens (this module is a dynamic import). The document is parsed in pdf.js's own
   worker from BYTES this page already fetched with the owner header; there is no scripting layer (that is the viewer
   app's, which is not used), no eval, no XFA, and no annotation layer, so a PDF's links and forms never act here. */
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

export type PdfDoc = pdfjs.PDFDocumentProxy
export const TextLayer = pdfjs.TextLayer

export async function openPdf(blob: Blob): Promise<PdfDoc> {
  const data = new Uint8Array(await blob.arrayBuffer())
  return pdfjs.getDocument({ data, enableXfa: false, isOffscreenCanvasSupported: true }).promise
}

/* the text a word-level diff compares: each page's text items, line breaks where pdf.js marks them, pages apart */
export async function pdfText(blob: Blob): Promise<string> {
  const doc = await openPdf(blob)
  const pages: string[] = []
  try {
    for (let i = 1; i <= doc.numPages; i++) {
      const tc = await (await doc.getPage(i)).getTextContent()
      let s = ''
      for (const it of tc.items) if ('str' in it) s += it.str + (it.hasEOL ? '\n' : '')
      pages.push(s.replace(/[ \t]+\n/g, '\n').trim())
    }
  } finally { void doc.loadingTask.destroy() }
  return pages.join('\n\n')
}
