import JSZip from 'jszip'

/* Office files are zips of XML. Two readers over JSZip + DOMParser, loaded only when a sheet opens or a docx/xlsx is
   diffed: an .xlsx's sheets as rows of cell VALUES, and a .docx's text as paragraphs (what a word-level diff compares).
   Nothing here renders markup from the file; it only reads text nodes. */

export interface Sheet { name: string; rows: string[][] }
const xml = (s: string) => new DOMParser().parseFromString(s, 'application/xml')
const kids = (el: Element | Document, tag: string) => Array.from(el.getElementsByTagNameNS('*', tag))

function colIndex(ref: string): number {
  const letters = /^[A-Z]+/.exec(ref)?.[0] ?? 'A'
  let n = 0
  for (const ch of letters) n = n * 26 + (ch.charCodeAt(0) - 64)
  return n - 1
}

export async function readXlsx(blob: Blob, maxRows = 20000): Promise<Sheet[]> {
  const zip = await JSZip.loadAsync(blob)
  const read = async (p: string) => (await zip.file(p)?.async('string')) ?? ''
  const shared = kids(xml(await read('xl/sharedStrings.xml')), 'si').map((si) => kids(si, 't').map((t) => t.textContent ?? '').join(''))
  const rels = new Map(kids(xml(await read('xl/_rels/workbook.xml.rels')), 'Relationship').map((r) => [r.getAttribute('Id'), r.getAttribute('Target') ?? '']))
  const out: Sheet[] = []
  for (const s of kids(xml(await read('xl/workbook.xml')), 'sheet')) {
    const rid = s.getAttribute('r:id') ?? s.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'id')
    let target = rels.get(rid) ?? ''
    target = target.startsWith('/') ? target.slice(1) : `xl/${target.replace(/^\.\//, '')}`
    const doc = xml(await read(target))
    const rows: string[][] = []
    for (const r of kids(doc, 'row').slice(0, maxRows)) {
      const at = Math.max(0, parseInt(r.getAttribute('r') ?? '0', 10) - 1)
      while (rows.length < at) rows.push([])
      const row: string[] = []
      for (const c of kids(r, 'c')) {
        const i = colIndex(c.getAttribute('r') ?? '')
        const t = c.getAttribute('t')
        const v = kids(c, 'v')[0]?.textContent ?? ''
        const val = t === 's' ? shared[+v] ?? '' : t === 'inlineStr' ? kids(c, 't').map((x) => x.textContent ?? '').join('') : t === 'b' ? (v === '1' ? 'TRUE' : 'FALSE') : tidy(v)
        while (row.length < i) row.push('')
        row[i] = val
      }
      rows.push(row)
    }
    out.push({ name: s.getAttribute('name') ?? `Sheet ${out.length + 1}`, rows })
  }
  return out
}
/* a float as Excel stores it (0.30000000000000004) reads as the number it is */
const tidy = (v: string) => (/^-?\d+\.\d{10,}$/.test(v) ? String(+parseFloat(v).toPrecision(12)) : v)

export async function docxText(blob: Blob): Promise<string> {
  const zip = await JSZip.loadAsync(blob)
  const doc = xml((await zip.file('word/document.xml')?.async('string')) ?? '')
  return kids(doc, 'p').map((p) => {
    let s = ''
    for (const n of Array.from(p.getElementsByTagNameNS('*', '*'))) {
      if (n.localName === 't') s += n.textContent ?? ''
      else if (n.localName === 'tab') s += '\t'
      else if (n.localName === 'br') s += '\n'
    }
    return s
  }).join('\n')
}

export async function xlsxText(blob: Blob): Promise<string> {
  return (await readXlsx(blob)).map((s) => `# ${s.name}\n${s.rows.map((r) => r.join('\t')).join('\n')}`).join('\n\n')
}
