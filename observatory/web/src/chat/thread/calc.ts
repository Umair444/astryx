/* THE CHAT'S CALCULATOR (owner 11-15: "press = and Qalculate it … a black box; LaTeX in it; Enter resolves it and the
   box shows expression = answer; only the answer goes to the agent; the box stays editable").
   A box is plain text in the composer between ⟦ and ⟧, so the cursor moves in and out of it like any text and it
   edits as text; the composer draws it as a dark box behind the textarea (Composer.tsx CalcMirror). Typing "= " where
   a word can start opens one; Enter inside it evaluates (POST /api/chat/calc, Qalculate in a sandbox) and writes
   "expression = answer"; on send each box becomes its answer alone. Leaving a box resolves it, entering it shows the
   expression again (settle). Pure: tests/chat_calc_test.ts runs it under node. */

export const OPEN = '⟦', CLOSE = '⟧'
const SEP = ' = '

/* "= " typed where a word can start (the line's start or after a space), outside a box: the box opens there. Returns
   the new text and caret, or null when the keystroke was ordinary. */
export function openCalc(text: string, caret: number): { text: string; caret: number } | null {
  if (caret < 2 || text[caret - 1] !== ' ' || text[caret - 2] !== '=') return null
  if (caret > 2 && !/\s/.test(text[caret - 3])) return null
  if (calcAt(text, caret - 2)) return null
  return { text: text.slice(0, caret - 2) + OPEN + CLOSE + text.slice(caret), caret: caret - 1 }
}

/* the box the caret is in: [start, end] are the ⟦ and ⟧ indexes, or null outside every box */
export function calcAt(text: string, caret: number): { start: number; end: number; inner: string } | null {
  const start = text.lastIndexOf(OPEN, caret - 1)
  if (start < 0) return null
  const closeBefore = text.lastIndexOf(CLOSE, caret - 1)
  if (closeBefore > start) return null
  const end = text.indexOf(CLOSE, start + 1)
  if (end < 0 || end < caret) return null
  return { start, end, inner: text.slice(start + 1, end) }
}

/* a box's contents: what was typed, and the answer once evaluated ("expr = answer"; the answer never holds " = ") */
export function splitCalc(inner: string): { expr: string; result: string | null } {
  const i = inner.lastIndexOf(SEP)
  return i < 0 ? { expr: inner.trim(), result: null } : { expr: inner.slice(0, i).trim(), result: inner.slice(i + SEP.length).trim() || null }
}

/* the box at [start, end] with its answer written in; the caret goes after the box */
export function setResult(text: string, box: { start: number; end: number; inner: string }, result: string): { text: string; caret: number } {
  const { expr } = splitCalc(box.inner)
  const inner = `${expr}${SEP}${result}`
  const out = text.slice(0, box.start) + OPEN + inner + CLOSE + text.slice(box.end + 1)
  return { text: out, caret: box.start + inner.length + 2 }
}

/* every box in the text, in order */
export function boxes(text: string): { start: number; end: number; inner: string }[] {
  const out: { start: number; end: number; inner: string }[] = []
  let i = 0
  for (;;) {
    const s = text.indexOf(OPEN, i)
    if (s < 0) break
    const e = text.indexOf(CLOSE, s + 1)
    if (e < 0) break
    out.push({ start: s, end: e, inner: text.slice(s + 1, e) })
    i = e + 1
  }
  return out
}

/* A BOX IS A CELL (owner 11-15: "the expression should resolve as the user gets out of it, and be back at the
   expression when inside the black box"): the box the caret is in shows its EXPRESSION alone, to edit; every other box
   shows "expression = answer". `known` holds the answers already worked out (expression -> answer), so leaving a box
   whose expression is unchanged resolves at once; an expression with no answer yet is returned in `ask`, for the
   composer to evaluate and settle again. The caret keeps its place in the text around it. Pure. */
export function settle(text: string, caret: number, known: Map<string, string>): { text: string; caret: number; ask: string[] } {
  let out = text, at = caret
  const ask: string[] = []
  for (const b of boxes(text).reverse()) {                 // last first: an edit never moves a box still to be read
    const { expr, result } = splitCalc(b.inner)
    const inside = caret > b.start && caret <= b.end
    if (result !== null && expr) known.set(expr, result)
    let inner = b.inner
    if (inside) inner = expr ? (result !== null ? expr : b.inner) : b.inner
    else if (expr && result === null) {
      const k = known.get(expr)
      if (k !== undefined) inner = `${expr}${SEP}${k}`
      else ask.push(expr)
    }
    if (inner === b.inner) continue
    out = out.slice(0, b.start + 1) + inner + out.slice(b.end)
    const delta = inner.length - b.inner.length
    if (inside) at = Math.min(at, b.start + 1 + inner.length)
    else if (b.end < caret) at += delta
  }
  return { text: out, caret: at, ask }
}

/* the text as it is SENT: each box its answer alone (owner: "only the answer goes to the agent"). `pending` lists the
   boxes with no answer yet, which the composer evaluates first. */
export function sendText(text: string): { text: string; pending: string[] } {
  const pending: string[] = []
  let out = '', i = 0
  for (const b of boxes(text)) {
    const { expr, result } = splitCalc(b.inner)
    out += text.slice(i, b.start) + (result ?? b.inner)
    if (result === null && expr) pending.push(expr)
    i = b.end + 1
  }
  return { text: out + text.slice(i), pending }
}

/* LaTeX, the way a person types it, as Qalculate reads it: fractions, roots, powers and subscripts in braces, the
   common operators, functions and constants, \left/\right. Anything else passes through for Qalculate to judge. */
export function latexToQalc(s: string): string {
  if (!/[\\{}]/.test(s)) return s
  let t = s
  const arg = String.raw`\{((?:[^{}]|\{[^{}]*\})*)\}`
  const once = (re: RegExp, f: (...m: string[]) => string) => { let prev; do { prev = t; t = t.replace(re, f as never) } while (t !== prev) }
  once(new RegExp(String.raw`\\[dt]?frac\s*${arg}\s*${arg}`), (_m, a, b) => `((${a})/(${b}))`)
  once(new RegExp(String.raw`\\sqrt\s*\[([^\]]+)\]\s*${arg}`), (_m, n, a) => `root(${a}, ${n})`)
  once(new RegExp(String.raw`\\sqrt\s*${arg}`), (_m, a) => `sqrt(${a})`)
  once(new RegExp(String.raw`\^\s*${arg}`), (_m, a) => `^(${a})`)
  once(new RegExp(String.raw`_\s*${arg}`), (_m, a) => `_${a}`)
  t = t.replace(/\\left|\\right/g, '')
       .replace(/\\(cdot|times)/g, '*').replace(/\\div/g, '/').replace(/\\pm/g, '+-')
       .replace(/\\pi\b/g, 'pi').replace(/\\infty\b/g, 'infinity').replace(/\\(alpha|beta|gamma|theta|lambda|mu|sigma|omega)\b/g, '$1')
       .replace(/\\(sin|cos|tan|ln|log|exp|arcsin|arccos|arctan|sinh|cosh|tanh)\b/g, '$1')
       .replace(/\\%/g, '%').replace(/\\,|\\;|\\!|\\ /g, ' ')
       .replace(/[{}]/g, (c) => (c === '{' ? '(' : ')'))
  return t.replace(/\s+/g, ' ').trim()
}
