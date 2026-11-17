import { memo, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Msg } from '../../types'
import { download, fetchFile, fileSize, type Embed } from '../model'
import { kindOfName, nameOf, type Kind } from '../artifacts/api'
import { originFrom, useOpenRequest, type OpenRequest } from '../artifacts/FileChip'
import { bytes, KindIcon, KIND_WORD } from '../artifacts/kinds'
import { BlobImg, useMediaSrc } from '../artifacts/viewers/common'
import { firstPage, useVisible } from '../library/FileCard'
import { I } from '../icons'
import './inline.css'

/* A FILE WHERE IT WAS EMBEDDED (owner 11-11: "inline is how people like to see it"). A [[file:]] in a body is drawn at
   its place in the text, the way a modern chat does: an image as a rounded picture (a click opens it large in the
   artifact panel), audio and video as the browser's own players, a PDF as its first page, anything else as a file
   card (name, kind, size, open, download). The chip row at the end of the message stays (the "option at the end");
   it is small, so nothing is shown twice as a big thing. A non-media embed that ENDS the body is left to that row
   alone: drawn here too it would be the same file twice, side by side.
   Bytes come the one way every file comes (model.fetchFile: the owner key as a header, the type the server sniffed),
   only once the spot scrolls near, and are held per (message, path): a re-render, a live update or a window that
   remounts the turn draws the same bytes at the same size, no refetch, no flash. */

const PDF_MAX = 15 * 1024 * 1024

/* ------------------------------------------------------------------------------------------------- the bytes */
interface Held { p: Promise<Blob>; blob?: Blob; w?: number; h?: number; size?: number | null }
const held = new Map<string, Held>()
const HOLD = 64                                   // most recently drawn files; the oldest is let go
function hold(key: string, path: string): Held {
  let e = held.get(key)
  if (e) { held.delete(key); held.set(key, e); return e }
  const fresh: Held = { p: fetchFile(path).then((r) => r.blob()) }
  fresh.p.then((b) => { fresh.blob = b }, () => held.delete(key))
  held.set(key, (e = fresh))
  while (held.size > HOLD) held.delete(held.keys().next().value!)
  return e
}
const keyOf = (msg: Msg | undefined, path: string) => `${msg?.id ?? 0}|${path}`

function useBytes(key: string, path: string, want: boolean): { blob: Blob | null; err: string } {
  const [blob, setBlob] = useState<Blob | null>(() => held.get(key)?.blob ?? null)
  const [err, setErr] = useState('')
  useEffect(() => {
    if (!want || blob) return
    let live = true
    hold(key, path).p.then((b) => live && setBlob(b), (e) => live && setErr(String((e as Error).message ?? e)))
    return () => { live = false }
  }, [key, path, want, blob])
  return { blob, err }
}

/* the conversation's scroller, if it sits at its end: an image that grows there keeps the end in view */
function scroller(el: Element | null): HTMLElement | null {
  for (let p = el?.parentElement; p; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY
    if ((o === 'auto' || o === 'scroll') && p.scrollHeight > p.clientHeight) return p
  }
  return null
}
const atEnd = (s: HTMLElement | null) => !!s && s.scrollHeight - s.scrollTop - s.clientHeight < 96

/* ------------------------------------------------------------------------------------------------- one embed */
export const InlineFile = memo(function InlineFile({ e, from, msg, onOpen }: { e: Embed; from: string; msg?: Msg; onOpen: (r: OpenRequest) => void }) {
  const name = nameOf(e.path, e.label)
  const kind = kindOfName(name)
  const { req } = useOpenRequest(e.path, e.label, from, msg)
  const open = (el: Element) => { originFrom(el); onOpen(req) }
  const key = keyOf(msg, e.path)
  if (kind === 'image') return <InlineImage k={key} path={e.path} name={name} open={open} />
  if (kind === 'audio' || kind === 'video') return <InlinePlayer k={key} path={e.path} name={name} kind={kind} open={open} />
  if (kind === 'pdf') return <InlinePdf k={key} path={e.path} name={name} open={open} />
  return <InlineCard k={key} path={e.path} name={name} kind={kind} open={open} />
}, (a, b) => a.e.path === b.e.path && a.e.label === b.e.label && a.from === b.from && a.msg === b.msg && a.onOpen === b.onOpen)

function InlineImage({ k, path, name, open }: { k: string; path: string; name: string; open: (el: Element) => void }) {
  const { ref, seen } = useVisible<HTMLDivElement>()
  const { blob, err } = useBytes(k, path, seen)
  const [dim, setDim] = useState(() => { const h = held.get(k); return h?.w ? { w: h.w, h: h.h! } : null })
  const [bad, setBad] = useState(false)
  const stick = useRef(false)
  useLayoutEffect(() => {
    if (!stick.current) return
    stick.current = false
    const s = scroller(ref.current)
    if (s) s.scrollTop = s.scrollHeight
  }, [dim, ref])
  if (err || bad) return <InlineCard k={k} path={path} name={name} kind="image" open={open} note={err ? 'Could not load the image' : 'This image could not be shown'} />
  return (
    <div ref={ref} className="ws-inline ws-inline-img" data-file-name={name}>
      <button type="button" onClick={(ev) => open(ev.currentTarget)} title={`Open ${name} large`} aria-label={`Open ${name} large`}
        className={`ws-inline-pic ${dim ? '' : 'is-loading'}`} style={dim ? { aspectRatio: `${dim.w} / ${dim.h}`, width: Math.min(dim.w, 520) } : undefined}>
        {blob && (
          <BlobImg blob={blob} alt={name} draggable={false} decoding="async" className={dim ? '' : 'opacity-0'}
            onLoad={(ev) => {
              const i = ev.currentTarget
              if (!i.naturalWidth) return setBad(true)
              const h = held.get(k)
              if (h) { h.w = i.naturalWidth; h.h = i.naturalHeight }
              if (!dim) { stick.current = atEnd(scroller(ref.current)); setDim({ w: i.naturalWidth, h: i.naturalHeight }) }
            }}
            onError={() => setBad(true)} />
        )}
      </button>
    </div>
  )
}

