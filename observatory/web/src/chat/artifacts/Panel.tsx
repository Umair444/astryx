import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { displayName } from '../../api'
import AgentFace from '../../components/AgentFace'
import { download, upload, type Uploaded } from '../model'
import { I } from '../icons'
import { contentOf, EDITABLE, extOf, isProse, restoreArtifact, saveArtifact, textOf, type Opened } from './api'
import { bytes, KindIcon, KIND_WORD } from './kinds'
import type { PanelState, Tab } from './usePanel'
import ArtifactView from './viewers'
import { Loading } from './viewers/common'
import VersionMenu, { ago, who } from './versions/VersionMenu'
import { comparable } from './versions/extract'
import type { AnnotateCtx } from './annotate/types'
import { A } from './annotate/icons'

/* THE ARTIFACT PANEL (DESIGN.md layout): the thing being made, beside the conversation about it. Tabs for every file
   opened in this conversation; for the active one, its versions (git, by author), Diff, Edit (text kinds: a new
   version by the owner), Download, fullscreen (⌘⇧F) and Close. Wide (≥1200) it sits in the row, resizable on a 1px
   seam (3px on hover; the width is remembered); narrower it is a sheet over the chat; on a phone, the whole screen.
   An old version is read-only with "Restore as new version": history is never rewritten.
   ANNOTATE (iteration 4): any text-bearing kind takes highlights, comments, asks and suggestions; the margin opens in
   the panel (which widens by its 280px while it is open), or as a sheet where the panel is narrow. */

const DiffView = lazy(() => import('./versions/DiffView'))
const Annotator = lazy(() => import('./annotate/Annotator'))
const ANNOTATABLE = ['text', 'code', 'table', 'pdf', 'docx', 'sheet']
const MARGIN = 280
const W_KEY = 'ws.artifact.w'
const MIN = 480

type View = { rev: string | null; diff: { from: string; to: string } | null; edit: { draft: string; base: string; message: string } | null; note: string; ann: boolean | null }
const FRESH: View = { rev: null, diff: null, edit: null, note: '', ann: null }

export type Layout = 'inline' | 'sheet' | 'full'

