import { useEffect, useRef, useState } from 'react'
import { displayName, fmtAgo } from '../api'
import { useStore } from '../store'
import type { Step } from '../types'
import AgentFace from '../components/AgentFace'
import { moodOf, nowLine } from '../ui/life'
import { download, fetchFile, kindOf, showMedia, stepLine, upload, visible, type Uploaded } from './model'

/* The side panel (plan-11884 C4/C5): whatever the conversation points at, opened beside it. A file (an upload or an
   agent's [[file:]] artifact) with light edits, or the WORKFORCE: every agent in this chat as a live lane.
   Edits never write in place: a rotated image or an edited text is saved as a NEW upload and offered back to the
   composer, so an agent's artifact is never silently changed under it. */

const UUID = /^[0-9a-f]{32}\.[a-z0-9]+$/
export function FileChip({ path, label, onOpen }: { path: string; label?: string; onOpen: (p: string) => void }) {
  const base = path.split('/').pop()!
  const k = kindOf(path)
  const name = label || (UUID.test(base) ? `Attached ${k === 'other' ? 'file' : k === 'pdf' ? 'PDF' : k}` : base)
  return (
    <button onClick={() => onOpen(path)} title={`Open ${name} beside the chat`}
      className="inline-flex items-center gap-1.5 max-w-[260px] rounded-lg border border-line bg-deck-2 hover:border-line-2 px-2 py-1 text-[12px] text-ink-dim hover:text-ink">
      <span aria-hidden className="text-ink-mute">{k === 'image' ? '▣' : k === 'pdf' ? '▤' : k === 'audio' ? '♪' : k === 'video' ? '▶' : '¶'}</span>
      <span className="truncate">{name}</span>
    </button>
  )
}

/* D2 (plan-11884): an image in an <img>, audio and video in their elements (a media src: C5's class a), text as a
   text node in a textarea, and a PDF or anything else as a DOWNLOAD (C5's class b). No in-page PDF renderer in v1:
   the first one is a trip (pdf.js ≥ 4.2.67 with scripting off, or its own origin). The type is the response's. */
