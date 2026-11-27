import { useEffect, useMemo, useState } from 'react'
import { I } from '../icons'
import { KIND_WORD } from '../artifacts/kinds'
import { ensureImported, loadLibrary, type Item } from '../library/api'
import { Badge } from '../library/FileCard'
import { since } from './parts'

/* ADD FROM THE LIBRARY: every file in the owner's conversations, searchable, several at once. A file not opened yet
   is imported into its own conversation first (one history per file, never a fork); the project pins its id. */

export default function FilePicker({ have, onClose, onAdd }: { have: string[]; onClose: () => void; onAdd: (ids: string[]) => void }) {
  const [items, setItems] = useState<Item[] | null>(null)
  const [q, setQ] = useState('')
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  useEffect(() => { loadLibrary().then(setItems).catch((e) => { setErr(String((e as Error).message)); setItems([]) }) }, [])
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    return (items ?? []).filter((i) => !(i.id && have.includes(i.id)) && (!s || i.name.toLowerCase().includes(s) || i.title.toLowerCase().includes(s)))
  }, [items, q, have])
  const flip = (k: string) => setSel((cur) => { const n = new Set(cur); if (n.has(k)) n.delete(k); else n.add(k); return n })
  const add = async () => {
    setBusy(true)
    try {
      const picked = (items ?? []).filter((i) => sel.has(i.key))
      onAdd(await Promise.all(picked.map(ensureImported)))
    } catch (e) { setErr(String((e as Error).message)); setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-50 ws-scrim grid place-items-start justify-center pt-[10vh] px-4" onMouseDown={onClose}
      onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}>
      <div role="dialog" aria-label="add files from the library" className="ws-menu w-full max-w-[600px] !rounded-[20px] flex flex-col max-h-[76vh]" onMouseDown={(e) => e.stopPropagation()}>
        <div className="px-5 pt-5 pb-3">
          <div className="ws-display text-[28px] leading-none text-ink">Add from the library</div>
          <label className="mt-4 flex items-center gap-2 h-10 rounded-[12px] px-3 border border-line focus-within:border-line-2 text-ink-mute">
            {I.search('w-[15px] h-[15px] shrink-0')}
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search files and conversations" aria-label="search files"
              className="flex-1 min-w-0 bg-transparent outline-none text-[13.5px] text-ink placeholder:text-ink-mute" />
          </label>
        </div>
        <ul className="flex-1 min-h-0 overflow-y-auto px-3 pb-2" role="listbox" aria-multiselectable>
          {items === null && <li className="px-2 py-3 text-[13px] text-ink-mute">Gathering every file…</li>}
          {items !== null && !shown.length && <li className="px-2 py-6 text-center text-[13px] text-ink-mute">{q ? 'Nothing matches.' : 'No other files yet. Upload one instead.'}</li>}
          {shown.map((it) => {
            const on = sel.has(it.key)
            return (
              <li key={it.key} role="option" aria-selected={on}>
                <button onClick={() => flip(it.key)} className="ws-row w-full flex items-center gap-3 rounded-[10px] px-2 py-2 text-left">
                  <span className="ws-check" data-on={on} aria-hidden>{on && <svg viewBox="0 0 24 24" className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={3}><path d="M5 12l5 5 9-10" /></svg>}</span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2"><span className="truncate text-[13.5px] text-ink">{it.name}</span><Badge it={it} /></span>
                    <span className="block truncate text-[11.5px] text-ink-mute mt-0.5">{KIND_WORD[it.kind]} · {since(it.ts)}{it.title ? ` · ${it.title}` : ''}</span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
        <div className="flex items-center gap-2 px-5 py-3.5 border-t border-line">
          {err ? <span className="text-[12.5px] text-bad truncate">{err}</span> : <span className="text-[12.5px] text-ink-mute">{sel.size ? `${sel.size} selected` : 'Pick one or more'}</span>}
          <button onClick={onClose} className="ws-btn ml-auto">Cancel</button>
          <button onClick={() => void add()} disabled={!sel.size || busy} className="ws-btn ws-btn-primary">{busy ? 'Adding…' : `Add${sel.size ? ` ${sel.size}` : ''}`}</button>
        </div>
      </div>
    </div>
  )
}
