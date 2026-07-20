import { useEffect, useMemo, useRef, useState } from 'react'
import { ActionIcon, Button, ScrollArea, Table, Tooltip } from '@mantine/core'
import { api, apiPost, apiSend } from '../api'
import type { Cell, DbList, DbSchema, QueryResult, SqlNode } from '../types'

const PAGE = 200

interface Tab {
  id: number
  title: string
  db: string
  sql: string
  result: QueryResult | null
  running: boolean
  count: number | null
  sortCol: number | null
  sortDir: 'asc' | 'desc'
  filePath?: string
}

let TAB_SEQ = 1
const newTab = (db: string, sql = '-- write SQL, ⌘/Ctrl+Enter to run\nSELECT * FROM steps ORDER BY id DESC\n', title = 'query'): Tab => ({
  id: TAB_SEQ++,
  title,
  db,
  sql,
  result: null,
  running: false,
  count: null,
  sortCol: null,
  sortDir: 'asc',
})

const cellStr = (v: Cell): string =>
  v === null || v === undefined ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v)

function toCSV(cols: string[], rows: Cell[][]): string {
  const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s)
  return [cols.map(esc).join(','), ...rows.map((r) => r.map((c) => esc(cellStr(c))).join(','))].join('\n')
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

/* ---- left: database → schema → table tree ---- */
function DbTree({
  dbs,
  onPick,
}: {
  dbs: string[]
  onPick: (db: string, schema: string, table: string) => void
}) {
  const [open, setOpen] = useState<string | null>(null)
  const [schemas, setSchemas] = useState<Record<string, DbSchema>>({})
  const toggle = async (db: string) => {
    if (open === db) return setOpen(null)
    setOpen(db)
    if (!schemas[db]) {
      try {
        const s = await api<DbSchema>(`/db/schema?database=${encodeURIComponent(db)}`)
        setSchemas((c) => ({ ...c, [db]: s }))
      } catch {
        /* ignore */
      }
    }
  }
  return (
    <div className="text-[12px]">
      {dbs.map((db) => (
        <div key={db}>
          <button
            onClick={() => toggle(db)}
            className="w-full flex items-center gap-1 px-2 py-1 rounded hover:bg-deck-3 text-ink-dim"
          >
            <span className="w-3 text-ink-mute">{open === db ? '▾' : '▸'}</span>
            <span className="truncate">🛢 {db}</span>
          </button>
          {open === db &&
            schemas[db] &&
            Object.entries(schemas[db].schemas).map(([sc, tables]) => (
              <div key={sc} className="ml-3">
                <div className="px-2 py-0.5 text-[10px] uppercase tracking-wide text-ink-mute">{sc}</div>
                {tables.map((t) => (
                  <button
                    key={t.name}
                    onClick={() => onPick(db, sc, t.name)}
                    className="w-full flex items-center gap-1 pl-4 pr-2 py-0.5 rounded hover:bg-deck-3 text-ink-mute hover:text-cyan-soft"
                  >
                    <span>{t.type === 'view' ? '◫' : '▤'}</span>
                    <span className="truncate">{t.name}</span>
                  </button>
                ))}
              </div>
            ))}
        </div>
      ))}
    </div>
  )
}

/* ---- right: saved .sql files under assets/ ---- */
function FileTree({
  nodes,
  onOpen,
  onDelete,
  depth = 0,
}: {
  nodes: SqlNode[]
  onOpen: (n: SqlNode) => void
  onDelete: (n: SqlNode) => void
  depth?: number
}) {
  return (
    <div>
      {nodes.map((n) => (
        <div key={n.path}>
          <div
            className="group flex items-center gap-1 px-1 py-0.5 rounded hover:bg-deck-3 text-[12px]"
            style={{ paddingLeft: 6 + depth * 12 }}
          >
            <button
              onClick={() => !n.dir && onOpen(n)}
              className={`flex items-center gap-1 flex-1 truncate ${n.dir ? 'text-ink-dim' : 'text-ink-mute hover:text-cyan-soft'}`}
            >
              <span>{n.dir ? '📁' : '≡'}</span>
              <span className="truncate">{n.name}</span>
            </button>
            <button
              onClick={() => onDelete(n)}
              className="opacity-0 group-hover:opacity-100 text-ink-mute hover:text-red-400 px-1"
              title="delete"
            >
              ×
            </button>
          </div>
          {n.dir && n.children && (
            <FileTree nodes={n.children} onOpen={onOpen} onDelete={onDelete} depth={depth + 1} />
          )}
        </div>
      ))}
    </div>
  )
}

