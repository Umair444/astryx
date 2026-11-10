import { useMemo, useState } from 'react'

/* CSV/TSV (and a spreadsheet's sheet, from Sheet.tsx) as a table: sticky header, a row-number column, numbers right-
   aligned in tabular figures, and a click on a header sorts by it (numeric when the column is numeric). Rendering
   stops at a cap; the rest is counted, never silently dropped. */
const CAP = 2000

/* RFC 4180: quoted fields, doubled quotes, newlines inside quotes; the delimiter by extension */
export function parseDelimited(text: string, delim: string): string[][] {
  const rows: string[][] = []
  let row: string[] = [], f = '', q = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++ } else q = false } else f += c
    } else if (c === '"' && f === '') q = true
    else if (c === delim) { row.push(f); f = '' }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++
      row.push(f); rows.push(row); row = []; f = ''
    } else f += c
  }
  if (f !== '' || row.length) { row.push(f); rows.push(row) }
  return rows
}

const NUM = /^-?[\d,]*\.?\d+(e[+-]?\d+)?%?$/i
const num = (s: string) => parseFloat(s.replace(/[,%]/g, ''))

export function Grid({ rows }: { rows: string[][] }) {
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null)
  const head = rows[0] ?? []
  const width = Math.max(head.length, ...rows.slice(0, 200).map((r) => r.length))
  const body = useMemo(() => rows.slice(1).filter((r) => r.some((c) => c !== '')), [rows])
  const numeric = useMemo(() => Array.from({ length: width }, (_, c) => {
    const vals = body.slice(0, 300).map((r) => (r[c] ?? '').trim()).filter(Boolean)
    return vals.length > 0 && vals.every((v) => NUM.test(v))
  }), [body, width])
  const sorted = useMemo(() => {
    if (!sort) return body
    const { col, dir } = sort
    return [...body].sort((a, b) => {
      const x = (a[col] ?? '').trim(), y = (b[col] ?? '').trim()
      if (numeric[col]) return ((x ? num(x) : -Infinity) - (y ? num(y) : -Infinity)) * dir
      return x.localeCompare(y, undefined, { numeric: true }) * dir
    })
  }, [body, sort, numeric])
  const shown = sorted.slice(0, CAP)
  const click = (c: number) => setSort((s) => (s?.col === c ? (s.dir === 1 ? { col: c, dir: -1 } : null) : { col: c, dir: 1 }))

  return (
    <div className="h-full overflow-auto ws-grid">
      <table data-ann-root>
        <thead>
          <tr>
            <th className="ws-grid-n" aria-label="row" data-ann-skip />
            {Array.from({ length: width }, (_, c) => (
              <th key={c} className={numeric[c] ? 'text-right' : ''} aria-sort={sort?.col === c ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
                <button onClick={() => click(c)} className={`inline-flex items-center gap-1 ${numeric[c] ? 'flex-row-reverse' : ''}`} title="Sort">
                  <span>{head[c] || `Column ${c + 1}`}</span>
                  <span className={`text-[10px] ${sort?.col === c ? 'text-ink' : 'opacity-0'}`} aria-hidden>{sort?.col === c && sort.dir === -1 ? '▼' : '▲'}</span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i}>
              <td className="ws-grid-n" data-ann-skip>{i + 1}</td>
              {Array.from({ length: width }, (_, c) => <td key={c} className={numeric[c] ? 'text-right' : ''}>{r[c] ?? ''}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-4 py-3 pb-16 text-[12px] text-ink-mute">
        {body.length.toLocaleString()} {body.length === 1 ? 'row' : 'rows'} · {width} columns{sorted.length > CAP ? ` · showing the first ${CAP.toLocaleString()}` : ''}
      </div>
    </div>
  )
}

export default function Table({ text, ext }: { text: string; ext: string }) {
  const rows = useMemo(() => parseDelimited(text, ext === 'tsv' ? '\t' : ','), [text, ext])
  return <Grid rows={rows} />
}
