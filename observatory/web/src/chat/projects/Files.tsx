import { useEffect, useMemo, useRef, useState } from 'react'
import { I } from '../icons'
import type { Item } from '../library/api'
import { FileRow, type Action } from '../library/FileCard'

/* THE FILES card: what the project knows. Each pinned artifact rides the first message of every new chat here as a
   [[file:]] the agents read (projects/context.ts). Add by upload (the button, or a drop anywhere on the card: the
   file is imported into the store as the project's own) or from the library (any conversation's file). A click
   opens it in the artifact panel with its versions; "Remove" unpins it (the file itself stays in the library). */

export default function Files({ items, loading, activeId, busy, onOpen, onUpload, onPick, onRemove }: {
  items: Item[]
  loading: boolean
  activeId: string | null
  busy: string                                  // an upload in flight: its words
  onOpen: (it: Item) => void
  onUpload: (files: File[]) => void
  onPick: () => void
  onRemove: (id: string) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [drop, setDrop] = useState(false)
  const [menu, setMenu] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!menu) return
    const off = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setMenu(false) }
    addEventListener('mousedown', off)
    return () => removeEventListener('mousedown', off)
  }, [menu])
  const actions = useMemo(() => (it: Item): Action[] => [{ label: 'Remove from project', icon: I.x('w-3.5 h-3.5'), run: () => onRemove(it.id!), danger: true }], [onRemove])

  return (
    <section className="ws-kcard ws-drop p-4" aria-label="files" data-drop={drop}
      onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setDrop(true) } }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDrop(false) }}
      onDrop={(e) => { e.preventDefault(); setDrop(false); const f = [...e.dataTransfer.files]; if (f.length) onUpload(f) }}>
      <div className="flex items-center gap-2 mb-1" ref={box}>
        <h2 className="text-[13px] font-medium text-ink">Files</h2>
        <span className="text-[12px] text-ink-mute tabular-nums">{items.length || ''}</span>
        <div className="relative ml-auto">
          <button className="ws-icon !w-auto px-2 gap-1 !flex items-center text-[12.5px]" onClick={() => setMenu((m) => !m)} aria-expanded={menu}>{I.plus('w-3.5 h-3.5')}Add</button>
          {menu && (
            <div className="ws-menu absolute right-0 top-[calc(100%+4px)] z-30 w-[220px] p-1" role="menu">
              <button role="menuitem" onClick={() => { setMenu(false); input.current?.click() }} className="ws-row w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-ink">{I.clip('w-3.5 h-3.5')}Upload from this device</button>
              <button role="menuitem" onClick={() => { setMenu(false); onPick() }} className="ws-row w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-ink">{I.folder('w-3.5 h-3.5')}From the library…</button>
            </div>
          )}
        </div>
        <input ref={input} type="file" multiple hidden onChange={(e) => { const f = [...(e.target.files ?? [])]; e.target.value = ''; if (f.length) onUpload(f) }} />
      </div>
      {busy && <div className="flex items-center gap-2 py-1.5 text-[12.5px] text-ink-dim"><span className="ws-live-dot" aria-hidden />{busy}</div>}
      {loading && !items.length && <div className="py-1.5 text-[12.5px] text-ink-mute">Reading the files…</div>}
      {!loading && !items.length && !busy && (
        <p className="text-[12.5px] text-ink-mute leading-relaxed py-1">
          Drop files here, or add them from any conversation. The team reads them at the start of every new chat in this project.
        </p>
      )}
      <div className="flex flex-col -mx-2">
        {items.map((it) => <FileRow key={it.key} it={it} where={false} compact active={it.id === activeId} actions={actions(it)} onOpen={() => onOpen(it)} />)}
      </div>
    </section>
  )
}
