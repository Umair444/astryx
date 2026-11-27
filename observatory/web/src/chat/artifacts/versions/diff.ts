import { diffLines, diffWordsWithSpace } from 'diff'

/* The diff model (DESIGN.md "versions are named; prose diffs are word-level"). Two passes: LINES first, so a change
   is a paragraph/line block (tinted 12%); inside each changed block, WORDS (the changed words tinted 28%). Long runs
   of unchanged lines fold to their context. The view (DiffView) only paints this. */

export interface Seg { text: string; hit: boolean }               // a run of words; hit = changed in this version
export type Block =
  | { kind: 'same'; text: string; lines: number }
  | { kind: 'fold'; text: string; lines: number }                 // unchanged lines folded away, expandable
  | { kind: 'change'; left: Seg[] | null; right: Seg[] | null; inline: { text: string; op: -1 | 0 | 1 }[]; lines: number }

export interface DiffResult { blocks: Block[]; added: number; removed: number }

const CONTEXT = 3
const nLines = (s: string) => Math.max(1, s.replace(/\n$/, '').split('\n').length)
const words = (s: string) => (s.match(/\S+/g) ?? []).length

export function computeDiff(a: string, b: string): DiffResult {
  const norm = (s: string) => (s.endsWith('\n') ? s : s + '\n')
  const parts = diffLines(norm(a), norm(b))
  const blocks: Block[] = []
  let added = 0, removed = 0
  for (let i = 0; i < parts.length; i++) {
    const p = parts[i]
    if (!p.added && !p.removed) {
      const lines = p.value.replace(/\n$/, '').split('\n')
      const first = i === 0, last = i === parts.length - 1
      const keepHead = first ? 0 : CONTEXT, keepTail = last ? 0 : CONTEXT
      if (lines.length > keepHead + keepTail + 2) {
        if (keepHead) blocks.push({ kind: 'same', text: lines.slice(0, keepHead).join('\n'), lines: keepHead })
        const mid = lines.slice(keepHead, lines.length - keepTail)
        blocks.push({ kind: 'fold', text: mid.join('\n'), lines: mid.length })
        if (keepTail) blocks.push({ kind: 'same', text: lines.slice(-keepTail).join('\n'), lines: keepTail })
      } else blocks.push({ kind: 'same', text: lines.join('\n'), lines: lines.length })
      continue
    }
    // a removal followed by an addition is ONE changed block, compared word by word
    const del = p.removed ? p.value : ''
    const add = p.added ? p.value : (parts[i + 1]?.added && p.removed ? parts[++i].value : '')
    const left: Seg[] = [], right: Seg[] = [], inline: { text: string; op: -1 | 0 | 1 }[] = []
    if (del && add) {
      for (const w of diffWordsWithSpace(del.replace(/\n$/, ''), add.replace(/\n$/, ''))) {
        if (w.removed) { left.push({ text: w.value, hit: true }); inline.push({ text: w.value, op: -1 }); removed += words(w.value) }
        else if (w.added) { right.push({ text: w.value, hit: true }); inline.push({ text: w.value, op: 1 }); added += words(w.value) }
        else { left.push({ text: w.value, hit: false }); right.push({ text: w.value, hit: false }); inline.push({ text: w.value, op: 0 }) }
      }
    } else if (del) { left.push({ text: del.replace(/\n$/, ''), hit: true }); inline.push({ text: del.replace(/\n$/, ''), op: -1 }); removed += words(del) }
    else { right.push({ text: add.replace(/\n$/, ''), hit: true }); inline.push({ text: add.replace(/\n$/, ''), op: 1 }); added += words(add) }
    blocks.push({ kind: 'change', left: del ? left : null, right: add ? right : null, inline, lines: Math.max(del ? nLines(del) : 0, add ? nLines(add) : 0) })
  }
  return { blocks, added, removed }
}
