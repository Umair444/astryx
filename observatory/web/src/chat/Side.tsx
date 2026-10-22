import { useEffect, useRef, useState } from 'react'
import { displayName, fmtAgo } from '../api'
import { useStore } from '../store'
import type { Step } from '../types'
import AgentFace from '../components/AgentFace'
import { moodOf, nowLine } from '../ui/life'
import { blobUrl, kindOf, stepLine, upload, type Uploaded } from './model'

/* The side panel (plan-11884 C4/C5): whatever the conversation points at, opened beside it. A file (an upload or an
   agent's [[file:]] artifact) with light edits, or the WORKFORCE: every agent in this chat as a live lane.
   Edits never write in place: a rotated image or an edited text is saved as a NEW upload and offered back to the
   composer, so an agent's artifact is never silently changed under it. */

export function FileChip({ path, onOpen }: { path: string; onOpen: (p: string) => void }) {
  const name = path.split('/').pop()!.replace(/^chat-[0-9a-f]{24}-/, '')
  const k = kindOf(path)
  return (
    <button onClick={() => onOpen(path)} title={`Open ${name} beside the chat`}
      className="inline-flex items-center gap-1.5 max-w-[260px] rounded-lg border border-line bg-deck-2 hover:border-line-2 px-2 py-1 text-[12px] text-ink-dim hover:text-ink">
      <span aria-hidden className="text-ink-mute">{k === 'image' ? '▣' : k === 'pdf' ? '▤' : k === 'audio' ? '♪' : k === 'video' ? '▶' : '¶'}</span>
      <span className="truncate">{name}</span>
    </button>
  )
}

export function Viewer({ path, onClose, onAttach }: { path: string; onClose: () => void; onAttach: (u: Uploaded) => void }) {
  const [url, setUrl] = useState<string | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const [rot, setRot] = useState(0)
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')
  const k = kindOf(path)
  const name = path.split('/').pop()!.replace(/^chat-[0-9a-f]{24}-/, '')

  useEffect(() => {
    let live = true, made = ''
    setUrl(null); setText(null); setErr(''); setRot(0); setNote('')
    blobUrl(path).then(async (u) => {
      made = u
      if (!live) return URL.revokeObjectURL(u)
      if (k === 'text') setText(await (await fetch(u)).text())
      setUrl(u)
    }).catch((e) => live && setErr(String(e.message ?? e)))
    return () => { live = false; if (made) URL.revokeObjectURL(made) }
  }, [path, k])

  async function saveImage() {
    if (!url) return
    setSaving(true)
    try {
      const img = new Image(); img.src = url; await img.decode()
      const c = document.createElement('canvas')
      const turn = rot % 180 !== 0
      c.width = turn ? img.height : img.width; c.height = turn ? img.width : img.height
      const g = c.getContext('2d')!
      g.translate(c.width / 2, c.height / 2); g.rotate((rot * Math.PI) / 180); g.drawImage(img, -img.width / 2, -img.height / 2)
      const blob: Blob = await new Promise((r) => c.toBlob((b) => r(b!), 'image/png'))
      const u = await upload(blob, name.replace(/\.[^.]+$/, '') + '-edited.png')
      onAttach(u); setNote('Saved as a new file and attached to your next message.')
    } catch (e) { setNote(String((e as Error).message ?? e)) } finally { setSaving(false) }
  }
  async function saveText() {
    if (text == null) return
    setSaving(true)
    try {
      const u = await upload(new Blob([text], { type: 'text/plain' }), name.replace(/\.[^.]+$/, '') + '-edited' + (name.match(/\.[^.]+$/)?.[0] ?? '.txt'))
      onAttach(u); setNote('Saved as a new file and attached to your next message.')
    } catch (e) { setNote(String((e as Error).message ?? e)) } finally { setSaving(false) }
  }

  return (
    <section className="h-full flex flex-col" aria-label={`file ${name}`}>
      <header className="flex items-center gap-2 px-4 h-12 border-b border-line shrink-0">
        <span className="text-[13px] font-medium text-ink truncate flex-1" title={name}>{name}</span>
        {k === 'image' && url && <>
          <button className="chat-tool" onClick={() => setRot((r) => (r + 270) % 360)} title="Rotate left">⟲</button>
          <button className="chat-tool" onClick={() => setRot((r) => (r + 90) % 360)} title="Rotate right">⟳</button>
          <button className="chat-tool" disabled={!rot || saving} onClick={saveImage}>Save copy</button>
        </>}
        {k === 'text' && text != null && <button className="chat-tool" disabled={saving} onClick={saveText}>Save copy</button>}
        <button className="chat-tool" onClick={onClose} title="Close (Esc)" aria-label="close the panel">✕</button>
      </header>
      <div className="flex-1 min-h-0 overflow-auto p-4 grid">
        {err && <div className="text-[13px] text-bad">{err}</div>}
        {!err && !url && <div className="text-[13px] text-ink-mute">Opening…</div>}
        {url && k === 'image' && <img src={url} alt={name} className="max-w-full max-h-full m-auto rounded-lg transition-transform duration-200" style={{ transform: `rotate(${rot}deg)` }} />}
        {url && k === 'pdf' && <iframe src={url} title={name} className="w-full h-full min-h-[70vh] rounded-lg bg-white" />}
        {url && k === 'audio' && <audio src={url} controls className="w-full self-start" />}
        {url && k === 'video' && <video src={url} controls className="w-full rounded-lg" />}
        {url && k === 'text' && text != null && (
          <textarea value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
            className="w-full h-full min-h-[60vh] resize-none rounded-lg bg-deck-2 border border-line p-3 font-mono text-[12.5px] leading-[1.6] text-ink outline-none focus:border-line-2" />
        )}
      </div>
      {note && <div className="px-4 py-2 border-t border-line text-[12px] text-ink-dim" role="status">{note}</div>}
    </section>
  )
}

