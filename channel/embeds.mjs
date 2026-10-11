// The send tool's embed check (channel/server.mjs send, channel-bound rows only). canopus 2026-10-10/11: two owner
// polls went out as plain text because the body's `[[poll: …` never closed — the bridge grammar (bridges/common.py
// split_polls / split_files) only parses a CLOSED token and leaves anything else in the text, so the human saw raw
// brackets and no poll, and the send still reported "delivered". A poll with fewer than 2 options is worse: POLL_RE
// matches it, split_polls drops it, and the token is stripped, so the question vanishes without a trace. Refuse both
// in the sender's turn, before the INSERT, so the sender fixes the body instead of the reader puzzling over it.
//   · every `[[poll:` and `[[file:` must close with `]]` before the next `[[` (an unclosed one would otherwise swallow
//     a later token's `]]`, the non-greedy POLL_RE's behaviour);
//   · a poll needs a question + 2..MAX_OPTIONS options (`multi=N` is not an option); Discord and Telegram cap at 10
//     and truncate silently past it, so 10 is the portable ceiling;
//   · a file path must be absolute and name an existing file (the bridges send a "NOT sent" note after the fact;
//     refusing first means the text never claims an attachment that isn't there).
import { statSync } from 'node:fs'
import { isAbsolute } from 'node:path'

export const MAX_OPTIONS = 10

/** Problems with the [[poll:]] / [[file:]] embeds in `body`; [] when every embed will render. */
export function embedProblems(body) {
  const text = String(body ?? '')
  const out = []
  const re = /\[\[(poll|file):/g
  let m
  while ((m = re.exec(text))) {
    const kind = m[1]
    const start = m.index + m[0].length
    const close = text.indexOf(']]', start)
    const nextOpen = text.indexOf('[[', start)
    if (close === -1 || (nextOpen !== -1 && nextOpen < close)) {
      out.push(`unclosed [[${kind}: at char ${m.index} (add the closing "]]")`)
      continue
    }
    const inner = text.slice(start, close)
    if (kind === 'poll') {
      const parts = inner.split('|').map((p) => p.trim()).filter(Boolean)
      if (parts.length && /^multi=/i.test(parts[parts.length - 1].replace(/\s/g, ''))) parts.pop()
      const opts = parts.length - 1
      if (opts < 2) out.push(`poll "${(parts[0] || '').slice(0, 40)}" has ${Math.max(opts, 0)} option(s); needs a question + at least 2`)
      else if (opts > MAX_OPTIONS) out.push(`poll "${parts[0].slice(0, 40)}" has ${opts} options; Discord/Telegram keep only ${MAX_OPTIONS}`)
    } else {
      const p = inner.trim()
      let ok = false
      try { ok = isAbsolute(p) && statSync(p).isFile() } catch { ok = false }
      if (!ok) out.push(`[[file:${p}]] is not an absolute path to an existing file`)
    }
    re.lastIndex = Math.max(re.lastIndex, close + 2)   // never backwards: a bad `close` can't loop
  }
  return out
}