export default function Panel({ panel, layout, onAttach, onDirty, annotate }: {
  panel: PanelState
  layout: Layout
  onAttach: (u: Uploaded) => void
  onDirty?: (dirty: boolean) => void
  annotate?: AnnotateCtx
}) {
  const { tabs, active, close, closeAll, activate, update } = panel
  const tab = tabs.find((t) => t.key === active) ?? tabs[0]
  const [views, setViews] = useState<Record<string, View>>({})
  const view = (tab && views[tab.key]) || FRESH
  const setView = useCallback((key: string, f: (v: View) => View) => setViews((m) => ({ ...m, [key]: f(m[key] ?? FRESH) })), [])
  const [full, setFull] = useState(false)
  const dirty = (k: string) => { const e = views[k]?.edit; return !!e && e.draft !== e.base }
  const anyDirty = tabs.some((t) => dirty(t.key))
  useEffect(() => { onDirty?.(anyDirty) }, [anyDirty, onDirty])

  // ── width: a remembered px width, clamped to [480, 60% of the row] ───────────────────────────────────────────
  const self = useRef<HTMLDivElement>(null)
  const [w, setW] = useState<number | null>(() => { try { return Number(localStorage.getItem(W_KEY)) || null } catch { return null } })
  const [row, setRow] = useState(0)
  useLayoutEffect(() => {
    const parent = self.current?.parentElement
    if (!parent || layout !== 'inline') return
    const ro = new ResizeObserver(() => setRow(parent.clientWidth))
    ro.observe(parent)
    return () => ro.disconnect()
  }, [layout])
  // the margin widens the panel by its own width, never squeezing the chat under 420px
  const extra = tab?.art && views[tab.key]?.ann && !views[tab.key]?.edit && !views[tab.key]?.diff ? MARGIN : 0
  const clamp = (x: number) => Math.round(Math.max(MIN, Math.min(row * 0.6, x)))
  const width = layout === 'inline' && row ? Math.round(Math.max(MIN, Math.min(clamp(w ?? row * 0.5) + extra, row - 420))) : undefined
  const drag = (e: React.PointerEvent) => {
    e.preventDefault()
    const right = self.current!.getBoundingClientRect().right
    const el = e.currentTarget as HTMLElement
    el.setPointerCapture(e.pointerId)
    document.body.style.cursor = 'col-resize'
    const move = (ev: PointerEvent) => setW(clamp(right - ev.clientX - extra))
    const up = () => {
      el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up)
      document.body.style.cursor = ''
      setW((x) => { try { if (x) localStorage.setItem(W_KEY, String(x)) } catch { /* private mode */ } return x })
    }
    el.addEventListener('pointermove', move); el.addEventListener('pointerup', up)
  }

  // ── keys: ⌘⇧F fullscreen, ⌘S save an edit, Esc leaves fullscreen first ──────────────────────────────────────
  const saveRef = useRef<() => void>(() => {})
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.shiftKey && e.key.toLowerCase() === 'f') { e.preventDefault(); setFull((f) => !f) }
      else if (mod && e.key.toLowerCase() === 's' && view.edit) { e.preventDefault(); saveRef.current() }
      else if (e.key === 'Escape' && full && !document.querySelector('[data-ann-open]')) { e.preventDefault(); e.stopImmediatePropagation(); setFull(false) }
    }
    addEventListener('keydown', k, true)
    return () => removeEventListener('keydown', k, true)
  }, [full, view.edit])

  const closeTab = (k: string) => { if (dirty(k) && !confirm('Discard your unsaved changes?')) return; close(k) }
  const closePanel = () => { if (anyDirty && !confirm('Discard your unsaved changes?')) return; setFull(false); closeAll() }

  if (!tab) return null
  const art = tab.art
  const fullscreen = full || layout === 'full'
  const shell = fullscreen
    ? 'fixed inset-0 z-50 bg-[var(--t-bg)]'
    : layout === 'sheet'
      ? `fixed right-0 top-0 bottom-0 z-40 ${extra ? 'w-[min(1040px,94vw)]' : 'w-[min(760px,94vw)]'} shadow-[-24px_0_60px_-30px_rgba(0,0,0,.45)] bg-[var(--t-bg)] border-l border-line`
      : 'relative shrink-0 border-l border-line bg-[color-mix(in_srgb,var(--t-bg)_70%,var(--t-bg2))]'

  return (
    <>
      {layout === 'sheet' && !fullscreen && <div className="fixed inset-0 z-30 ws-scrim" onClick={closePanel} aria-hidden />}
      <section ref={self} className={`ws-artifact flex flex-col min-w-0 ${shell}`} style={layout === 'inline' && !fullscreen ? { width } : undefined}
        aria-label="artifact panel">
        {layout === 'inline' && !fullscreen && (
          <div className="ws-seam" onPointerDown={drag} onDoubleClick={() => { setW(null); try { localStorage.removeItem(W_KEY) } catch { /* */ } }}
            role="separator" aria-orientation="vertical" aria-label="resize the panel" title="Drag to resize · double-click to reset" />
        )}

        {/* the tabs, and the panel's own controls */}
        <div className="h-12 shrink-0 flex items-end gap-1 pl-2 pr-2 border-b border-line">
          <div className="flex-1 min-w-0 flex items-end gap-0.5 overflow-x-auto ws-noscroll" role="tablist" aria-label="open files">
            {tabs.map((t) => (
              <TabButton key={t.key} t={t} active={t.key === tab.key} dirty={dirty(t.key)} onClick={() => activate(t.key)} onClose={() => closeTab(t.key)} />
            ))}
          </div>
          <div className="flex items-center gap-0.5 self-center">
            <button className="ws-icon" onClick={() => setFull((f) => !f)} aria-pressed={full} title={full ? 'Leave full screen (Esc)' : 'Open full (⌘⇧F)'} aria-label="full screen">
              {full ? <Shrink /> : <Expand />}
            </button>
            <button className="ws-icon" onClick={closePanel} title="Close the panel" aria-label="close the panel">{I.x()}</button>
          </div>
        </div>

        {tab.err ? <div className="flex-1 grid place-items-center p-8 text-[13px] text-ink-dim text-center">{tab.err}</div>
          : !art ? <div className="flex-1"><Loading /></div>
          : <Body key={tab.key} art={art} view={view} setView={(f) => setView(tab.key, f)} wide={layout !== 'full' && (fullscreen || (width ?? 0) >= 640)}
              onSaved={(a) => update(tab.key, a)} onAttach={onAttach} saveRef={saveRef} from={tab.req.from} roomy={layout !== 'full'}
              annotate={annotate && annotate.focus?.name === art.name ? annotate : annotate && { ...annotate, focus: null }} />}
      </section>
    </>
  )
}

