import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { contentOf, type Opened } from '../api'
import { BlobImg, Failed, Loading } from '../viewers/common'
import { computeDiff, type Block, type Seg } from './diff'
import { textForDiff } from './extract'
import VersionMenu from './VersionMenu'

/* DIFF MODE: any two versions, compared word by word. Header "v3 (db) → v4 (owner)" with both ends selectable, the
   word counts, and a Side-by-side / Unified switch (side-by-side by default when the panel is wide). Side by side is
   ONE scroller with two columns, so the sides can never drift apart; unified inlines the changed words (struck for
   removed, tinted for added). A minimap on the right marks where the changes are; a click jumps there. PDFs, Word
   files and sheets are compared by their text; images side by side, by eye. */

export default function DiffView({ art, from, to, onFrom, onTo, wide }: {
  art: Opened
  from: string
  to: string
  onFrom: (rev: string) => void
  onTo: (rev: string) => void
  wide: boolean
}) {
  const [mode, setMode] = useState<'split' | 'unified'>(wide ? 'split' : 'unified')
  useEffect(() => { setMode(wide ? 'split' : 'unified') }, [wide])
  const [texts, setTexts] = useState<[string | null, string | null] | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let live = true
    setTexts(null); setErr('')
    if (art.kind === 'image') return
    Promise.all([textForDiff(art, from), textForDiff(art, to)]).then((t) => live && setTexts(t))
      .catch((e) => live && setErr(`These versions could not be compared (${(e as Error).message}).`))
    return () => { live = false }
  }, [art.id, from, to]) // eslint-disable-line react-hooks/exhaustive-deps
  const diff = useMemo(() => (texts && texts[0] != null && texts[1] != null ? computeDiff(texts[0], texts[1]) : null), [texts])
  const mono = art.kind === 'code' || art.kind === 'table' || art.kind === 'sheet'

  return (
    <div className="h-full flex flex-col">
      <div className="shrink-0 flex items-center gap-2 flex-wrap px-4 py-2 border-b border-line">
        <VersionMenu versions={art.versions} current={from} onPick={onFrom} label="Compare from" />
        <span className="text-ink-mute" aria-hidden>→</span>
        <VersionMenu versions={art.versions} current={to} onPick={onTo} label="Compare to" />
        {diff && (
          <span className="text-[12px] tabular-nums ml-1 flex gap-2">
            <span className="ws-diff-add-ink">+{diff.added} {diff.added === 1 ? 'word' : 'words'}</span>
            <span className="ws-diff-del-ink">−{diff.removed}</span>
          </span>
        )}
        <div className="ml-auto flex items-center gap-0.5 ws-seg" role="radiogroup" aria-label="diff layout">
          {(['split', 'unified'] as const).map((m) => (
            <button key={m} role="radio" aria-checked={mode === m} onClick={() => setMode(m)}>{m === 'split' ? 'Side by side' : 'Unified'}</button>
          ))}
        </div>
      </div>
      {from === to && <div className="shrink-0 px-4 py-1.5 text-[12px] text-ink-mute border-b border-line/60">The same version on both sides: pick another to compare.</div>}
      <div className="flex-1 min-h-0 relative">
        {art.kind === 'image' ? <ImagePair art={art} from={from} to={to} />
          : err ? <Failed err={err} />
          : !texts ? <Loading what="Comparing" />
          : !diff ? <Failed err="This kind of file has no text to compare." />
          : <Blocks diff={diff.blocks} split={mode === 'split'} mono={mono} />}
      </div>
    </div>
  )
}

