import { useEffect, useMemo, useState } from 'react'
import { displayName, fmtAgo } from '../../api'
import AgentFace from '../../components/AgentFace'
import { I } from '../icons'
import { contentOf, type MediaItem, type Opened } from './api'
import type { OpenRequest } from './FileChip'
import { FILTER_OF, KindIcon, KIND_WORD, type Filter } from './kinds'
import { useObjectUrl } from './viewers/common'

/* THE MEDIA DRAWER: every file this conversation holds, newest first: what the owner uploaded and what the agents
   made, each badged with who. Images as a thumbnail grid, everything else as a list; filters All / Images / Docs /
   Data / Code. A click opens the file in the artifact panel. */

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' }, { id: 'images', label: 'Images' }, { id: 'docs', label: 'Docs' }, { id: 'data', label: 'Data' }, { id: 'code', label: 'Code' },
]

export default function MediaDrawer({ items, loading, onOpen, onClose, openKey }: {
  items: MediaItem[]
  loading: boolean
  onOpen: (r: OpenRequest) => void
  onClose: () => void
  openKey: string | null
}) {
  const [filter, setFilter] = useState<Filter>('all')
  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: items.length, images: 0, docs: 0, data: 0, code: 0 }
    for (const m of items) c[FILTER_OF[m.kind]]++
    return c
  }, [items])
  const shown = items.filter((m) => filter === 'all' || FILTER_OF[m.kind] === filter)
  const images = shown.filter((m) => m.kind === 'image')
  const rest = shown.filter((m) => m.kind !== 'image')
  const open = (m: MediaItem) => onOpen({ path: m.path, label: m.label ?? undefined, from: m.from })

  return (
    <aside className="ws-drawer h-full flex flex-col" aria-label="files in this conversation">
      <header className="h-12 shrink-0 flex items-center gap-2 pl-4 pr-2 border-b border-line">
        <span className="ws-display text-[21px] leading-none text-ink">Files</span>
        <span className="text-[12px] text-ink-mute tabular-nums">{items.length}</span>
        <button className="ws-icon ml-auto" onClick={onClose} aria-label="close the files" title="Close (Esc)">{I.x()}</button>
      </header>
      <div className="shrink-0 flex gap-1 px-3 py-2.5 overflow-x-auto ws-noscroll" role="radiogroup" aria-label="filter">
        {FILTERS.map((f) => (
          <button key={f.id} role="radio" aria-checked={filter === f.id} onClick={() => setFilter(f.id)} disabled={f.id !== 'all' && !counts[f.id]}
            className="ws-filter">{f.label}{f.id !== 'all' && counts[f.id] > 0 && <span className="tabular-nums opacity-60 ml-1">{counts[f.id]}</span>}</button>
        ))}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto px-3 pb-6">
        {loading && !items.length && <div className="px-1 py-3 text-[13px] text-ink-mute">Looking for files…</div>}
        {!loading && !items.length && (
          <div className="px-2 py-8 text-center">
            <div className="text-[13.5px] text-ink-dim">No files yet</div>
            <p className="mt-1 text-[12.5px] text-ink-mute leading-relaxed">Attach one to a message, or ask an agent for a chart, a sheet or a report. Every file in this conversation collects here.</p>
          </div>
        )}
        {images.length > 0 && (
          <div className="grid grid-cols-2 gap-2 mb-3">
            {images.map((m) => <Thumb key={m.path} m={m} on={openKey === m.path} onClick={() => open(m)} />)}
          </div>
        )}
        {rest.length > 0 && (
          <ul className="flex flex-col gap-0.5">
            {rest.map((m) => (
              <li key={m.path}>
                <button onClick={() => open(m)} aria-current={openKey === m.path} className="ws-row w-full rounded-[10px] px-2 py-2 flex items-center gap-2.5 text-left">
                  <span className="ws-chip-icon w-9 h-9 rounded-[10px] grid place-items-center shrink-0"><KindIcon kind={m.kind} className="w-[18px] h-[18px]" /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] text-ink">{m.name}</span>
                    <Source m={m} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  )
}

function Source({ m }: { m: MediaItem }) {
  const mine = m.from === 'owner'
  return (
    <span className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-ink-mute">
      {mine ? <span className="ws-badge">Uploaded</span> : <><AgentFace name={m.from} size={14} /><span className="text-ink-dim">{displayName(m.from)}</span></>}
      <span>· {KIND_WORD[m.kind]} · {fmtAgo(m.ts)}</span>
    </span>
  )
}

/* an image thumbnail: fetched with the owner header (no URL carries the key), via the same cached bytes the panel uses */
function Thumb({ m, on, onClick }: { m: MediaItem; on: boolean; onClick: () => void }) {
  const [blob, setBlob] = useState<Blob | null>(null)
  useEffect(() => {
    let live = true
    const plain: Opened = { id: `file:${m.path}`, thread: '', name: m.name, kind: m.kind, path_in_store: '', size: 0, head: '', versions: [], source: m.path, store: false }
    contentOf(plain).then((b) => live && setBlob(b)).catch(() => {})
    return () => { live = false }
  }, [m.path, m.name, m.kind])
  const url = useObjectUrl(blob)
  return (
    <button onClick={onClick} aria-current={on} className="ws-thumb group text-left" title={m.name}>
      <span className="block aspect-[4/3] rounded-[10px] overflow-hidden ws-checker relative">
        {url ? <img src={url} alt={m.name} className="w-full h-full object-cover" draggable={false} />
          : <span className="absolute inset-0 grid place-items-center text-ink-mute"><KindIcon kind="image" className="w-6 h-6" /></span>}
        <span className="absolute left-1.5 top-1.5">{m.from === 'owner' ? <span className="ws-badge ws-badge-solid">You</span> : <AgentFace name={m.from} size={18} />}</span>
      </span>
      <span className="block mt-1 px-0.5 truncate text-[12px] text-ink-dim group-hover:text-ink">{m.name}</span>
    </button>
  )
}