export default function SqlView() {
  const [dbs, setDbs] = useState<string[]>([])
  const [tabs, setTabs] = useState<Tab[]>([])
  const [active, setActive] = useState(0)
  const [files, setFiles] = useState<SqlNode[]>([])
  const taRef = useRef<HTMLTextAreaElement>(null)

  // resizable / collapsible side panels (persisted)
  const [leftW, setLeftW] = useState(() => +(localStorage.getItem('sql_leftW') || 208))
  const [rightW, setRightW] = useState(() => +(localStorage.getItem('sql_rightW') || 208))
  const [leftHidden, setLeftHidden] = useState(() => localStorage.getItem('sql_leftHidden') === '1')
  const [rightHidden, setRightHidden] = useState(() => localStorage.getItem('sql_rightHidden') === '1')
  useEffect(() => { localStorage.setItem('sql_leftW', String(leftW)) }, [leftW])
  useEffect(() => { localStorage.setItem('sql_rightW', String(rightW)) }, [rightW])
  useEffect(() => { localStorage.setItem('sql_leftHidden', leftHidden ? '1' : '0') }, [leftHidden])
  useEffect(() => { localStorage.setItem('sql_rightHidden', rightHidden ? '1' : '0') }, [rightHidden])

  function startResize(side: 'left' | 'right', e: React.MouseEvent) {
    e.preventDefault()
    const x0 = e.clientX
    const w0 = side === 'left' ? leftW : rightW
    const clamp = (v: number) => Math.max(150, Math.min(560, v))
    const move = (m: MouseEvent) =>
      side === 'left' ? setLeftW(clamp(w0 + (m.clientX - x0))) : setRightW(clamp(w0 - (m.clientX - x0)))
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      document.body.style.cursor = ''
    }
    document.body.style.cursor = 'col-resize'
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  // editor ↔ results vertical split (persisted, collapsible)
  const [editorH, setEditorH] = useState(() => +(localStorage.getItem('sql_editorH') || 160))
  const [editorHidden, setEditorHidden] = useState(() => localStorage.getItem('sql_editorHidden') === '1')
  const [resultsHidden, setResultsHidden] = useState(() => localStorage.getItem('sql_resultsHidden') === '1')
  useEffect(() => { localStorage.setItem('sql_editorH', String(editorH)) }, [editorH])
  useEffect(() => { localStorage.setItem('sql_editorHidden', editorHidden ? '1' : '0') }, [editorHidden])
  useEffect(() => { localStorage.setItem('sql_resultsHidden', resultsHidden ? '1' : '0') }, [resultsHidden])

  function startVResize(e: React.MouseEvent) {
    e.preventDefault()
    const y0 = e.clientY
    const h0 = editorH
    const move = (m: MouseEvent) => setEditorH(Math.max(70, Math.min(560, h0 + (m.clientY - y0))))
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      document.body.style.cursor = ''
    }
    document.body.style.cursor = 'row-resize'
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  useEffect(() => {
    api<DbList>('/db/databases').then((d) => {
      setDbs(d.databases)
      setTabs([newTab(d.current)])
    })
    refreshFiles()
  }, [])

  const refreshFiles = () => api<SqlNode[]>('/sqlfiles').then(setFiles).catch(() => {})

  const tab = tabs[active]
  const patch = (i: number, p: Partial<Tab>) => setTabs((ts) => ts.map((t, k) => (k === i ? { ...t, ...p } : t)))

  async function runQuery(i: number, opts: { limit?: number | null; offset?: number; append?: boolean } = {}) {
    const t = tabs[i]
    if (!t || !t.sql.trim()) return
    patch(i, { running: true })
    try {
      const r = await apiPost<QueryResult>('/db/query', {
        database: t.db,
        sql: t.sql,
        limit: opts.limit === undefined ? PAGE : opts.limit,
        offset: opts.offset ?? 0,
      })
      if (opts.append && t.result?.rows && r.rows) {
        patch(i, { running: false, result: { ...r, rows: [...t.result.rows, ...r.rows], rowCount: (t.result.rows.length + r.rows.length) } })
      } else {
        patch(i, { running: false, result: r, count: null, sortCol: null })
      }
    } catch (e) {
      patch(i, { running: false, result: { error: String(e) } })
    }
  }

  function runInNewTab(limit: number | null) {
    const t = tabs[active]
    if (!t) return
    const nt = newTab(t.db, t.sql, `↳ ${limit ?? 'all'}`)
    setTabs((ts) => [...ts, nt])
    const idx = tabs.length
    setActive(idx)
    setTimeout(() => runQueryFor(nt, idx, limit), 0)
  }
  // run a specific tab object at index (used right after creating it)
  async function runQueryFor(t: Tab, i: number, limit: number | null) {
    patch(i, { running: true })
    try {
      const r = await apiPost<QueryResult>('/db/query', { database: t.db, sql: t.sql, limit })
      patch(i, { running: false, result: r, count: null, sortCol: null })
    } catch (e) {
      patch(i, { running: false, result: { error: String(e) } })
    }
  }

  async function getCount(i: number) {
    const t = tabs[i]
    try {
      const r = await apiPost<{ count?: number; error?: string }>('/db/count', { database: t.db, sql: t.sql })
      patch(i, { count: r.count ?? null })
    } catch {
      /* ignore */
    }
  }

  async function exportAll(i: number) {
    const t = tabs[i]
    try {
      const r = await apiPost<QueryResult>('/db/query', { database: t.db, sql: t.sql, limit: null })
      if (r.columns && r.rows) download(`${t.title}-all.csv`, toCSV(r.columns, r.rows))
    } catch {
      /* ignore */
    }
  }

  function onEditorKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    const mod = e.metaKey || e.ctrlKey
    if (mod && e.key === 'Enter') {
      e.preventDefault()
      if (e.shiftKey) runInNewTab(10)
      else runQuery(active, { limit: null })
      return
    }
    if (e.key === 'Tab') {
      e.preventDefault()
      const el = e.currentTarget
      const s = el.selectionStart
      const v = el.value
      const nv = v.slice(0, s) + '  ' + v.slice(el.selectionEnd)
      patch(active, { sql: nv })
      requestAnimationFrame(() => {
        el.selectionStart = el.selectionEnd = s + 2
      })
    }
  }

  function pickTable(db: string, schema: string, table: string) {
    const sql = `SELECT * FROM "${schema}"."${table}"`
    patch(active, { db, sql })
    setTimeout(() => runQuery(active, { limit: PAGE }), 0)
  }

  async function openFile(n: SqlNode) {
    const r = await api<{ content: string }>(`/sqlfile?path=${encodeURIComponent(n.path)}`)
    const nt = newTab(tab?.db ?? dbs[0] ?? 'astryx', r.content, n.name)
    nt.filePath = n.path
    setTabs((ts) => [...ts, nt])
    setActive(tabs.length)
  }

  async function saveTab() {
    const t = tabs[active]
    if (!t) return
    let path = t.filePath
    if (!path) {
      const name = prompt('save as (e.g. reports/daily.sql):', `${t.title}.sql`)
      if (!name) return
      path = name.endsWith('.sql') ? name : `${name}.sql`
    }
    await apiSend('PUT', '/sqlfile', { path, content: t.sql })
    patch(active, { filePath: path, title: path.split('/').pop()! })
    refreshFiles()
  }

  async function newFolder() {
    const name = prompt('new folder (e.g. reports):')
    if (name) {
      await apiSend('POST', '/sqlfile', { path: name, kind: 'dir' })
      refreshFiles()
    }
  }

  async function deleteFile(n: SqlNode) {
    if (!confirm(`delete ${n.path}?`)) return
    await apiSend('DELETE', `/sqlfile?path=${encodeURIComponent(n.path)}`)
    refreshFiles()
  }

  // client-side sort of the loaded page
  const view = useMemo(() => {
    const r = tab?.result
    if (!r?.rows || tab.sortCol == null) return r?.rows ?? []
    const c = tab.sortCol
    const dir = tab.sortDir === 'asc' ? 1 : -1
    return [...r.rows].sort((a, b) => {
      const x = a[c]
      const y = b[c]
      if (x === null) return 1
      if (y === null) return -1
      if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir
      return String(x).localeCompare(String(y)) * dir
    })
  }, [tab?.result, tab?.sortCol, tab?.sortDir])

  function sortBy(c: number) {
    if (!tab) return
    if (tab.sortCol === c) patch(active, { sortDir: tab.sortDir === 'asc' ? 'desc' : 'asc' })
    else patch(active, { sortCol: c, sortDir: 'asc' })
  }

  if (!tab) return <div className="p-4 text-sm text-ink-mute">connecting…</div>
  const r = tab.result

  return (
    <div className="h-full flex">
      {/* left: databases */}
      {leftHidden ? (
        <button
          onClick={() => setLeftHidden(false)}
          className="w-6 shrink-0 border-r border-line flex flex-col items-center pt-2 gap-2 text-ink-mute hover:text-cyan-soft"
          title="show databases"
        >
          <span>▸</span>
          <span className="text-[10px] tracking-wide" style={{ writingMode: 'vertical-rl' }}>
            DATABASES
          </span>
        </button>
      ) : (
        <>
          <div className="shrink-0 border-r border-line flex flex-col" style={{ width: leftW }}>
            <div className="flex items-center justify-between px-3 py-2 border-b border-line">
              <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-dim">Databases</span>
              <button onClick={() => setLeftHidden(true)} className="text-ink-mute hover:text-cyan-soft text-sm" title="hide">
                ‹
              </button>
            </div>
            <ScrollArea className="flex-1">
              <div className="py-1">
                <DbTree dbs={dbs} onPick={pickTable} />
              </div>
            </ScrollArea>
          </div>
          <div
            onMouseDown={(e) => startResize('left', e)}
            className="w-1 shrink-0 cursor-col-resize hover:bg-cyan-soft/40 bg-line/40"
          />
        </>
      )}

      {/* middle: tabs + editor + results */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* query tabs */}
        <div className="flex items-center gap-1 px-2 pt-1.5 border-b border-line overflow-x-auto">
          {tabs.map((t, i) => (
            <div
              key={t.id}
              onClick={() => setActive(i)}
              className={`group flex items-center gap-1 px-2.5 py-1 rounded-t text-[12px] cursor-pointer whitespace-nowrap ${
                i === active ? 'bg-deck-3 text-cyan-soft' : 'text-ink-mute hover:text-ink'
              }`}
            >
              <span className="truncate max-w-[120px]">{t.filePath ? '≡ ' : ''}{t.title}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setTabs((ts) => ts.filter((_, k) => k !== i))
                  setActive((a) => Math.max(0, a >= i ? a - 1 : a))
                }}
                className="opacity-40 group-hover:opacity-100 hover:text-red-400"
              >
                ×
              </button>
            </div>
          ))}
          <button
            onClick={() => {
              setTabs((ts) => [...ts, newTab(tab.db)])
              setActive(tabs.length)
            }}
            className="px-2 py-1 text-ink-mute hover:text-cyan-soft text-sm"
          >
            +
          </button>
        </div>

        {/* editor region — resizable height, hideable */}
        {editorHidden ? (
          <button
            onClick={() => setEditorHidden(false)}
            className="shrink-0 h-6 border-b border-line text-[10px] uppercase tracking-[0.2em] text-ink-mute hover:text-cyan-soft"
          >
            ▾ show editor
          </button>
        ) : (
          <div
            className="relative border-b border-line flex flex-col min-h-0"
            style={resultsHidden ? { flex: 1 } : { height: editorH }}
          >
            <textarea
              ref={taRef}
              value={tab.sql}
              onChange={(e) => patch(active, { sql: e.target.value })}
              onKeyDown={onEditorKey}
              spellCheck={false}
              className="w-full flex-1 resize-none bg-deck px-3 py-2 font-mono text-[13px] text-ink outline-none leading-relaxed"
              style={{ tabSize: 2 }}
            />
          </div>
        )}

        {/* action bar */}
        <div className="flex items-center gap-2 px-3 py-1.5 border-b border-line text-[12px]">
          <Button size="compact-xs" color="cyan" variant="filled" loading={tab.running} onClick={() => runQuery(active, { limit: null })}>
            ▶ Run
          </Button>
          <Tooltip label="⌘/Ctrl+Shift+Enter" openDelay={400}>
            <Button size="compact-xs" variant="light" color="cyan" onClick={() => runInNewTab(10)}>
              ▶ Run 10 ↗
            </Button>
          </Tooltip>
          <select
            value={tab.db}
            onChange={(e) => patch(active, { db: e.target.value })}
            className="bg-deck-3 text-ink-dim text-[11px] rounded px-1.5 py-1 border border-line outline-none"
          >
            {dbs.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <div className="ml-auto flex items-center gap-1.5 text-[11px] text-ink-mute font-mono">
            {r && !r.error && (
              <>
                <span>{r.command}</span>
                <span>· {r.rowCount ?? 0} rows</span>
                <span>· {r.elapsed_ms}ms</span>
                {tab.count != null && <span className="text-cyan-soft">· total {tab.count}</span>}
              </>
            )}
          </div>
        </div>

        {/* divider: editor ↔ results (resize + collapse either half) */}
        {!editorHidden && !resultsHidden && (
          <div
            onMouseDown={startVResize}
            className="group relative h-1.5 shrink-0 cursor-row-resize bg-line/40 hover:bg-cyan-soft/40 flex items-center"
          >
            <div className="absolute right-3 flex gap-3" onMouseDown={(e) => e.stopPropagation()}>
              <button onClick={() => setEditorHidden(true)} title="hide editor" className="text-[10px] text-ink-mute hover:text-cyan-soft">
                ▲
              </button>
              <button onClick={() => setResultsHidden(true)} title="hide results" className="text-[10px] text-ink-mute hover:text-cyan-soft">
                ▼
              </button>
            </div>
          </div>
        )}

        {resultsHidden ? (
          <button
            onClick={() => setResultsHidden(false)}
            className="shrink-0 h-6 border-t border-line text-[10px] uppercase tracking-[0.2em] text-ink-mute hover:text-cyan-soft"
          >
            ▴ show results
          </button>
        ) : (
          <>
        {/* results toolbar */}
        {r && !r.error && r.columns && (
          <div className="flex items-center gap-1 px-3 py-1 border-b border-line">
            <ActionIcon.Group>
              <Button size="compact-xs" variant="subtle" color="gray" onClick={() => getCount(active)}>
                Σ count
              </Button>
              <Button size="compact-xs" variant="subtle" color="gray" onClick={() => runQuery(active, { limit: PAGE, offset: r.rows?.length ?? 0, append: true })}>
                ↓ fetch more
              </Button>
              <Button size="compact-xs" variant="subtle" color="gray" onClick={() => download(`${tab.title}.csv`, toCSV(r.columns!, r.rows ?? []))}>
                ⤓ export
              </Button>
              <Button size="compact-xs" variant="subtle" color="gray" onClick={() => exportAll(active)}>
                ⤓ export all
              </Button>
            </ActionIcon.Group>
          </div>
        )}

        {/* results grid */}
        <div className="flex-1 min-h-0">
          {r?.error ? (
            <div className="p-3 font-mono text-[12px] text-red-400 whitespace-pre-wrap">{r.error}</div>
          ) : r?.columns && r.columns.length ? (
            <ScrollArea className="h-full">
              <Table stickyHeader verticalSpacing={3} horizontalSpacing="sm" className="text-[12px]" striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th style={{ width: 42, color: '#5b6689' }}>#</Table.Th>
                    {r.columns.map((c, i) => (
                      <Table.Th key={i} onClick={() => sortBy(i)} style={{ cursor: 'pointer', whiteSpace: 'nowrap' }}>
                        <span className="text-cyan-soft">{c}</span>
                        {tab.sortCol === i && <span className="text-ink-mute"> {tab.sortDir === 'asc' ? '▲' : '▼'}</span>}
                      </Table.Th>
                    ))}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {view.map((row, ri) => (
                    <Table.Tr key={ri}>
                      <Table.Td className="font-mono text-ink-mute">{ri + 1}</Table.Td>
                      {row.map((cell, ci) => (
                        <Table.Td key={ci} className="font-mono" style={{ maxWidth: 380, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {cell === null ? <span className="text-ink-mute/50 italic">NULL</span> : <span className="text-ink-dim">{cellStr(cell)}</span>}
                        </Table.Td>
                      ))}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          ) : (
            <div className="p-3 text-[12px] text-ink-mute">
              {r ? `${r.command} — ${r.rowCount ?? 0} rows` : 'run a query — ⌘/Ctrl+Enter'}
            </div>
          )}
        </div>
          </>
        )}
      </div>

      {/* right: saved SQL files */}
      {rightHidden ? (
        <button
          onClick={() => setRightHidden(false)}
          className="w-6 shrink-0 border-l border-line flex flex-col items-center pt-2 gap-2 text-ink-mute hover:text-cyan-soft"
          title="show SQL files"
        >
          <span>◂</span>
          <span className="text-[10px] tracking-wide" style={{ writingMode: 'vertical-rl' }}>
            SQL FILES
          </span>
        </button>
      ) : (
        <>
          <div
            onMouseDown={(e) => startResize('right', e)}
            className="w-1 shrink-0 cursor-col-resize hover:bg-cyan-soft/40 bg-line/40"
          />
          <div className="shrink-0 border-l border-line flex flex-col" style={{ width: rightW }}>
            <div className="flex items-center justify-between px-3 py-2 border-b border-line">
              <div className="flex items-center gap-1">
                <button onClick={() => setRightHidden(true)} className="text-ink-mute hover:text-cyan-soft text-sm" title="hide">
                  ›
                </button>
                <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-dim">SQL files</span>
              </div>
              <div className="flex gap-1">
                <Tooltip label="save current tab" openDelay={400}>
                  <button onClick={saveTab} className="text-ink-mute hover:text-cyan-soft text-sm">
                    ⤓
                  </button>
                </Tooltip>
                <Tooltip label="new folder" openDelay={400}>
                  <button onClick={newFolder} className="text-ink-mute hover:text-cyan-soft text-sm">
                    ＋
                  </button>
                </Tooltip>
              </div>
            </div>
            <ScrollArea className="flex-1">
              <div className="py-1 pr-1">
                {files.length ? (
                  <FileTree nodes={files} onOpen={openFile} onDelete={deleteFile} />
                ) : (
                  <div className="px-3 py-2 text-[11px] text-ink-mute">no saved queries — write one and hit ⤓</div>
                )}
              </div>
            </ScrollArea>
          </div>
        </>
      )}
    </div>
  )
}
