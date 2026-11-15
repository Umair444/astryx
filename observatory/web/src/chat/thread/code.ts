/* CODE IN AN ANSWER (owner 11-15, via db: "show code in a proper code interface: monospace, readable, a copy button").
   Two halves, both pure so tests/chat_code_test.ts runs them under node:
   - codeBlock(): a fenced block as the chat draws it: a bar with the language and a Copy button, then the code,
     escaped, its lines and indentation kept. Prose.tsx hands it to marked as the `code` renderer; the Copy click is
     delegated from the answer (data-copy), so no script rides in the sanitized HTML.
   - fenceBareSql(): an answer that pasted SQL WITHOUT a fence (db's 12138: two queries as prose) had its `*` read as
     emphasis and its indentation and line breaks flattened. A run that STARTS with a statement keyword at the start of
     a line, and holds a FROM, is fenced as sql before marked reads it. Conservative by construction: a sentence
     ("Select the rows from…") is not uppercase-led and has no line structure, so prose is never taken for code; a
     fenced block is never touched. */

const ESC: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
export const escapeHtml = (s: string) => s.replace(/[&<>"']/g, (c) => ESC[c])

export function codeBlock(text: string, lang?: string | null): string {
  const label = (lang || '').trim().split(/\s+/)[0].replace(/[^\w+#.-]/g, '').slice(0, 20)
  return `<div class="ws-code"><div class="ws-code-bar"><span class="ws-code-lang">${escapeHtml(label || 'code')}</span>`
    + `<button type="button" class="ws-code-copy" data-copy="1" aria-label="Copy the code">Copy</button></div>`
    + `<pre><code${label ? ` class="language-${escapeHtml(label)}"` : ''}>${escapeHtml(text.replace(/\n$/, ''))}</code></pre></div>`
}

// a line that opens a statement: the keyword in CAPITALS at the line's start (how SQL is written in an answer)
const OPENS = /^\s*(SELECT|WITH|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|INDEX|MATERIALIZED\s+VIEW)|EXPLAIN|MERGE\s+INTO)\b/
// a line that carries a statement on past a blank line: indented, a closing paren, or a clause keyword
const GOES_ON = /^(\s+\S|\)|(FROM|WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|UNION|JOIN|LEFT|RIGHT|INNER|FULL|CROSS|ON|AND|OR|LIMIT|FETCH|SELECT|WITH|WINDOW|QUALIFY)\b)/
const FENCE = /^\s*(```|~~~)/

export function fenceBareSql(md: string): string {
  const lines = md.split('\n')
  const out: string[] = []
  let inFence = false
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i]
    if (FENCE.test(l)) { inFence = !inFence; out.push(l); continue }
    if (inFence || !OPENS.test(l)) { out.push(l); continue }
    // the run: up to a blank line that the next line does not carry on past, or a fence, or the end
    let j = i + 1
    while (j < lines.length && !FENCE.test(lines[j])) {
      if (lines[j].trim()) { j++; continue }
      const next = lines.slice(j + 1).find((x) => x.trim())
      const fresh = next !== undefined && /^\S/.test(next) && OPENS.test(next)     // a new statement: its own run
      if (next !== undefined && !fresh && GOES_ON.test(next)) { j++; continue }
      break
    }
    while (j > i + 1 && !lines[j - 1].trim()) j--          // trailing blanks stay outside the fence
    const run = lines.slice(i, j)
    if (run.length >= 2 && run.some((x) => /\bFROM\b/.test(x)) || run.length === 1 && /\bFROM\b/.test(run[0]) && /\bSELECT\b/.test(run[0]) && run[0].length > 40) {
      out.push('```sql', ...run, '```')
      i = j - 1
    } else out.push(l)
  }
  return out.join('\n')
}
