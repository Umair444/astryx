import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { BASE } from './api'
import { I } from './ui'

/* Files in a conversation. Every file a message carries — an agent's [[file:/path]] or the line an
   upload leaves (<file attached: /path>) — becomes something you can SEE: images and video in place,
   everything else a card that opens a full-screen viewer. PDFs use the browser's own viewer; Word,
   PowerPoint and Excel are rendered to PDF on the server (LibreOffice) so they read as authored; text
   shows as text. Numbering matches the server's (_ANY_FILE in bridges/canvas.py). */

export const ANY_FILE = /\[\[file:([^\]]+)\]\]|<(?:file|voice) attached(?:, fetch failed: [^>]*)?: ([^>]+)>/g

export function filesOf(body: string): string[] {
  return [...body.matchAll(ANY_FILE)].map(x => (x[1] ?? x[2]).trim())
}

type Kind = 'image' | 'video' | 'audio' | 'pdf' | 'office' | 'text' | 'other'
const EXT: [RegExp, Kind][] = [
  [/\.(png|jpe?g|gif|webp|avif|svg)$/i, 'image'],
  [/\.(mp4|m4v|mov)$/i, 'video'],
  [/\.(mp3|ogg|wav|m4a|flac)$/i, 'audio'],
  [/\.pdf$/i, 'pdf'],
  [/\.(docx?|odt|rtf|pptx?|odp|xlsx?|ods)$/i, 'office'],
  [/\.(txt|md|csv|tsv|json|log|py|js|ts|tsx|sql|ya?ml|toml|sh|ini|xml)$/i, 'text'],
]
function kindOf(name: string): Kind {
  // a recorded voice note is cv-<ts>-voice.webm: sound only; any other webm is a video
  if (/\.webm$/i.test(name)) return /(^|[-_])voice\.webm$/i.test(name) ? 'audio' : 'video'
  return EXT.find(([r]) => r.test(name))?.[1] ?? 'other'
}

const BADGE: Record<string, { label: string; color: string }> = {
  pdf: { label: 'PDF', color: '#e5484d' }, doc: { label: 'DOC', color: '#2f6fed' }, docx: { label: 'DOC', color: '#2f6fed' },
  odt: { label: 'DOC', color: '#2f6fed' }, rtf: { label: 'DOC', color: '#2f6fed' },
  ppt: { label: 'PPT', color: '#e8590c' }, pptx: { label: 'PPT', color: '#e8590c' }, odp: { label: 'PPT', color: '#e8590c' },
  xls: { label: 'XLS', color: '#2b8a3e' }, xlsx: { label: 'XLS', color: '#2b8a3e' }, ods: { label: 'XLS', color: '#2b8a3e' },
  csv: { label: 'CSV', color: '#2b8a3e' },
}
function badge(name: string) {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  return BADGE[ext] ?? { label: (ext || 'file').slice(0, 4).toUpperCase(), color: 'var(--t-accent)' }
}

const pretty = (name: string) => name.replace(/^cv-\d+-/, '')

export function FileChip({ msgId, n, path }: { msgId: number; n: number; path: string }) {
  const [open, setOpen] = useState(false)
  const url = `${BASE}api/file?msg=${msgId}&n=${n}`
  const name = path.split('/').pop() ?? path
  const kind = kindOf(name)
  if (kind === 'audio') return <audio controls preload="metadata" src={`${url}&inline=1`} className="mt-2 w-full max-w-sm" />
  if (kind === 'video') {
    return <video controls playsInline preload="metadata" src={`${url}&inline=1`} className="mt-2 max-h-96 w-full max-w-xl rounded-2xl border border-line bg-black" />
  }
  const b = badge(name)
  return (
    <>
      {kind === 'image' ? (
        <button onClick={() => setOpen(true)} className="mt-2 block rounded-2xl overflow-hidden border border-line hover:border-violet/60 transition" title={pretty(name)}>
          <img src={url} alt={pretty(name)} className="max-h-80 max-w-full object-contain" />
        </button>
      ) : (
        <button onClick={() => setOpen(true)}
          className="mt-2 group flex items-center gap-3 w-full max-w-sm text-left rounded-2xl border border-line bg-fg/[.04] hover:bg-fg/[.07] hover:border-violet/50 px-3 py-2.5 transition">
          <span className="w-10 h-12 shrink-0 rounded-lg grid place-items-center text-[10px] font-bold text-white tracking-wide shadow-sm" style={{ background: b.color }}>{b.label}</span>
          <span className="min-w-0 flex-1">
            <span className="block text-[14px] truncate">{pretty(name)}</span>
            <span className="block text-[12px] text-fg-mute">{kind === 'other' ? 'Download' : 'Open'}{kind === 'office' ? ' · rendered as a PDF' : ''}</span>
          </span>
          <span className="text-fg-mute group-hover:text-fg">{I.expand('w-4 h-4')}</span>
        </button>
      )}
      <AnimatePresence>{open && <Viewer url={url} name={name} kind={kind} msgId={msgId} n={n} onClose={() => setOpen(false)} />}</AnimatePresence>
    </>
  )
}

