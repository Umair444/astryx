import { useEffect, useMemo, useRef, useState } from 'react'
import { structuredPatch } from 'diff'
import { displayName } from '../../../api'
import AgentFace from '../../../components/AgentFace'
import { exportArtifact, type Opened, type Version } from '../api'
import { comparable, textForDiff } from './extract'
import { changesBody, MAX_LINES } from './changes'
import { who } from './VersionMenu'
import { DiffLines } from '../../thread/ChangesCard'

/* SEND MY CHANGES (iteration 7): the composer the panel opens after the owner changed an agent's file. Pick the agent
   (the last agent who wrote it, by default), say what you want in a line, and ONE message goes on this thread: the note,
   a compact unified diff of the text (≤ MAX_LINES lines, the rest summarized) and the exact current file as a
   [[file:]] (changes.ts holds the format). A file with no text (an image) goes as the note and the file. Loaded on
   first use: jsdiff's patch builder stays out of the chat's bundle. */

export interface Patch { text: string; adds: number; dels: number; omitted: number }

export function unified(a: string, b: string, name: string): Patch {
  const p = structuredPatch(name, name, a, b, undefined, undefined, { context: 2 })
  const lines: string[] = []
  let adds = 0, dels = 0
  for (const h of p.hunks) {
    lines.push(`@@ -${h.oldStart},${h.oldLines} +${h.newStart},${h.newLines} @@`)
    for (const l of h.lines) {
      if (l.startsWith('\\')) continue                      // "\ No newline at end of file": noise in a message
      if (l[0] === '+') adds++; else if (l[0] === '-') dels++
      lines.push(l)
    }
  }
  return { text: lines.slice(0, MAX_LINES).join('\n'), adds, dels, omitted: Math.max(0, lines.length - MAX_LINES) }
}

export default function SendChanges({ art, base, head, agents, initial, send, onClose, onSent }: {
  art: Opened
  base: Version                      // what the agent last saw
  head: Version                      // what the owner made
  agents: string[]
  initial: string                    // the default agent
  send: (agent: string, body: string) => Promise<unknown>
  onClose: () => void
  onSent: (agent: string) => void
}) {
  const [to, setTo] = useState(initial)
  const [note, setNote] = useState(`I changed ${art.name} (v${base.n} → v${head.n}). The diff is below and the current file is attached: please work from this version.`)
  const [patch, setPatch] = useState<Patch | null | 'none'>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const box = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { box.current?.focus(); box.current?.select() }, [])
  useEffect(() => {
    let live = true
    if (!comparable(art)) { setPatch('none'); return }
    Promise.all([textForDiff(art, base.rev), textForDiff(art, head.rev)])
      .then(([a, b]) => live && setPatch(a != null && b != null ? unified(a, b, art.name) : 'none'))
      .catch(() => live && setPatch('none'))
    return () => { live = false }
  }, [art.id, base.rev, head.rev]) // eslint-disable-line react-hooks/exhaustive-deps
  const p = patch && patch !== 'none' ? patch : null
  const shown = useMemo(() => p?.text ?? '', [p])

  async function go() {
    if (busy || !to || patch === null) return
    setBusy(true); setErr('')
    try {
      const { path } = await exportArtifact(art.id)
      const body = changesBody({ name: art.name, fromN: base.n, fromWho: base.author, toN: head.n, toWho: head.author, note, diff: shown, omitted: p?.omitted ?? 0 }, path)
      await send(to, body)
      onSent(to)
    } catch (e) {
      setErr(`Not sent: ${(e as Error).message}`)
    } finally { setBusy(false) }
  }

  return (
    <div className="ws-send-changes" role="dialog" aria-label="send your changes">
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-semibold text-ink">Send your changes</span>
        <span className="text-[12px] text-ink-mute tabular-nums truncate">v{base.n} ({who(base.author)}) → v{head.n} ({who(head.author)})</span>
        <button className="ws-icon !w-7 !h-7 ml-auto" onClick={onClose} aria-label="close" title="Close (Esc)">
          <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </div>
      <div className="flex items-center gap-1.5 flex-wrap mt-2" role="radiogroup" aria-label="send to">
        <span className="text-[12px] text-ink-mute mr-0.5">To</span>
        {agents.map((a) => (
          <button key={a} role="radio" aria-checked={to === a} onClick={() => setTo(a)} className="ws-pick">
            <AgentFace name={a} size={18} /><span>{displayName(a)}</span>
          </button>
        ))}
      </div>
      <textarea ref={box} value={note} onChange={(e) => setNote(e.target.value)} rows={3} aria-label="a note with your changes"
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void go() } if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}
        className="ws-input w-full mt-2 !h-auto py-2 leading-[1.5] resize-none" />
      <div className="mt-2 text-[12px] text-ink-mute flex items-center gap-2 flex-wrap">
        {patch === null ? <span>Comparing…</span>
          : p ? <>
            <span className="ws-diff-add-ink tabular-nums">+{p.adds}</span><span className="ws-diff-del-ink tabular-nums">−{p.dels}</span>
            <span>{p.adds + p.dels === 1 ? 'line' : 'lines'} changed{p.omitted ? ` · the diff shows ${MAX_LINES} lines, the file has the rest` : ''}</span>
          </>
          : <span>No text to compare: the note and the file go.</span>}
        <span className="ml-auto">+ the file, as v{head.n}</span>
      </div>
      {p && p.text && (
        <details className="ws-changes-diff mt-2">
          <summary>Preview the diff</summary>
          <DiffLines text={p.text} />
        </details>
      )}
      {err && <div className="mt-2 text-[12px] text-bad" role="alert">{err}</div>}
      <div className="mt-2.5 flex items-center justify-end gap-1.5">
        <span className="text-[11px] text-ink-mute mr-auto max-sm:hidden">⌘↵ to send</span>
        <button className="ws-btn !h-8" onClick={onClose}>Cancel</button>
        <button className="ws-btn ws-btn-primary !h-8" disabled={busy || patch === null || !note.trim()} onClick={() => void go()}>
          {busy ? 'Sending…' : `Send to ${displayName(to)}`}
        </button>
      </div>
    </div>
  )
}