function TabButton({ t, active, dirty, onClick, onClose }: { t: Tab; active: boolean; dirty: boolean; onClick: () => void; onClose: () => void }) {
  const name = t.art?.name ?? t.req.label ?? t.req.path.split('/').pop()!
  const kind = t.art?.kind ?? 'binary'
  return (
    <div role="tab" aria-selected={active} className={`ws-tab group ${active ? 'is-on' : ''}`} onAuxClick={(e) => { if (e.button === 1) onClose() }}>
      <button onClick={onClick} className="flex items-center gap-2 min-w-0 h-full pl-3 pr-1" title={name}>
        <KindIcon kind={kind} className="w-[15px] h-[15px] shrink-0 opacity-80" />
        <span className="truncate max-w-[180px]">{name}</span>
      </button>
      <button onClick={onClose} aria-label={`close ${name}`} title={dirty ? 'Unsaved changes' : 'Close'} className="ws-tab-x">
        {dirty ? <span className="w-2 h-2 rounded-full bg-[var(--t-accent)] group-hover:hidden" aria-hidden /> : null}
        <span className={dirty ? 'hidden group-hover:block' : ''}>{I.x('w-3.5 h-3.5')}</span>
      </button>
    </div>
  )
}

/* the active artifact: its toolbar, then the version (or the diff, or the editor) */
function Body({ art, view, setView, wide, onSaved, onAttach, saveRef, from, annotate, roomy }: {
  art: Opened
  view: View
  setView: (f: (v: View) => View) => void
  wide: boolean
  onSaved: (a: Opened) => void
  onAttach: (u: Uploaded) => void
  saveRef: React.MutableRefObject<() => void>
  from: string
  annotate?: AnnotateCtx
  roomy: boolean
}) {
  const head = art.versions[0]
  const rev = view.rev ?? art.head ?? ''
  const shown = art.versions.find((v) => v.rev === rev) ?? head
  const old = !!head && !!shown && shown.rev !== head.rev
  const editable = EDITABLE.includes(art.kind)
  const [busy, setBusy] = useState(false)
  const note = useCallback((s: string) => setView((v) => ({ ...v, note: s })), [setView])
  const [count, setCount] = useState(0)
  const setAnn = useCallback((o: boolean) => setView((v) => ({ ...v, ann: o })), [setView])
  // a quoted ask in the chat opens the margin even before the layer has loaded
  useEffect(() => { if (annotate?.focus) setView((v) => ({ ...v, ann: true, rev: null, diff: null })) }, [annotate?.focus?.n]) // eslint-disable-line react-hooks/exhaustive-deps

  async function startEdit() {
    const text = await textOf(art, art.store ? head?.rev : undefined)
    setView((v) => ({ ...v, diff: null, rev: null, edit: { draft: text, base: text, message: '' }, note: '' }))
  }
  async function save() {
    const e = view.edit
    if (!e || busy) return
    if (e.draft === e.base) { note('No changes'); return }
    setBusy(true)
    try {
      if (art.store) {
        const a = await saveArtifact(art.id, e.draft, e.message.trim() || undefined)
        onSaved({ ...art, ...a, kind: art.kind })
        setView((v) => ({ ...FRESH, ann: v.ann, note: `Saved as v${a.versions[0]?.n ?? ''}` }))
      } else {   // no store: the edit becomes a new upload, attached to the next message (the old file is never changed)
        const u = await upload(new Blob([e.draft]), art.name.replace(/(\.[^.]+)?$/, (x) => `-edited${x || '.txt'}`))
        onAttach(u)
        setView(() => ({ ...FRESH, note: 'Saved as a new file, attached to your next message' }))
      }
    } catch (err) {
      const s = (err as { status?: number }).status
      note(s === 409 ? 'No changes' : `Not saved: ${(err as Error).message}`)
    } finally { setBusy(false) }
  }
  saveRef.current = () => void save()
  async function restore() {
    if (!shown || busy) return
    setBusy(true)
    try {
      const a = await restoreArtifact(art.id, shown.rev)
      onSaved({ ...art, ...a, kind: art.kind })
      setView((v) => ({ ...FRESH, ann: v.ann, note: `Restored v${shown.n} as v${a.versions[0]?.n ?? ''}` }))
    } catch (err) {
      note((err as { status?: number }).status === 409 ? 'No changes: the latest version already holds this' : `Not restored: ${(err as Error).message}`)
    } finally { setBusy(false) }
  }
  const toggleDiff = () => setView((v) => {
    if (v.diff) return { ...v, diff: null }
    const to = v.rev ?? art.head
    const i = art.versions.findIndex((x) => x.rev === to)
    return { ...v, edit: null, diff: { from: art.versions[i + 1]?.rev ?? to, to } }
  })
  const dl = async () => download(await contentOf(art, art.store ? rev : undefined), art.name)

  const canDiff = art.store && art.versions.length > 1 && (comparable(art) || art.kind === 'image')
  const e = view.edit
  const dirty = !!e && e.draft !== e.base
  const madeBy = art.versions.at(-1)?.author ?? from
  const annotatable = art.store && ANNOTATABLE.includes(art.kind)

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* toolbar */}
      <div className="shrink-0 min-h-11 flex items-center gap-1.5 flex-wrap px-3 py-1.5 border-b border-line/70 text-[12.5px]">
        {!e && <span className="inline-flex items-center gap-1.5 text-ink-mute min-w-0 mr-1" title={`${KIND_WORD[art.kind]} from ${who(madeBy)}`}>
          <AgentFace name={madeBy} size={18} />
          <span className="truncate max-w-[200px] max-sm:hidden">{madeBy === 'owner' ? 'Uploaded by you' : `From ${displayName(madeBy)}`}{art.size ? ` · ${bytes(art.size)}` : ''}</span>
        </span>}
        <div className="ml-auto flex items-center gap-1">
          {e ? <>
            <span className={`inline-flex items-center gap-1.5 mr-1 ${dirty ? 'text-ink-dim' : 'text-ink-mute'}`} role="status">
              {dirty && <span className="w-1.5 h-1.5 rounded-full bg-[var(--t-accent)]" aria-hidden />}{dirty ? 'Unsaved changes' : 'Editing'}
            </span>
            {art.store && <input value={e.message} onChange={(x) => setView((v) => ({ ...v, edit: v.edit && { ...v.edit, message: x.target.value } }))}
              placeholder="What changed? (optional)" maxLength={200} aria-label="what changed"
              className="ws-input h-8 w-[190px] max-md:hidden" onKeyDown={(x) => { if (x.key === 'Enter') void save() }} />}
            <button className="ws-btn !h-8" onClick={() => { if (!dirty || confirm('Discard your changes?')) setView((v) => ({ ...v, edit: null })) }}>Cancel</button>
            <button className="ws-btn ws-btn-primary !h-8" disabled={!dirty || busy} onClick={() => void save()} title="Save (⌘S)">
              {busy ? 'Saving…' : art.store ? 'Save version' : 'Save copy'}
            </button>
          </> : <>
            {art.store && art.versions.length > 0 && !view.diff && (
              <VersionMenu versions={art.versions} current={rev} onPick={(r) => setView((v) => ({ ...v, rev: r === art.head ? null : r, note: '' }))} />
            )}
            {canDiff && <button className="ws-tool" aria-pressed={!!view.diff} onClick={toggleDiff} title="Compare versions">{DiffIcon}<span>Diff</span></button>}
            {annotatable && !view.diff && (
              <button className="ws-tool" aria-pressed={!!view.ann} onClick={() => setAnn(!view.ann)} title={view.ann ? 'Hide the notes' : 'Annotate: highlight, comment, ask an agent'}>
                {A.margin()}<span className="max-sm:hidden">Annotate</span>
                {count > 0 && <span className="ax-count" aria-label={`${count} notes`}>{count}</span>}
              </button>
            )}
            {editable && !old && !view.diff && <button className="ws-tool" onClick={() => void startEdit()} title="Edit (saves a new version)">{I.edit('w-[15px] h-[15px]')}<span>Edit</span></button>}
            <button className="ws-tool" onClick={() => void dl()} title="Download this version" aria-label="download">{DownIcon}</button>
          </>}
        </div>
      </div>

      {old && !view.diff && !e && shown && (
        <div className="shrink-0 flex items-center gap-3 flex-wrap px-4 py-2 text-[12.5px] ws-oldbar">
          <span className="text-ink-dim">Viewing <b className="text-ink font-semibold">v{shown.n}</b> by {who(shown.author)}, {ago(shown.ts)}. Read-only.</span>
          <span className="ml-auto flex gap-1.5">
            <button className="ws-btn !h-7 !text-[12px]" onClick={() => setView((v) => ({ ...v, rev: null }))}>Back to latest</button>
            <button className="ws-btn ws-btn-primary !h-7 !text-[12px]" disabled={busy} onClick={() => void restore()}>Restore as new version</button>
          </span>
        </div>
      )}
      {view.note && <div className="shrink-0 px-4 py-1.5 text-[12px] text-ink-dim border-b border-line/60 cursor-pointer" role="status" onClick={() => note('')}>{view.note}</div>}

      <div className="flex-1 min-h-0 relative">
        {view.diff ? (
          <Suspense fallback={<Loading what="Comparing" />}>
            <DiffView art={art} from={view.diff.from} to={view.diff.to} wide={wide}
              onFrom={(r) => setView((v) => ({ ...v, diff: v.diff && { ...v.diff, from: r } }))}
              onTo={(r) => setView((v) => ({ ...v, diff: v.diff && { ...v.diff, to: r } }))} />
          </Suspense>
        ) : e ? (
          <Editor value={e.draft} prose={art.kind === 'text' && isProse(art.name) || extOf(art.name) === 'md'}
            onChange={(t) => setView((v) => ({ ...v, edit: v.edit && { ...v.edit, draft: t } }))} />
        ) : annotatable ? (
          <Suspense fallback={<Loading />}>
            <Annotator art={art} version={shown?.n ?? null} canSuggest={editable && !old} ctx={annotate ?? null}
              open={view.ann} setOpen={setAnn} onCount={setCount} onSaved={onSaved} note={note} roomy={roomy}>
              <ArtifactView art={art} rev={art.store ? rev : undefined} />
            </Annotator>
          </Suspense>
        ) : <ArtifactView art={art} rev={art.store ? rev : undefined} />}
      </div>
    </div>
  )
}