function Viewer({ url, name, kind, msgId, n, onClose }: { url: string; name: string; kind: Kind; msgId: number; n: number; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [zoom, setZoom] = useState(false)
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  useEffect(() => {
    if (kind !== 'text') return
    fetch(`${url}&inline=1`, { credentials: 'same-origin' }).then(r => r.text()).then(t => setText(t.slice(0, 400_000))).catch(() => setText('could not load this file'))
  }, [kind, url])
  // 'other' has nothing to show: the card's click is a download
  useEffect(() => { if (kind === 'other') { location.href = url; onClose() } }, [kind, url, onClose])
  const src = kind === 'office' ? `${BASE}api/file/preview?msg=${msgId}&n=${n}` : `${url}&inline=1`

  return createPortal(
    <motion.div className="fixed inset-0 z-[200] flex flex-col" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      style={{ background: 'color-mix(in srgb, var(--t-bg) 88%, transparent)', backdropFilter: 'blur(10px)' }}
      onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="shrink-0 flex items-center gap-3 px-4 sm:px-6 h-14 border-b border-line">
        <span className="text-[14px] font-medium truncate">{pretty(name)}</span>
        {kind === 'office' && <span className="text-[11px] text-fg-mute hidden sm:inline">rendered as a PDF</span>}
        <a href={url} download={pretty(name)} className="ml-auto text-[13px] px-3 py-1.5 rounded-lg border border-line hover:bg-fg/[.06]">Download</a>
        <button onClick={onClose} aria-label="close" className="p-2 rounded-lg hover:bg-fg/[.06]">{I.x('w-4 h-4')}</button>
      </div>
      <motion.div className="flex-1 min-h-0 relative" initial={{ scale: 0.985, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ duration: 0.18 }}
        onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
        {kind === 'image' && (
          <div className={`absolute inset-0 overflow-auto grid ${zoom ? '' : 'place-items-center'} p-4`} onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
            <img src={url} alt={pretty(name)} onClick={() => setZoom(z => !z)}
              className={zoom ? 'max-w-none cursor-zoom-out' : 'max-w-full max-h-full object-contain cursor-zoom-in rounded-xl shadow-2xl'} />
          </div>
        )}
        {(kind === 'pdf' || kind === 'office') && (
          <>
            {!loaded && (
              <div className="absolute inset-0 grid place-items-center text-fg-mute text-sm">
                <div className="flex flex-col items-center gap-3">
                  <span className="w-8 h-8 rounded-full border-2 border-violet border-t-transparent animate-spin" />
                  {kind === 'office' ? 'Rendering the document…' : 'Opening…'}
                </div>
              </div>
            )}
            <iframe src={src} title={pretty(name)} onLoad={() => setLoaded(true)}
              className={`absolute inset-0 w-full h-full bg-white transition-opacity ${loaded ? 'opacity-100' : 'opacity-0'}`} />
          </>
        )}
        {kind === 'text' && (
          <div className="absolute inset-0 overflow-auto p-4 sm:p-8">
            <pre className="max-w-4xl mx-auto text-[13px] leading-relaxed font-mono whitespace-pre-wrap break-words bg-fg/[.04] border border-line rounded-2xl p-5">{text ?? 'Loading…'}</pre>
          </div>
        )}
      </motion.div>
    </motion.div>,
    document.body,
  )
}
