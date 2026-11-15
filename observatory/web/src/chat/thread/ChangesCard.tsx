import { useState } from 'react'
import { personName } from '../../api'
import type { Changes } from '../artifacts/versions/changes'

/* The owner's "send my changes" message (artifacts/versions/changes.ts) as the chat shows it: a card, never raw diff
   text. "Changes to report.md · v2 → v4 · +3 −1", the owner's note, the diff folded until asked for. The file chip
   (the exact version sent) is drawn by the turn beneath it, like any other file. */

export default function ChangesCard({ ch }: { ch: Changes }) {
  const [open, setOpen] = useState(false)
  const lines = ch.diff ? ch.diff.split('\n').length : 0
  return (
    <div className="ws-changes">
      <div className="flex items-center gap-2 min-w-0 text-[12.5px]">
        <span className="ws-changes-glyph" aria-hidden>
          <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M7 4v10M2.5 9h9M14 19h8" /></svg>
        </span>
        <span className="text-ink-dim truncate">Changes to <b className="font-semibold text-ink">{ch.name}</b></span>
        <span className="text-ink-mute tabular-nums shrink-0" title={`from v${ch.fromN} (${personName(ch.fromWho, 'you')}) to v${ch.toN} (${personName(ch.toWho, 'you')})`}>v{ch.fromN} → v{ch.toN}</span>
        {(ch.adds > 0 || ch.dels > 0) && <span className="ml-auto shrink-0 tabular-nums flex gap-1.5">
          <span className="ws-diff-add-ink">+{ch.adds}</span><span className="ws-diff-del-ink">−{ch.dels}</span>
        </span>}
      </div>
      {ch.note && <div className="mt-1.5 text-[15px] leading-[1.55] text-ink whitespace-pre-wrap break-words">{ch.note}</div>}
      {lines > 0 && <>
        <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="mt-1.5 inline-flex items-center gap-1.5 text-[12px] text-ink-mute hover:text-ink">
          <span className={`inline-block transition-transform ${open ? 'rotate-90' : ''}`} aria-hidden>›</span>
          {open ? 'Hide the diff' : `Show the diff · ${lines} ${lines === 1 ? 'line' : 'lines'}`}{ch.omitted ? ` (+${ch.omitted} not sent)` : ''}
        </button>
        {open && <DiffLines text={ch.diff} />}
      </>}
    </div>
  )
}

/* a unified diff's lines, tinted the way the diff view tints (added green, removed red, hunk headers quiet) */
export function DiffLines({ text }: { text: string }) {
  return (
    <pre className="ws-difflines" aria-label="the diff">
      {text.split('\n').map((l, i) => (
        <span key={i} className={l.startsWith('@@') ? 'is-hunk' : l[0] === '+' ? 'is-add' : l[0] === '-' ? 'is-del' : ''}>{l || ' '}{'\n'}</span>
      ))}
    </pre>
  )
}
