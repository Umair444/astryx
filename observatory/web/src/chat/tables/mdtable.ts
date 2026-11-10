import { marked, type Token, type Tokens } from 'marked'
import { scaleOf } from './infer'

/* The tables in an agent's markdown answer, as rows of plain cell text, in DOCUMENT ORDER (the same order marked
   renders their <table>s in, so the nth table here is the nth <table> in the turn). A cell's inline markdown is
   reduced to its text (**12.4M** → 12.4M, [x](url) → x, `code` → code). Tables nested in a list or a quote count too. */

export interface MdTable { rows: string[][]; before: string }      // before: what names it (a lead-in line, else the heading above)

export function tablesOf(text: string): MdTable[] {
  if (!/^\s*\|?.*\|.*\n\s*\|?\s*:?-+/m.test(text)) return []          // cheap: no delimiter row, no table
  const out: MdTable[] = []
  let last = '', heading = ''
  const walk = (toks: Token[]) => {
    for (const t of toks) {
      if (t.type === 'table') {
        const tb = t as Tokens.Table
        // a short lead-in ("Top 5 in Aug (PKR mn):") names the table best; else the heading it sits under
        out.push({ rows: [tb.header.map(cell), ...tb.rows.map((r) => r.map(cell))], before: /[:：]\s*$/.test(last) && last.length <= 70 ? last : heading || last })
        continue
      }
      if (t.type === 'heading' || t.type === 'paragraph') {
        const s = inline((t as Tokens.Heading).tokens ?? []).split('\n').pop()!.trim()
        if (s) last = s
        if (s && t.type === 'heading') heading = s
      }
      const kids = (t as { tokens?: Token[] }).tokens
      if (kids && t.type !== 'paragraph' && t.type !== 'heading') walk(kids)
      const items = (t as { items?: { tokens: Token[] }[] }).items
      if (items) for (const it of items) walk(it.tokens)
    }
  }
  walk(marked.lexer(text))
  return out
}

/* inline tokens as the text a reader sees: marked has already told emphasis from an identifier's underscores */
function inline(toks: Token[]): string {
  return toks.map((t) => {
    const kids = (t as { tokens?: Token[] }).tokens
    if (t.type === 'br') return ' '
    if (t.type === 'html') return ''
    if (kids?.length) return inline(kids)
    return decode((t as { text?: string }).text ?? '')
  }).join('')
}
const cell = (c: Tokens.TableCell) => inline(c.tokens ?? []).replace(/\s+/g, ' ').trim()
const decode = (s: string) => s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'")

/* a table's file name, from what the agent said just above it (a heading or a lead-in line), else the turn's words */
/* …kept short (what comes before a colon, a comma or an aside), but a scale the figures are in ("PKR mn", "Rs M") stays in
   the name: the chart reads it from there (a CSV has nowhere else to carry it) and never calls 11,521 (mn) "11.5K" */
export function tableName(t: MdTable, turn: string, n: number, of: number): string {
  const lead = t.before.replace(/[:：]\s*$/, '').trim()
  const src = lead || turn.replace(/[#>*_`|[\]]/g, ' ').trim().split(/\s+/).slice(0, 12).join(' ')
  const scale = scaleOf(lead || turn.split('\n').slice(0, 3).join(' '))         // from the WHOLE caption, before any cut
  const short = src.split(/\s*[(:：;]\s*|\s+[-–—]\s+/)[0].replace(/,/g, ' ').replace(/[^\w\s&%.'-]+/g, ' ').replace(/\s+/g, ' ')
    .split(' ').slice(0, 8).join(' ').slice(0, 60).trim() || 'table'
  const unit = scale && !scaleOf(short) ? ` (${scale.replace(/[^\w\s.'$-]+/g, ' ').trim()})` : ''
  return `${short}${unit}${of > 1 && !lead ? ` ${n}` : ''}.csv`
}
