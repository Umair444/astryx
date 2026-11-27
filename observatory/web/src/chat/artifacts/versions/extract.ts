import { contentOf, type Opened } from '../api'

/* The text a version is compared by. Text kinds are their bytes; a PDF is pdf.js's text content, a .docx its
   paragraphs, an .xlsx its cell values (each through its own lazily loaded reader). Images compare by eye, not text:
   null. Cached per revision like the bytes are. */
const cache = new Map<string, Promise<string | null>>()

export function comparable(a: Opened): boolean {
  return ['text', 'code', 'table', 'pdf', 'docx', 'sheet'].includes(a.kind)
}

export function textForDiff(a: Opened, rev: string): Promise<string | null> {
  const key = `${a.id}@${rev}`
  let p = cache.get(key)
  if (!p) {
    p = (async () => {
      const blob = await contentOf(a, rev)
      switch (a.kind) {
        case 'text': case 'code': case 'table': return blob.text()
        case 'pdf': return (await import('../viewers/pdf')).pdfText(blob)
        case 'docx': return (await import('../viewers/office')).docxText(blob)
        case 'sheet': return (await import('../viewers/office')).xlsxText(blob)
        default: return null
      }
    })()
    p.catch(() => cache.delete(key))
    cache.set(key, p)
  }
  return p
}
