/* An agent's provenance line (iteration 12). Agents end an answer with where its numbers came from (the org's
   provenance-footer law): "Source: o.product_pl…", "Sources: …", "Data used: …", "_Source: ClickHouse …_",
   "— lending · source: …". The chat draws that last paragraph as a quiet footer, not body text.

   CONSERVATIVE on purpose: only the LAST paragraph (or, with no blank line before it, the last line), only when it
   OPENS with one of the keywords and a colon (or is wholly italic and opens with one), only when it is short (≤ 3
   lines, ≤ 600 chars), never a table row, a list item or a code fence, and never when it is the whole answer. A
   sentence that merely mentions a source mid-paragraph stays prose. Pure: tests/web/chat_provenance_cases.ts. */

const KEY = String.raw`(?:sources?|data(?:\s+used|\s+sources?)?|provenance)`
const SIGNED = String.raw`(?:[—–-]\s*[\w-]{1,30}\s*·\s*)?`                      // "— lending · source: …"
const COLON = new RegExp(String.raw`^${SIGNED}(?:[_*]{1,2})?${KEY}(?:[_*]{1,2})?\s*:(?:[_*]{1,2})?[ \t]*\S`, 'i')
const ITALIC = new RegExp(String.raw`^([_*])${KEY}\b[^\n]*\S\1$`, 'i')           // "_Source ClickHouse, to 29 Oct_"
const MAX_CHARS = 600
const MAX_LINES = 3

export interface Split { body: string; source: string | null }

export function splitProvenance(text: string): Split {
  const t = (text ?? '').replace(/\s+$/, '')
  const none = { body: text, source: null }
  if (!t) return none
  const para = t.lastIndexOf('\n\n')
  let cut = para >= 0 ? para : -1
  let tail = t.slice(cut + 1).replace(/^\n+/, '')
  if (!fits(tail)) {                              // no blank line before it: the last line alone
    const nl = t.lastIndexOf('\n')
    if (nl < 0) return none
    cut = nl
    tail = t.slice(nl + 1)
    if (!fits(tail)) return none
  }
  const body = t.slice(0, Math.max(cut, 0)).replace(/\s+$/, '')
  if (!/\S/.test(body) || /```[^`]*$/.test(body)) return none   // the whole answer, or inside an open fence
  return { body, source: unwrap(tail.trim()) }
}

function fits(tail: string): boolean {
  const s = tail.trim()
  if (!s || s.length > MAX_CHARS || s.split('\n').length > MAX_LINES) return false
  if (/^(?:\||```|~~~|#{1,6}\s|>|\d{1,3}[.)]\s|[-*+]\s(?!\S*\s*·))/.test(s)) return false   // table/fence/heading/quote/list
  const first = s.split('\n')[0]
  return COLON.test(first) || (s.split('\n').length === 1 && ITALIC.test(s))
}

/* the footer as written, minus an italic wrapper around the whole line ("_Source: …_" -> "Source: …") */
function unwrap(s: string): string {
  const m = /^(\*\*|__|[_*])(?![_*])([\s\S]*[^_*\s])\1$/.exec(s)
  return m ? m[2].trim() : s
}
