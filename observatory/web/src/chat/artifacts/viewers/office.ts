import JSZip from 'jszip'

/* Office files are zips of XML. Two readers over JSZip and a small XML reader of our own (below), loaded only when a
   sheet opens or a docx/xlsx is diffed: an .xlsx's sheets as rows of cell VALUES, and a .docx's text as paragraphs
   (what a word-level diff compares). Nothing here makes a DOM node: the file's XML becomes plain objects holding
   strings, so no markup from it is ever parsed into the page (the active-content gate, C3, refuses a browser XML/HTML parser). */

export interface Sheet { name: string; rows: string[][] }

/* ── a minimal XML reader: elements (by LOCAL name, prefix dropped), attributes (by qualified name), text, CDATA.
   Comments, processing instructions and doctypes are skipped; entities are decoded. Enough for OOXML parts, which
   are machine-written and well-formed; a malformed part yields what it can, never throws. */
interface X { name: string; attrs: Record<string, string>; kids: (X | string)[] }
const TOKEN = /<!\[CDATA\[([\s\S]*?)\]\]>|<!--[\s\S]*?-->|<\?[\s\S]*?\?>|<![^>]*>|<(\/?)([\w.:-]+)((?:\s+[\w.:-]+\s*=\s*(?:"[^"]*"|'[^']*'))*)\s*(\/?)>/g
const ATTR = /([\w.:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g
const ENT: Record<string, string> = { lt: '<', gt: '>', amp: '&', quot: '"', apos: "'" }
const decode = (s: string) => s.replace(/&(#x[0-9a-f]+|#\d+|\w+);/gi, (m, e: string) =>
  e[0] === '#' ? safeChar(e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10)) : ENT[e] ?? m)
const safeChar = (n: number) => (n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : '')
const local = (q: string) => q.slice(q.lastIndexOf(':') + 1)

function xml(src: string): X {
  const root: X = { name: '#root', attrs: {}, kids: [] }
  const stack: X[] = [root]
  let at = 0
  for (const m of src.matchAll(TOKEN)) {
    const top = stack[stack.length - 1]
    if (m.index! > at) top.kids.push(decode(src.slice(at, m.index)))
    at = m.index! + m[0].length
    if (m[1] !== undefined) { top.kids.push(m[1]); continue }              // CDATA: literal text
    if (!m[3]) continue                                                      // comment, PI, doctype
    if (m[2] === '/') {                                                      // a close: pop to its match
      const n = local(m[3])
      for (let i = stack.length - 1; i > 0; i--) if (stack[i].name === n) { stack.length = i; break }
      continue
    }
    const attrs: Record<string, string> = {}
    for (const a of (m[4] ?? '').matchAll(ATTR)) attrs[a[1]] = decode(a[2] ?? a[3] ?? '')
    const el: X = { name: local(m[3]), attrs, kids: [] }
    top.kids.push(el)
    if (!m[5]) stack.push(el)
  }
  return root
}
/* every descendant element named `tag`, in document order */
function kids(el: X, tag: string, out: X[] = []): X[] {
  for (const k of el.kids) if (typeof k !== 'string') { if (k.name === tag) out.push(k); kids(k, tag, out) }
  return out
}
const textOf = (el: X): string => el.kids.map((k) => (typeof k === 'string' ? k : textOf(k))).join('')
const attr = (el: X, q: string) => el.attrs[q] ?? null
/* a namespaced attribute whatever its prefix (r:id, or the same namespace under another prefix) */
const attrNs = (el: X, name: string) => { for (const k in el.attrs) if (k.includes(':') && local(k) === name) return el.attrs[k]; return null }

function colIndex(ref: string): number {
  const letters = /^[A-Z]+/.exec(ref)?.[0] ?? 'A'
  let n = 0
  for (const ch of letters) n = n * 26 + (ch.charCodeAt(0) - 64)
  return n - 1
}

export async function readXlsx(blob: Blob, maxRows = 20000): Promise<Sheet[]> {
  const zip = await JSZip.loadAsync(blob)
  const read = async (p: string) => (await zip.file(p)?.async('string')) ?? ''
  const shared = kids(xml(await read('xl/sharedStrings.xml')), 'si').map((si) => kids(si, 't').map(textOf).join(''))
  const rels = new Map(kids(xml(await read('xl/_rels/workbook.xml.rels')), 'Relationship').map((r) => [attr(r, 'Id'), attr(r, 'Target') ?? '']))
  const out: Sheet[] = []
  for (const s of kids(xml(await read('xl/workbook.xml')), 'sheet')) {
    const rid = attr(s, 'r:id') ?? attrNs(s, 'id')
    let target = rels.get(rid) ?? ''
    target = target.startsWith('/') ? target.slice(1) : `xl/${target.replace(/^\.\//, '')}`
    const doc = xml(await read(target))
    const rows: string[][] = []
    for (const r of kids(doc, 'row').slice(0, maxRows)) {
      const at = Math.max(0, parseInt(attr(r, 'r') ?? '0', 10) - 1)
      while (rows.length < at) rows.push([])
      const row: string[] = []
      for (const c of kids(r, 'c')) {
        const i = colIndex(attr(c, 'r') ?? '')
        const t = attr(c, 't')
        const v = (kids(c, 'v')[0] && textOf(kids(c, 'v')[0])) ?? ''
        const val = t === 's' ? shared[+v] ?? '' : t === 'inlineStr' ? kids(c, 't').map(textOf).join('') : t === 'b' ? (v === '1' ? 'TRUE' : 'FALSE') : tidy(v)
        while (row.length < i) row.push('')
        row[i] = val
      }
      rows.push(row)
    }
    out.push({ name: attr(s, 'name') ?? `Sheet ${out.length + 1}`, rows })
  }
  return out
}
/* a float as Excel stores it (0.30000000000000004) reads as the number it is */
const tidy = (v: string) => (/^-?\d+\.\d{10,}$/.test(v) ? String(+parseFloat(v).toPrecision(12)) : v)

export async function docxText(blob: Blob): Promise<string> {
  const zip = await JSZip.loadAsync(blob)
  const doc = xml((await zip.file('word/document.xml')?.async('string')) ?? '')
  const run = (el: X): string => el.kids.map((k) => (typeof k === 'string' ? '' : k.name === 't' ? textOf(k) : k.name === 'tab' ? '\t' : k.name === 'br' ? '\n' : run(k))).join('')
  return kids(doc, 'p').map(run).join('\n')
}

export async function xlsxText(blob: Blob): Promise<string> {
  return (await readXlsx(blob)).map((s) => `# ${s.name}\n${s.rows.map((r) => r.join('\t')).join('\n')}`).join('\n\n')
}