export function Viewer({ path, onClose, onAttach }: { path: string; onClose: () => void; onAttach: (u: Uploaded) => void }) {
  const [blob, setBlob] = useState<Blob | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [kind, setKind] = useState<'image' | 'audio' | 'video' | 'text' | 'download' | null>(null)
  const [err, setErr] = useState('')
  const [rot, setRot] = useState(0)
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')
  const img = useRef<HTMLImageElement>(null)
  const audio = useRef<HTMLAudioElement>(null)
  const video = useRef<HTMLVideoElement>(null)
  const base = path.split('/').pop()!
  const name = UUID.test(base) ? `attachment.${base.split('.').pop()}` : base

  useEffect(() => {
    let live = true
    setBlob(null); setText(null); setKind(null); setErr(''); setRot(0); setNote('')
    fetchFile(path).then(async (r) => {
      const ct = (r.headers.get('content-type') ?? '').toLowerCase()
      const disp = (r.headers.get('content-disposition') ?? '').toLowerCase()
      if (!live) return
      if (ct.startsWith('text/plain') && !disp.startsWith('attachment')) { setText(await r.text()); setKind('text'); return }
      const b = await r.blob()
      if (!live) return
      setBlob(b)
      setKind(disp.startsWith('attachment') ? 'download' : ct.startsWith('image/') ? 'image' : ct.startsWith('audio/') ? 'audio'
        : ct.startsWith('video/') ? 'video' : 'download')
    }).catch((e) => live && setErr(String(e.message ?? e)))
    return () => { live = false }
  }, [path])
  useEffect(() => {
    if (!blob) return
    const el = kind === 'image' ? img.current : kind === 'audio' ? audio.current : kind === 'video' ? video.current : null
    if (el) showMedia(el, blob)
    return () => { if (el?.src.startsWith('blob:')) URL.revokeObjectURL(el.src) }
  }, [blob, kind])

  async function saveImage() {
    if (!blob) return
    setSaving(true)
    try {
      const pic = new Image()
      showMedia(pic, blob)
      await pic.decode()
      const c = document.createElement('canvas')
      const turn = rot % 180 !== 0
      c.width = turn ? pic.height : pic.width; c.height = turn ? pic.width : pic.height
      const g = c.getContext('2d')!
      g.translate(c.width / 2, c.height / 2); g.rotate((rot * Math.PI) / 180); g.drawImage(pic, -pic.width / 2, -pic.height / 2)
      URL.revokeObjectURL(pic.src)
      const out: Blob = await new Promise((res) => c.toBlob((b) => res(b!), 'image/png'))
      const u = await upload(out, name.replace(/\.[^.]+$/, '') + '-edited.png')
      onAttach(u); setNote('Saved as a new file and attached to your next message.')
    } catch (e) { setNote(String((e as Error).message ?? e)) } finally { setSaving(false) }
  }
  async function saveText() {
    if (text == null) return
    setSaving(true)
    try {
      const u = await upload(new Blob([text]), name.replace(/\.[^.]+$/, '') + '-edited.txt')
      onAttach(u); setNote('Saved as a new file and attached to your next message.')
    } catch (e) { setNote(String((e as Error).message ?? e)) } finally { setSaving(false) }
  }

  return (
    <section className="h-full flex flex-col" aria-label={`file ${name}`}>
      <header className="flex items-center gap-2 px-4 h-12 border-b border-line shrink-0">
        <span className="text-[13px] font-medium text-ink truncate flex-1" title={name}>{name}</span>
        {kind === 'image' && <>
          <button className="chat-tool" onClick={() => setRot((r) => (r + 270) % 360)} title="Rotate left">⟲</button>
          <button className="chat-tool" onClick={() => setRot((r) => (r + 90) % 360)} title="Rotate right">⟳</button>
          <button className="chat-tool" disabled={!rot || saving} onClick={saveImage}>Save copy</button>
        </>}
        {kind === 'text' && <button className="chat-tool" disabled={saving} onClick={saveText}>Save copy</button>}
        {blob && <button className="chat-tool" onClick={() => download(blob, name)}>Download</button>}
        <button className="chat-tool" onClick={onClose} title="Close (Esc)" aria-label="close the panel">✕</button>
      </header>
      <div className="flex-1 min-h-0 overflow-auto p-4 grid">
        {err && <div className="text-[13px] text-bad">{err}</div>}
        {!err && !kind && <div className="text-[13px] text-ink-mute">Opening…</div>}
        {kind === 'image' && <img ref={img} alt={name} className="max-w-full max-h-full m-auto rounded-lg transition-transform duration-200" style={{ transform: `rotate(${rot}deg)` }} />}
        {kind === 'audio' && <audio ref={audio} controls className="w-full self-start" />}
        {kind === 'video' && <video ref={video} controls className="w-full rounded-lg" />}
        {kind === 'text' && text != null && (
          <textarea value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} aria-label={`${name}, editable`}
            className="w-full h-full min-h-[60vh] resize-none rounded-lg bg-deck-2 border border-line p-3 font-mono text-[12.5px] leading-[1.6] text-ink outline-none focus:border-line-2" />
        )}
        {kind === 'download' && blob && (
          <div className="m-auto text-center max-w-[260px]">
            <div className="text-[14px] text-ink">{name}</div>
            <p className="mt-1 text-[12.5px] text-ink-mute">{(blob.size / 1024).toFixed(0)} KB. Files like this open on your device, never inside the observatory.</p>
            <button onClick={() => download(blob, name)} className="mt-3 rounded-lg px-3 py-1.5 text-[13px] font-medium bg-cyan text-on">Download</button>
          </div>
        )}
      </div>
      {note && <div className="px-4 py-2 border-t border-line text-[12px] text-ink-dim" role="status">{note}</div>}
    </section>
  )
}

/* THE WORKFORCE: one lane per agent in this chat (or this project). Its state in words and colour, what it is doing
   now, and its last few moves: the human watches the org work. */
export function Workforce({ agents, steps, unlinked, title }: { agents: string[]; steps: Record<string, Step[]>; unlinked: Record<string, number>; title: string }) {
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
          const recent = (steps[a] ?? []).filter(visible).slice(-5).reverse()
          return <Lane key={a} agent={a} mood={mood} line={mood === 'asleep' ? `asleep, seen ${fmtAgo(row?.last_seen ?? null)}` : nl.line} recent={recent} unfiled={unlinked[a] ?? 0} />
        })}
      </div>
    </section>
  )
}

function Lane({ agent, mood, line, recent, unfiled }: { agent: string; mood: string; line: string; recent: Step[]; unfiled: number }) {
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
      {unfiled > 0 && <div className="mt-1.5 text-[11.5px] text-ink-mute">{unfiled} earlier {unfiled === 1 ? 'step' : 'steps'} never filed to a turn</div>}
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
