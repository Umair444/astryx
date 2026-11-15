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
  return `<div class="ws-cb"><div class="ws-cb-bar"><span class="ws-cb-lang">${escapeHtml(label || 'code')}</span>`
    + `<button type="button" class="ws-cb-copy" data-copy="1" aria-label="Copy the code">Copy</button></div>`
    + `<pre><code data-lang="${escapeHtml(label)}">${escapeHtml(text.replace(/\n$/, ''))}</code></pre></div>`
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

/* ── ANY CODE, for a human's own words (owner 11-15: "when a user writes a query or code in the chatbox … show it like
   a black box, how the Claude app shows it … queries and code can be detected programmatically"). A paragraph (a run
   between blank lines) is code when most of its lines are code-shaped; neighbouring code paragraphs of one language
   join into one block (a function's blank lines don't split it). Conservative: a list, a sentence, a short line is
   never taken; a fence the human wrote is never touched. Agents fence their own (the wire's instructions), and their
   answers keep only fenceBareSql. */
// each form needs a CODE-SHAPED head: "for each row in the table: what's missing?" and "while you're at it: …" are
// words (medic 12168); `for x in rows:` and `while n > 0:` end at the colon with nothing after
const PY = /^\s*(def \w+\(|class \w+[(:]|import [\w.]+( as \w+)?(, [\w.]+)*$|from [\w.]+ import |if __name__|@\w+(\(.*\))?$|elif .+:$|except( \w+)?( as \w+)?:$|try:$|with .+ as \w+:$|for \w+(, ?\w+)* in \S+:$|while \S.*[^?!]:$|return\b|print\()/
const JS = /^\s*(const \w+ =|let \w+ =|var \w+ =|function \w*\(|async function|export (default |const |function |class )|import .+ from ['"]|class \w+ \{|console\.\w+\(|document\.\w+|module\.exports)/
// a shell line is a command WITH an argument shape: "cd ops team asked" and "git the latest numbers" are words
const SH = /^\s*(\$ \S|sudo \S|cd [~./\w-]+\/?\S*$|ls( -\w+)*( \S+)?$|git (status|log|pull|push|clone|checkout|switch|diff|add|commit|fetch|merge|rebase|branch|stash|reset|show)\b|npm (install|i|ci|run|test)\b|npx \S|pip3? install\b|python3? [\w./-]+\.py\b|python3? -[mc]\b|curl (-\S+ )*\S*:\/\/|docker (run|ps|exec|build|compose|logs|pull)\b|kubectl \w+|export [A-Z_]+=|ssh [\w.-]+@?[\w.-]+$|scp \S+ \S+$|chmod [0-7+\w]+ \S+$|mkdir (-p )?\S+$|cat \S+$|grep (-\S+ )*\S+ \S+|systemctl \w+ \S+$|tmux \w+|psql \S)/
const LINE_CODE = /([;{}]\s*$|^\s*[}\])]|^\s*(#include|\/\/|<\/?[a-z][\w-]*[ >])|\)\s*:\s*$|=>|:=|==|!=|\w+\(.*\)\s*;?$)/
// a line that reads as words whatever else it holds: a contraction, or a question/exclamation at its end
const WORDY = /\b\w+'(s|re|t|ll|ve|d|m)\b|[?!]\s*$/

export function codeLang(block: string): string | null {
  const lines = block.split('\n').filter((l) => l.trim())
  if (lines.length < 2) return null
  const t = block.trim()
  if ((t.startsWith('{') && t.endsWith('}')) || (t.startsWith('[') && t.endsWith(']'))) {
    try { JSON.parse(t); return 'json' } catch { /* not JSON: judged below */ }
  }
  if (OPENS.test(lines[0]) && lines.some((l) => /\bFROM\b/.test(l))) return 'sql'
  const share = (re: RegExp) => lines.filter((l) => re.test(l)).length / lines.length
  const prose = lines.filter((l) => /^[A-Z][^;{}()=<>]*[.?!]$/.test(l.trim()) || /^\s*([-*•]|\d+[.)])\s+\w/.test(l) || WORDY.test(l)).length / lines.length
  if (prose > 0.3) return null                       // sentences and lists are words, whatever else they hold
  if (share(SH) >= 0.6) return 'bash'
  const code = share(LINE_CODE)
  if (share(PY) >= 0.2 && (code >= 0.3 || lines.some((l) => /:\s*$/.test(l)))) return 'python'
  if (share(JS) >= 0.2 && code >= 0.4) return 'javascript'
  if (code >= 0.6 && lines.length >= 3) return 'code'
  return null
}

export function fenceBareCode(md: string): string {
  const pre = fenceBareSql(md)                      // SQL first: its rule knows statements across blank lines
  const lines = pre.split('\n')
  const out: string[] = []
  let inFence = false, para: string[] = []
  const blocks: { lines: string[]; lang: string | null; fence: boolean }[] = []
  // a paragraph called code keeps any leading lines that read as words OUTSIDE the block ("why is this slow?" on the
  // line above a pasted query or an HTML dump)
  const words = (l: string) => !(PY.test(l) || JS.test(l) || SH.test(l) || LINE_CODE.test(l) || OPENS.test(l) || /^\s*[<{[]/.test(l))
  const flush = () => {
    if (!para.length) return
    const lang = codeLang(para.join('\n'))
    let k = 0
    if (lang) while (k < para.length - 2 && words(para[k])) k++
    if (k) blocks.push({ lines: para.slice(0, k), lang: null, fence: false })
    blocks.push({ lines: para.slice(k), lang: k ? codeLang(para.slice(k).join('\n')) ?? lang : lang, fence: false })
    para = []
  }
  for (const l of lines) {
    if (FENCE.test(l)) {
      if (!inFence) { flush(); para = [l]; inFence = true } else { para.push(l); blocks.push({ lines: para, lang: null, fence: true }); para = []; inFence = false }
      continue
    }
    if (inFence) { para.push(l); continue }
    if (!l.trim()) { flush(); blocks.push({ lines: [l], lang: null, fence: false }); continue }
    para.push(l)
  }
  if (inFence) blocks.push({ lines: para, lang: null, fence: true }); else flush()
  // a short paragraph that is all code-shaped ("import pandas as pd", a closing "print(x)") joins the code block one
  // blank line away; on its own it is too short to call (codeLang needs two lines)
  const shaped = (b: { lines: string[] }) => b.lines.length <= 2 && b.lines.every((l) => PY.test(l) || JS.test(l) || SH.test(l) || LINE_CODE.test(l))
  for (let pass = 0; pass < 2; pass++) {
    for (let i = 0; i < blocks.length; i++) {
      const b = blocks[i]
      if (b.lang || b.fence || !b.lines[0].trim() || !shaped(b)) continue
      const near = [blocks[i - 2], blocks[i + 2]].find((x, k) => x && x.lang && !x.fence && !blocks[k ? i + 1 : i - 1].lines[0].trim())
      if (near) b.lang = near.lang
    }
  }
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i]
    if (!b.lang || b.fence) { out.push(...b.lines); continue }
    let j = i + 1, end = i                          // join code paragraphs of one language across single blank lines
    while (j + 1 < blocks.length && !blocks[j].lines[0].trim() && blocks[j + 1].lang === b.lang && !blocks[j + 1].fence) { end = j + 1; j += 2 }
    out.push('```' + (b.lang === 'code' ? '' : b.lang), ...blocks.slice(i, end + 1).flatMap((x) => x.lines), '```')
    i = end
  }
  return out.join('\n')
}

/* a pasted block on its way out of the composer: code is sent fenced (so every surface draws it as code), anything
   else as it was pasted */
export function fencePaste(text: string): string {
  if (/^\s*(```|~~~)/m.test(text)) return text
  const lang = codeLang(text)
  return lang ? '```' + (lang === 'code' ? '' : lang) + '\n' + text.replace(/\n+$/, '') + '\n```' : text
}

/* the composer's long-paste token (Claude Code's shape) and its expansion on send: each token becomes its paste on
   lines of its own, code fenced. Ids are never reused in a tab (the composer persists its counter with the pastes),
   so an old token can't pick up a new paste. `missing`: a token whose paste is gone (a reload past the store) and
   `broken`: a token edited out of its shape; the composer refuses to send either, rather than lose the text quietly
   (medic 12168). */
export const pasteToken = (id: number, lines: number) => `[Pasted text #${id} +${lines} lines]`
const PASTE_TOKEN = /\[Pasted text #(\d+) \+\d+ lines\]/g
export function expandPasteTokens(text: string, pastes: Map<number, string>): { text: string; missing: number[]; broken: boolean } {
  const missing: number[] = []
  const out = text.replace(PASTE_TOKEN, (tok, id) => {
    const t = pastes.get(Number(id))
    if (t === undefined) { missing.push(Number(id)); return tok }
    return `\n${fencePaste(t)}\n`
  })
  const broken = /\[Pasted text #/.test(text.replace(PASTE_TOKEN, ''))
  return { text: out, missing, broken }
}
