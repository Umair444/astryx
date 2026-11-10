/* Iteration 9, data-forward: what a table's columns ARE, read from their values (and a header hint), so a chart can
   be picked without asking. Pure functions over string rows (the CSV parser's and the xlsx reader's shape): no DOM,
   no chart library, cheap enough to run on every render of a 20k-row sheet (it samples). */

export type ColType = 'time' | 'number' | 'category' | 'empty'
export interface Column {
  i: number
  name: string
  type: ColType
  distinct: number            // distinct non-empty values in the sample
  pct: boolean                // its numbers were written as percentages
  scaled: boolean             // the header already names a scale (PKR mn, '000, bn): figures are shown as written
  rank: boolean               // an ordinal (a rank, a serial number): a number nobody plots as a magnitude
  unit: string                // a currency/unit prefix the values carried (Rs, PKR, $), shown on the axis
}

/* ── numbers ─────────────────────────────────────────────────────────────────────────────────────────────── */
/* "1,234.5", "-12%", "(3,400)" (accounting negative), "Rs 1,200", "PKR 3.4M"? no: suffixed magnitudes are text an
   agent typed for humans, and guessing them would chart a wrong number. Only plain, comma-grouped figures parse. */
const CUR = '(?:Rs|PKR|USD|US\\$|\\$|€|£|₨)'
const NUM_RE = new RegExp(`^\\(?[-+]?(?:${CUR}\\.?\\s?)?[-+]?(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d+)?(?:e[+-]?\\d+)?\\)?\\s?%?$`, 'i')
const PREFIX = new RegExp(`^\\(?-?(${CUR})\\.?\\s?(?=-?\\d)`, 'i')
/* typography an agent's prose uses (a true minus −, an en dash, a thin space, a footnote star) reads as plain */
const norm = (raw: string) => raw.replace(/[\u2212\u2013]/g, '-').replace(/[\u2009\u202f\u00a0]/g, ' ').replace(/\s*[*†‡]+$/, '').trim()
export function parseNum(raw: string): number | null {
  let s = norm(raw)
  // a figure with an aside, "5,699.8 (49.5%)": the figure
  if (!NUM_RE.test(s)) { const m = /^(.*?\d)\s*\([^()]*\)$/.exec(s); if (m) s = m[1] }
  if (!s || !NUM_RE.test(s) || !/\d/.test(s)) return null
  const neg = (s.startsWith('(') && s.endsWith(')')) || /^\(?-/.test(s) || /^\(?\D+?\s?-\d/.test(s)
  const digits = s.replace(PREFIX, '').replace(/[(),%\s]/g, '').replace(/^[-+]+/, '')
  const n = parseFloat(digits)
  if (!Number.isFinite(n)) return null
  return neg ? -n : n
}
const isPct = (s: string) => /%\s*\)?$/.test(norm(s))
const unitOf = (s: string) => {
  const m = PREFIX.exec(s.trim())
  return m ? m[1] : ''
}

/* ── time ────────────────────────────────────────────────────────────────────────────────────────────────── */
/* a date, a month, a week, a quarter, a year (by header): each to a sortable instant. Day-first slashes (dd/mm/yyyy,
   the org's locale) are read day-first; an ambiguous US date is not guessed at. */
const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
const mon = (s: string) => MONTHS.indexOf(s.slice(0, 3).toLowerCase())
const yr = (s: string) => { const n = +s; return s.length === 2 ? 2000 + n : n }
export function parseTime(raw: string): number | null {
  const s = raw.trim()
  if (!s || s.length > 32) return null
  let m: RegExpExecArray | null
  if ((m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T\s](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}:?\d{2})?)?$/.exec(s)))
    return Date.UTC(+m[1], +m[2] - 1, +m[3], +(m[4] ?? 0), +(m[5] ?? 0), +(m[6] ?? 0))
  if ((m = /^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$/.exec(s))) return +m[2] <= 12 ? Date.UTC(+m[3], +m[2] - 1, +m[1]) : null
  if ((m = /^(\d{4})[-/](\d{1,2})$/.exec(s)) && +m[2] >= 1 && +m[2] <= 12) return Date.UTC(+m[1], +m[2] - 1, 1)
  if ((m = /^(\d{4})[-\s]?W(\d{1,2})$/i.exec(s))) return Date.UTC(+m[1], 0, 1 + (+m[2] - 1) * 7)
  if ((m = /^Q([1-4])[-\s']*(\d{2}|\d{4})$/i.exec(s))) return Date.UTC(yr(m[2]), (+m[1] - 1) * 3, 1)
  if ((m = /^(\d{4})[-\s]?Q([1-4])$/i.exec(s))) return Date.UTC(+m[1], (+m[2] - 1) * 3, 1)
  if ((m = /^([A-Za-z]{3,9})[-\s']*(\d{2}|\d{4})$/.exec(s)) && mon(m[1]) >= 0) return Date.UTC(yr(m[2]), mon(m[1]), 1)
  if ((m = /^(\d{1,2})[-\s]([A-Za-z]{3,9})[-\s](\d{2}|\d{4})$/.exec(s)) && mon(m[2]) >= 0) return Date.UTC(yr(m[3]), mon(m[2]), +m[1])
  return null
}
const TIME_HINT = /(^|[^a-z])(date|day|dt|month|mon|week|wk|period|year|yr|quarter|qtr|time|hour|hr|ts|timestamp)([^a-z]|$)/i
const YEAR_HINT = /(^|[^a-z])(year|yr|fy)([^a-z]|$)/i

/* ── columns ─────────────────────────────────────────────────────────────────────────────────────────────── */
const SAMPLE = 600
const RANK_HINT = /(^|[^a-z])(rank|ranking|position|serial|sr\.?\s?no|s\.?\s?no)([^a-z]|$)/i
/* THE SCALE A FIGURE IS ALREADY IN, named by a caption, a header, a file or a sheet title ("PKR mn", "Rs M", "(k)",
   "USD bn", "'000"): read from the FULL text, before anything truncates it. A chart of figures in a named scale
   shows them as written (11,521 PKR mn, never "11.5K") and says the scale. Returns the scale as written, cleaned
   ("PKR mn"), or '' when none is named. A bare "k" counts only as a word of its own ("Revenue (k)"), never "5k". */
const SCALE_WORD = /(?:^|[\s(\[,;/:])((?:PKR|Rs\.?|USD|US\$|\$)\s*)?(mn|mln|million|millions|bn|bln|billion|billions|k|thousand|thousands|'000|000s|crore|crores|lakh|lakhs)(?=$|[\s)\],;/:.])/i
const SCALE_CUR = /(?:^|[^A-Za-z])((?:PKR|Rs\.?|USD)\s?)(M|B|K)(?=$|[^A-Za-z])/
export function scaleOf(text: string): string {
  const s = (text ?? '').replace(/[\u2009\u202f\u00a0]/g, ' ')
  const m = SCALE_WORD.exec(s) ?? SCALE_CUR.exec(s)
  if (!m) return ''
  return `${m[1] ? m[1].trim() + ' ' : ''}${m[2]}`.replace(/\s+/g, ' ')
}

export function inferColumns(head: string[], body: string[][]): Column[] {
  const width = Math.max(head.length, ...body.slice(0, 200).map((r) => r.length), 0)
  const sample = body.length > SAMPLE ? body.filter((_, k) => k % Math.ceil(body.length / SAMPLE) === 0) : body
  return Array.from({ length: width }, (_, i) => {
    const name = (head[i] ?? '').trim() || (i === 0 ? 'Item' : `Column ${i + 1}`)     // an unheaded first column labels the rows
    const vals = sample.map((r) => (r[i] ?? '').trim()).filter((v) => v !== '' && !/^(null|none|n\/a|na|-|—)$/i.test(v))
    const distinct = new Set(vals).size
    const base = { i, name, distinct, pct: false, unit: '', scaled: false, rank: false }
    if (!vals.length) return { ...base, type: 'empty' as const }
    const nums = vals.filter((v) => parseNum(v) !== null)
    const times = vals.filter((v) => parseTime(v) !== null)
    // a year column is numbers by shape, time by meaning: the header decides
    if (YEAR_HINT.test(name) && nums.length === vals.length && nums.every((v) => /^(19|20)\d{2}$/.test(v)))
      return { ...base, type: 'time' as const }
    if (times.length >= vals.length * 0.9 && (times.length > nums.length || TIME_HINT.test(name))) return { ...base, type: 'time' as const }
    if (nums.length >= vals.length * 0.9) {
      // an id is a number nobody adds up: all-distinct integers under an id-ish header
      if (/(^|[^a-z])(id|code|msisdn|number|no|#)([^a-z]|$)/i.test(name) && distinct === vals.length) return { ...base, type: 'category' as const }
      const units = new Set(nums.map(unitOf).filter(Boolean))
      const ints = nums.map((v) => parseNum(v)!)
      const rank = RANK_HINT.test(name) || (distinct === vals.length && vals.length > 3 && ints.every((n) => Number.isInteger(n) && n >= 1 && n <= vals.length + 1) && /(^|[^a-z])(no|sr|s\.no|#|n)\.?([^a-z]|$)/i.test(name))
      return {
        ...base, type: 'number' as const, pct: nums.filter(isPct).length >= nums.length * 0.5 || /(%|percent|pct|share|rate)\b/i.test(name) && ints.every((n) => Math.abs(n) <= 100),
        unit: units.size === 1 ? [...units][0] : '', scaled: scaleOf(name) !== '', rank,
      }
    }
    return { ...base, type: 'category' as const }
  })
}

/* a column's value as a number (time columns as their instant; a bare year as Jan 1 of it) */
export function valueOf(c: Column, raw: string | undefined): number | null {
  const s = (raw ?? '').trim()
  if (!s) return null
  if (c.type === 'time') return /^(19|20)\d{2}$/.test(s) ? Date.UTC(+s, 0, 1) : parseTime(s)
  return parseNum(s)
}

/* ── the table's body: the header row out, empty rows out, a trailing TOTAL row out (it would dwarf every bar) ─ */
export function bodyOf(rows: string[][]): { head: string[]; body: string[][]; total: boolean } {
  const head = rows[0] ?? []
  let body = rows.slice(1).filter((r) => r.some((c) => (c ?? '').trim() !== ''))
  const last = body.at(-1)
  const total = !!last && /^((grand|net|overall)\s+)?totals?:?$/i.test((last.find((c) => (c ?? '').trim() !== '') ?? '').trim())
  if (total) body = body.slice(0, -1)
  return { head, body, total }
}
