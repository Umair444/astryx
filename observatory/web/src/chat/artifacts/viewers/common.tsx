import { useEffect, useState } from 'react'
import { contentOf, type Opened } from '../api'
import { showMedia } from '../../model'

/* What every viewer shares: the version's bytes (cached per revision by api.ts), a quiet loading line, an error, and
   the floating control pill a viewer puts its own controls in (zoom, page, sheet) so the panel header stays one row. */

export function useBlob(art: Opened, rev?: string): { blob: Blob | null; err: string } {
  const [blob, setBlob] = useState<Blob | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let live = true
    setBlob(null); setErr('')
    contentOf(art, rev).then((b) => live && setBlob(b)).catch((e) => live && setErr(String((e as Error).message ?? e)))
    return () => { live = false }
  }, [art.id, art.source, art.head, rev]) // eslint-disable-line react-hooks/exhaustive-deps
  return { blob, err }
}

export function useText(art: Opened, rev?: string): { text: string | null; err: string } {
  const { blob, err } = useBlob(art, rev)
  const [text, setText] = useState<string | null>(null)
  useEffect(() => { let live = true; setText(null); blob?.text().then((t) => live && setText(t)); return () => { live = false } }, [blob])
  return { text, err }
}

/* a version's bytes on a media element (img, audio, video): the ref this returns hands the element to model.ts's
   showMedia, the one object-URL sink the active-content gate admits (a media src, typed by the RESPONSE); the URL is
   revoked when the blob changes or the element goes. A blob URL never leaves an element, so it never becomes a link. */
type MediaEl = HTMLImageElement | HTMLAudioElement | HTMLVideoElement
export function useMediaSrc<T extends MediaEl>(blob: Blob | null): (el: T | null) => void {
  const [el, setEl] = useState<T | null>(null)
  useEffect(() => {
    if (!el || !blob) return
    showMedia(el, blob)
    // the element is detached by the time an unmount's cleanup runs: touching its src THEN makes Blink re-select the
    // image source and register a viewport listener on the document that is never removed (it is removed only when an
    // element leaves the tree, which already happened), and that listener held the whole page around it alive, a
    // library page per visit (iteration 14, heap snapshot). So: revoke the URL always, clear src only while attached.
    return () => { if (el.src.startsWith('blob:')) URL.revokeObjectURL(el.src); if (el.isConnected) el.removeAttribute('src') }
  }, [el, blob])
  return setEl
}
/* an <img> of a blob */
export function BlobImg({ blob, alt, ...p }: { blob: Blob; alt: string } & Omit<React.ImgHTMLAttributes<HTMLImageElement>, 'src'>) {
  const ref = useMediaSrc<HTMLImageElement>(blob)
  return <img ref={ref} alt={alt} {...p} />
}

export function Loading({ what = 'Opening' }: { what?: string }) {
  return (
    <div className="h-full grid place-items-center" aria-busy>
      <div className="flex items-center gap-2 text-[13px] text-ink-mute"><span className="ws-live-dot" aria-hidden />{what}…</div>
    </div>
  )
}
export function Failed({ err }: { err: string }) {
  return <div className="h-full grid place-items-center p-8"><div className="max-w-[340px] text-center text-[13px] text-ink-dim">{err}</div></div>
}

/* the floating control pill, bottom-centre of the viewer */
export function Pill({ children }: { children: React.ReactNode }) {
  return (
    <div className="absolute left-1/2 -translate-x-1/2 bottom-4 z-10 ws-pill flex items-center gap-0.5 px-1 h-9 rounded-full text-[12.5px] text-ink-dim tabular-nums">
      {children}
    </div>
  )
}
export function PillBtn({ onClick, label, children, disabled, pressed }: { onClick: () => void; label: string; children: React.ReactNode; disabled?: boolean; pressed?: boolean }) {
  return (
    <button onClick={onClick} disabled={disabled} aria-label={label} title={label} aria-pressed={pressed}
      className="min-w-7 h-7 px-1.5 rounded-full grid place-items-center hover:bg-[color-mix(in_srgb,var(--t-fg)_8%,transparent)] hover:text-ink disabled:opacity-35 aria-pressed:text-ink">
      {children}
    </button>
  )
}