/* the editor: a plain, good textarea; serif at the reading measure for prose, mono for code and data */
function Editor({ value, prose, onChange }: { value: string; prose: boolean; onChange: (t: string) => void }) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { ref.current?.focus({ preventScroll: true }) }, [])
  return (
    <div className="h-full overflow-hidden flex">
      <textarea ref={ref} value={value} onChange={(e) => onChange(e.target.value)} spellCheck={prose} aria-label="edit the file"
        onKeyDown={(e) => {
          if (e.key === 'Tab' && !prose) {          // a tab in code is indentation, not focus travel
            e.preventDefault()
            const t = e.currentTarget, s = t.selectionStart, end = t.selectionEnd
            onChange(value.slice(0, s) + '  ' + value.slice(end))
            requestAnimationFrame(() => { t.selectionStart = t.selectionEnd = s + 2 })
          }
        }}
        className={`ws-editor flex-1 resize-none outline-none bg-transparent ${prose ? 'ws-editor-prose' : 'ws-editor-code'}`} />
    </div>
  )
}

const DiffIcon = <svg viewBox="0 0 24 24" className="w-[15px] h-[15px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden><path d="M6 4v10M1.5 9h9M14 19h8" /><circle cx="18" cy="8" r="3.5" /></svg>
const DownIcon = <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M12 4v11M7 10.5l5 5 5-5M5 20h14" /></svg>
const Expand = () => <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" /></svg>
const Shrink = () => <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M20 10h-6V4M4 14h6v6M14 10l7-7M10 14l-7 7" /></svg>