function Blocks({ diff, split, mono }: { diff: Block[]; split: boolean; mono: boolean }) {
  const scroller = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState<Set<number>>(new Set())
  // the minimap: each change block's real place in the scroller, measured after layout (prose wraps; lines lie)
  const [marks, setMarks] = useState<{ at: number; size: number; i: number }[]>([])
  useLayoutEffect(() => {
    const el = scroller.current
    if (!el) return
    const measure = () => {
      const H = el.scrollHeight || 1
      setMarks(diff.flatMap((b, i) => {
        if (b.kind !== 'change') return []
        const c = el.querySelector<HTMLElement>(`[data-b="${i}"]`)
        return c ? [{ at: c.offsetTop / H, size: c.offsetHeight / H, i }] : []
      }))
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el.firstElementChild ?? el)
    return () => ro.disconnect()
  }, [diff, split, open])
  const jump = (i: number) => scroller.current?.querySelector(`[data-b="${i}"]`)?.scrollIntoView({ block: 'center' })
  const nothing = !diff.some((b) => b.kind === 'change')

  return (
    <div className="h-full flex">
      <div ref={scroller} className={`relative flex-1 min-w-0 overflow-auto ${mono ? 'ws-diff-mono' : 'ws-diff-prose'}`}>
        {nothing && <div className="px-6 pt-6 text-[13px] text-ink-mute">No differences: these two versions hold the same text.</div>}
        <div className={`py-5 pb-20 ${split ? 'grid grid-cols-2' : 'max-w-[760px] mx-auto'}`}>
          {diff.map((b, i) => {
            if (b.kind === 'fold' && !open.has(i)) return (
              <button key={i} data-b={i} onClick={() => setOpen((s) => new Set(s).add(i))} className={`ws-diff-fold ${split ? 'col-span-2' : ''}`}>
                {b.lines} unchanged {b.lines === 1 ? 'line' : 'lines'}
              </button>
            )
            if (b.kind === 'same' || b.kind === 'fold') return split
              ? <SplitRow key={i} i={i} left={<span className="ws-diff-same">{b.text}</span>} right={<span className="ws-diff-same">{b.text}</span>} />
              : <div key={i} data-b={i} className="ws-diff-cell ws-diff-same">{b.text}</div>
            if (split) return (
              <SplitRow key={i} i={i}
                left={b.left ? <div className="ws-diff-del">{segs(b.left, 'del')}</div> : <div className="ws-diff-gap" />}
                right={b.right ? <div className="ws-diff-add">{segs(b.right, 'add')}</div> : <div className="ws-diff-gap" />} />
            )
            return (
              <div key={i} data-b={i} className="ws-diff-cell ws-diff-mix">
                {b.inline.map((w, j) => w.op === 0 ? <span key={j}>{w.text}</span>
                  : w.op < 0 ? <del key={j} className="ws-w-del">{w.text}</del> : <ins key={j} className="ws-w-add">{w.text}</ins>)}
              </div>
            )
          })}
        </div>
      </div>
      <div className="w-2.5 shrink-0 relative border-l border-line/60 ws-minimap" aria-label="where the changes are">
        {marks.map((m) => (
          <button key={m.i} onClick={() => jump(m.i)} aria-label="jump to a change" className="absolute left-0.5 right-0.5 rounded-sm"
            style={{ top: `${m.at * 100}%`, height: `max(3px, ${m.size * 100}%)` }} />
        ))}
      </div>
    </div>
  )
}

function SplitRow({ i, left, right }: { i: number; left: React.ReactNode; right: React.ReactNode }) {
  return <>
    <div data-b={i} className="ws-diff-cell border-r border-line/60">{left}</div>
    <div className="ws-diff-cell">{right}</div>
  </>
}
const segs = (s: Seg[], k: 'add' | 'del') => s.map((x, j) => (x.hit ? <span key={j} className={k === 'add' ? 'ws-w-add' : 'ws-w-del'}>{x.text}</span> : <span key={j}>{x.text}</span>))

function ImagePair({ art, from, to }: { art: Opened; from: string; to: string }) {
  const [blobs, setBlobs] = useState<[Blob, Blob] | null>(null)
  useEffect(() => { let live = true; Promise.all([contentOf(art, from), contentOf(art, to)]).then((b) => live && setBlobs(b)); return () => { live = false } }, [art, from, to])
  if (!blobs) return <Loading what="Comparing" />
  return (
    <div className="h-full grid grid-cols-2 gap-px bg-line/60">
      {blobs.map((u, i) => (
        <div key={i} className="ws-checker grid place-items-center p-5 overflow-auto">
          <BlobImg blob={u} alt={i ? 'the newer version' : 'the older version'} className="max-w-full max-h-full rounded-[6px]" />
        </div>
      ))}
    </div>
  )
}
