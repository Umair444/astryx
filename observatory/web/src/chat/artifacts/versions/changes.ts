/* "SEND MY CHANGES TO <agent>" (iteration 7): the owner's edits to an artifact go back to an agent as ONE ordinary wire
   message on the thread, readable as plain text by any agent:

     [changes to report.md: v2 (db) → v4 (owner)]
     I tightened the summary; please work from this version.

     ```diff
     @@ -3,4 +3,4 @@
     -Revenue rose 4%.
     +Revenue rose 4.2% (checked against o.product_pl).
     ```
     [[file:/…/report.md]] (report.md)

   The [[file:]] is the head's exact bytes (POST /api/ws/artifacts/{id}/export), so the agent reads the current file,
   not the diff alone. The diff is bounded (MAX_LINES); beyond it, a line says how much was left out. The chat draws
   this message as a "changes" card (thread/ChangesCard.tsx); this module is the one place the format lives. */

export const MAX_LINES = 120

export interface Changes {
  name: string
  fromN: number; fromWho: string
  toN: number; toWho: string
  note: string
  diff: string               // the unified hunks ('' for a file with no text)
  adds: number; dels: number
  omitted: number            // diff lines left out
}

export function changesBody(c: Omit<Changes, 'adds' | 'dels'>, path: string): string {
  const head = `[changes to ${c.name}: v${c.fromN} (${c.fromWho}) → v${c.toN} (${c.toWho})]`
  const diff = c.diff ? `\n\n\`\`\`diff\n${c.diff}\n\`\`\`` + (c.omitted ? `\n(${c.omitted} more diff lines not shown: the attached file is the whole new version)` : '') : ''
  return `${head}\n${c.note.trim()}${diff}\n[[file:${path}]] (${c.name})`
}

const HEAD = /^\[changes to (.+?): v(\d+) \(([\w-]+)\) → v(\d+) \(([\w-]+)\)\]\n?/
export function parseChanges(body: string): Changes | null {
  const b = body.replace(/^\[chat with [^\]]*\]\n/, '')
  const h = HEAD.exec(b)
  if (!h) return null
  let rest = b.slice(h[0].length).replace(/\[\[file:[^\]\n]+\]\](?: \([^)\n]{1,120}\))?/g, '')
  let diff = ''
  const at = rest.indexOf('```diff\n')
  if (at >= 0) {
    const end = rest.indexOf('\n```', at + 8)
    diff = rest.slice(at + 8, end < 0 ? undefined : end)
    rest = rest.slice(0, at) + (end < 0 ? '' : rest.slice(end + 4))
  }
  const om = /\((\d+) more diff lines not shown[^)]*\)/.exec(rest)
  const lines = diff.split('\n')
  return {
    name: h[1], fromN: +h[2], fromWho: h[3], toN: +h[4], toWho: h[5],
    note: rest.replace(/\((\d+) more diff lines not shown[^)]*\)/, '').trim(), diff,
    adds: lines.filter((l) => l.startsWith('+')).length, dels: lines.filter((l) => l.startsWith('-')).length,
    omitted: om ? +om[1] : 0,
  }
}