function InlinePlayer({ k, path, name, kind, open }: { k: string; path: string; name: string; kind: 'audio' | 'video'; open: (el: Element) => void }) {
  const { ref, seen } = useVisible<HTMLDivElement>()
  const { blob, err } = useBytes(k, path, seen)
  const audio = useMediaSrc<HTMLAudioElement>(kind === 'audio' ? blob : null)
  const video = useMediaSrc<HTMLVideoElement>(kind === 'video' ? blob : null)
  if (err) return <InlineCard k={k} path={path} name={name} kind={kind} open={open} note={`Could not load the ${kind}`} />
  return (
    <div ref={ref} className={`ws-inline ws-inline-${kind}`} data-file-name={name}>
      {kind === 'video'
        ? <video ref={video} controls preload="metadata" playsInline className="ws-inline-video-el" aria-label={name} />
        : <audio ref={audio} controls preload="metadata" className="ws-inline-audio-el" aria-label={name} />}
      <button type="button" className="ws-inline-cap" onClick={(ev) => open(ev.currentTarget)} title={`Open ${name} beside the chat`}>
        <KindIcon kind={kind} className="w-3.5 h-3.5 shrink-0" /><span className="truncate">{name}</span>
      </button>
    </div>
  )
}

function InlinePdf({ k, path, name, open }: { k: string; path: string; name: string; open: (el: Element) => void }) {
  const { ref, seen } = useVisible<HTMLDivElement>()
  const { blob, err } = useBytes(k, path, seen)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [paper, setPaper] = useState(false)
  useEffect(() => {
    if (!blob || blob.size > PDF_MAX) return
    let live = true
    firstPage(blob, canvas.current, () => live).then((ok) => live && setPaper(ok)).catch(() => {})
    return () => { live = false }
  }, [blob])
  return (
    <div ref={ref} className="ws-inline ws-inline-pdf" data-file-name={name}>
      <button type="button" onClick={(ev) => open(ev.currentTarget)} title={`Open ${name} beside the chat`} className="ws-inline-paper">
        <canvas ref={canvas} className="ws-inline-page" data-on={paper} aria-hidden />
        {!paper && <span className="ws-inline-paper-ph"><KindIcon kind="pdf" className="w-8 h-8" /></span>}
      </button>
      <CardRow k={k} path={path} name={name} kind="pdf" open={open} blob={blob} coming note={err ? 'Could not load the PDF' : ''} />
    </div>
  )
}

function InlineCard({ k, path, name, kind, open, note }: { k: string; path: string; name: string; kind: Kind; open: (el: Element) => void; note?: string }) {
  return <div className="ws-inline ws-inline-file" data-file-name={name}><CardRow k={k} path={path} name={name} kind={kind} open={open} note={note} /></div>
}

/* the file line every inline shape shares: icon, name, kind · size, Download (the bytes held above, else fetched) */
/* coming: the bytes are on their way (the PDF's page), so the size waits for them instead of asking */
function CardRow({ k, path, name, kind, open, blob, coming, note }: { k: string; path: string; name: string; kind: Kind; open: (el: Element) => void; blob?: Blob | null; coming?: boolean; note?: string }) {
  const { ref, seen } = useVisible<HTMLDivElement>()
  const [size, setSize] = useState<number | null>(() => blob?.size ?? held.get(k)?.blob?.size ?? held.get(k)?.size ?? null)
  useEffect(() => {
    if (blob) { setSize(blob.size); return }
    if (!seen || size !== null || note || coming) return
    let live = true
    fileSize(path).then((n) => { if (!live) return; setSize(n); const h = held.get(k); if (h) h.size = n }).catch(() => {})
    return () => { live = false }
  }, [seen, blob, path, k, size, note, coming])
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setBusy(true)
    try { download(await hold(k, path).p, name) } catch { /* the note below the card says it */ } finally { setBusy(false) }
  }
  return (
    <div ref={ref} className="ws-inline-row">
      <button type="button" onClick={(ev) => open(ev.currentTarget)} title={`Open ${name} beside the chat`} className="ws-inline-open">
        <span className="ws-chip-icon shrink-0 grid place-items-center w-9 h-9 rounded-[10px]"><KindIcon kind={kind} className="w-[18px] h-[18px]" /></span>
        <span className="min-w-0 flex flex-col leading-tight">
          <span className="truncate text-[13.5px] font-medium text-ink">{name}</span>
          <span className="text-[11.5px] text-ink-mute truncate">{note || [KIND_WORD[kind], size !== null ? bytes(size) : ''].filter(Boolean).join(' · ')}</span>
        </span>
      </button>
      {!note && (
        <button type="button" className="ws-inline-dl" onClick={() => void save()} disabled={busy} title={`Download ${name}`} aria-label={`Download ${name}`}>
          {I.down()}
        </button>
      )}
    </div>
  )
}
