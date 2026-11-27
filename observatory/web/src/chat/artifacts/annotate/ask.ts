import { isHuman, type Msg } from '../../../types'
import type { Ann } from './types'

/* ASK-THE-MARGIN (DESIGN.md wow #5). Asking an agent about a highlight sends ONE ordinary wire message on the current
   thread, through the app's own send path:

     > "…the quoted passage…"
     — finance_summary.pdf (v1, p.2)

     the question

     [[ann:ask.k3j9x0q2ab.finance]]

   The trailing marker ties the message to its margin card; the chat strips it and draws the quote as a chip that opens
   the highlight. The asked agent's NEXT message on the thread after the ask (and before a later ask to the same agent)
   is its answer, and threads into the card as a reply. */

export const ANN_MARK = /\s*\[\[ann:([\w.-]{1,80})\]\]\s*/g
export const stripAnn = (s: string) => s.replace(ANN_MARK, '\n').trim()

export const askAgent = (a: Ann): string | null => (a.id.startsWith('ask.') ? a.id.split('.').slice(2).join('.') || null : null)

const QUOTE_MAX = 280
export function askBody(quote: string, source: string, question: string, id: string): string {
  let q = quote.replace(/\s+/g, ' ').trim()
  if (q.length > QUOTE_MAX) q = q.slice(0, QUOTE_MAX - 1).trimEnd() + '…'
  return `> "${q}"\n— ${source}\n\n${question.trim()}\n\n[[ann:${id}]]`
}

export interface ParsedAsk { quote: string; source: string; name: string; question: string; ann: string }
const ASK = /^> "([\s\S]*?)"\n— ([^\n]+)\n\n([\s\S]*?)\s*\[\[ann:([\w.-]{1,80})\]\]\s*$/
export function parseAsk(body: string): ParsedAsk | null {
  const m = ASK.exec(body.replace(/^\[chat with [^\]]*\]\n/, ''))
  if (!m) return null
  const name = m[2].replace(/\s*\((?:v\d+|p\.\d+)(?:, ?(?:v\d+|p\.\d+))*\)\s*$/, '').trim()
  return { quote: m[1], source: m[2].trim(), name, question: m[3].trim(), ann: m[4] }
}

/* each ask's wire message, and the answer to it if one has come */
export function answers(items: Ann[], rows: Msg[]): Record<string, { asked: Msg | null; answer: Msg | null }> {
  const out: Record<string, { asked: Msg | null; answer: Msg | null }> = {}
  const asks = items.filter((a) => askAgent(a))
  if (!asks.length) return out
  const sent = new Map<string, Msg>()
  for (const m of rows) if (isHuman(m.from)) for (const x of m.body.matchAll(ANN_MARK)) if (!sent.has(x[1])) sent.set(x[1], m)
  for (const a of asks) {
    const agent = askAgent(a)!
    const asked = sent.get(a.id) ?? null
    if (!asked) { out[a.id] = { asked: null, answer: null }; continue }
    // the next ask to the same agent bounds this one's answer window
    const nextAsk = rows.find((m) => m.id > asked.id && isHuman(m.from) && m.to === agent && /\[\[ann:/.test(m.body))
    const answer = rows.find((m) => m.id > asked.id && m.from === agent && (!nextAsk || m.id < nextAsk.id)) ?? null
    out[a.id] = { asked, answer }
  }
  return out
}
