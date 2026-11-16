/* THE DRAFT, DRAWN (owner 11-16: "the black box should appear detecting the code in the chatbox … and other md
   things as well"): the composer's text read as the chat will draw it, WHILE it is typed, not after Enter. Composer's
   mirror paints these behind the transparent textarea, so every mark must keep the exact glyph geometry of plain
   text: colour, background, a stroke for weight, never a font, size or padding. Pure, so tests/chat_draft_test.ts
   runs it under node.
   - blocks(): the text cut into runs of whole LINES, each a ``` or ~~~ fence (open to its close, or to the end while it is
     still being typed) or ordinary text; joined by '\n' they are the text again, so each draws as one block, line for
     line with the textarea.
   - spans(): one ordinary run cut into what it shows: a ⟦calc⟧ box, `code`, **strong**, a # heading line, text.
   - codeAt(): whether a place in the text is code, where "= " is the code's own text and never opens a calc box
     (medic 12585: "where a = 1" in a fence had lost its "=" to a box the fence drew as plain text). */

export const OPEN = '⟦', CLOSE = '⟧'      // a calc box's marks (calc.ts); here so draft.ts needs nothing back from it

export interface Block { fence: boolean; text: string; closed?: boolean }
export interface Span { kind: 'text' | 'calc' | 'code' | 'strong' | 'head'; text: string }

const OPEN_FENCE = /^ {0,3}(`{3,}(?=[^`]*$)|~{3,})/      // ``` or ~~~, as code.ts reads a fence (medic 12587)
export function blocks(text: string): Block[] {
  const out: Block[] = []
  const push = (fence: boolean, line: string) => {
    const last = out[out.length - 1]
    if (last && last.fence === fence && !fence) last.text += '\n' + line
    else out.push({ fence, text: line })
  }
  const lines = text.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const m = OPEN_FENCE.exec(lines[i])
    if (!m) { push(false, lines[i]); continue }
    const close = new RegExp(`^ {0,3}${m[1][0]}{${m[1].length},}\\s*$`)
    let j = i + 1
    while (j < lines.length && !close.test(lines[j])) j++
    out.push({ fence: true, text: lines.slice(i, Math.min(j, lines.length - 1) + 1).join('\n'), closed: j < lines.length })
    i = j
  }
  return out
}

const INLINE = new RegExp(`${OPEN}[^${CLOSE}]*${CLOSE}|\`[^\`\\n]+\`|\\*\\*[^*\\n]+\\*\\*|^#{1,6} [^\\n]*`, 'gm')
export function spans(s: string): Span[] {
  const out: Span[] = []
  let i = 0
  for (const m of s.matchAll(INLINE)) {
    if (m.index! > i) out.push({ kind: 'text', text: s.slice(i, m.index) })
    const t = m[0]
    out.push({ kind: t[0] === OPEN ? 'calc' : t[0] === '`' ? 'code' : t[0] === '#' ? 'head' : 'strong', text: t })
    i = m.index! + t.length
  }
  if (i < s.length) out.push({ kind: 'text', text: s.slice(i) })
  return out
}

/* inside a fence (closed or still open), or inside `…` on its line (closed or still being typed: an odd count of
   backticks before it) */
export function codeAt(text: string, i: number): boolean {
  let at = 0
  for (const b of blocks(text)) {
    const end = at + b.text.length
    if (i <= end) {
      if (b.fence) return true
      const line = text.slice(text.lastIndexOf('\n', i - 1) + 1, i)
      return (line.match(/`/g)?.length ?? 0) % 2 === 1
    }
    at = end + 1
  }
  return false
}

/* anything to draw: the mirror (and the transparent textarea over it) only while it is */
export const drawn = (text: string) => blocks(text).some((b) => b.fence || spans(b.text).some((s) => s.kind !== 'text'))