/* THE WORKFORCE: one lane per agent in this chat (or this project). Its state in words and colour, what it is doing
   now, and its last few moves: the human watches the org work. */
export function Workforce({ agents, steps, title }: { agents: string[]; steps: Record<string, Step[]>; title: string }) {
  const { agents: roster, presence } = useStore()
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 4000); return () => clearInterval(t) }, [])
  return (
    <section className="h-full flex flex-col" aria-label="workforce">
      <header className="px-4 h-12 flex items-center border-b border-line shrink-0">
        <span className="text-[13px] font-medium text-ink">{title}</span>
        <span className="ml-auto text-[12px] text-ink-mute tabular-nums">{agents.length} {agents.length === 1 ? 'agent' : 'agents'}</span>
      </header>
      <div className="flex-1 min-h-0 overflow-y-auto p-3 flex flex-col gap-2.5">
        {agents.length === 0 && <div className="p-3 text-[13px] text-ink-mute">Mention an agent with @ and it joins this chat. Its work shows up here as it happens.</div>}
        {agents.map((a) => {
          const row = roster.find((r) => r.agent === a)
          const p = presence[a]
          const mood = row ? moodOf(row, p, now) : 'asleep'
          const nl = row ? nowLine(row, p, mood, now) : { where: '', line: '' }
          const recent = (steps[a] ?? []).slice(-5).reverse()
          return <Lane key={a} agent={a} mood={mood} line={mood === 'asleep' ? `asleep, seen ${fmtAgo(row?.last_seen ?? null)}` : nl.line} recent={recent} />
        })}
      </div>
    </section>
  )
}

function Lane({ agent, mood, line, recent }: { agent: string; mood: string; line: string; recent: Step[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const working = mood === 'working'
  return (
    <div ref={ref} className={`rounded-xl border px-3 py-2.5 ${working ? 'border-cyan/50 bg-cyan/[0.06]' : 'border-line bg-deck-2'}`}>
      <div className="flex items-center gap-2.5">
        <span className="relative shrink-0"><AgentFace name={agent} size={26} dim={mood === 'asleep'} />{working && <span className="chat-halo absolute -inset-1 rounded-full pointer-events-none" aria-hidden />}</span>
        <span className="text-[13px] font-semibold text-ink">{displayName(agent)}</span>
        <span className={`ml-auto text-[11.5px] ${working ? 'text-cyan' : mood === 'awake' ? 'text-good' : 'text-ink-mute'}`}>{mood}</span>
      </div>
      {line && <div className="mt-1.5 text-[12.5px] text-ink-dim leading-snug line-clamp-2">{line}</div>}
      {recent.length > 0 && (
        <ol className="mt-2 flex flex-col gap-0.5">
          {recent.map((s, i) => (
            <li key={s.id} className={`font-mono text-[11px] truncate ${i === 0 && working ? 'text-ink' : 'text-ink-mute'}`}>{stepLine(s)}</li>
          ))}
        </ol>
      )}
    </div>
  )
}
