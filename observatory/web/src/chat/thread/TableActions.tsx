import { useContext, useEffect, useLayoutEffect, useMemo, useState } from 'react'
import type { Msg } from '../../types'
import { tableName, tablesOf } from '../tables/mdtable'
import '../tables/tables.css'
import { TurnActionsCtx } from './TurnActions'

/* A table in an agent's answer, data-forward (iteration 9): on hover (or focus; always on touch) a small pill at its
   top-right corner — Chart (the table becomes a CSV artifact in the store, by that agent, and opens in the panel AS
   its chart), CSV, Excel. The pills float over the rendered prose (Prose's HTML is never rewritten); the nth pill
   belongs to the nth <table>, which is the nth table marked's lexer finds (tables/mdtable.ts). */

export default function TableActions({ host, text, m }: { host: HTMLDivElement | null; text: string; m: Msg }) {
  const tables = useMemo(() => tablesOf(text), [text])
  const ctx = useContext(TurnActionsCtx)
  const [at, setAt] = useState<{ top: number; bottom: number; right: number }[]>([])
  const [on, setOn] = useState<number | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const [said, setSaid] = useState<{ i: number; s: string } | null>(null)

  // where each table sits, relative to the prose's wrapper; re-measured as the column resizes
  useLayoutEffect(() => {
    if (!host || !tables.length) return
    const measure = () => {
      const box = host.parentElement!.getBoundingClientRect()
      setAt([...host.querySelectorAll('table')].slice(0, tables.length).map((t) => {
        // the table is a scrolling block as wide as the column: its RIGHT is where its last cell ends
        const r = t.getBoundingClientRect(), row = (t as HTMLTableElement).rows[0]?.getBoundingClientRect()
        return { top: r.top - box.top, bottom: r.bottom - box.top, right: Math.max(0, box.right - Math.min(row?.right ?? r.right, r.right, box.right)) }
      }))
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(host)
    return () => ro.disconnect()
  }, [host, tables.length, text])
  // which table the pointer (or focus) is in
  useEffect(() => {
    const wrap = host?.parentElement
    if (!wrap || !tables.length) return
    const over = (e: Event) => {
      const t = (e.target as Element).closest?.('table')
      if (t) setOn([...host!.querySelectorAll('table')].indexOf(t))
      else if (!(e.target as Element).closest?.('.ws-tbl-acts')) setOn(null)
    }
    const leave = () => setOn(null)
    wrap.addEventListener('pointerover', over)
    wrap.addEventListener('pointerleave', leave)
    return () => { wrap.removeEventListener('pointerover', over); wrap.removeEventListener('pointerleave', leave) }
  }, [host, tables.length])

  if (!tables.length || !at.length) return null
  // no hover (a phone): the pill is always there, so it sits UNDER the table instead of over its header
  const touch = typeof matchMedia === 'function' && matchMedia('(hover: none)').matches
  const flash = (i: number, s: string) => { setSaid({ i, s }); setTimeout(() => setSaid((x) => (x?.i === i ? null : x)), 1800) }
  const name = (i: number) => tableName(tables[i], text, i + 1, tables.length)
  const chart = async (i: number) => {
    if (!ctx?.openTable) return
    setBusy(i)
    try {
      const { toCsv } = await import('../tables/files')
      await ctx.openTable(m, toCsv(tables[i].rows), name(i))
    } catch (e) { flash(i, `Not opened: ${(e as Error).message}`) } finally { setBusy(null) }
  }
  const out = async (i: number, fmt: 'csv' | 'xlsx') => {
    try {
      const f = await import('../tables/files')
      if (fmt === 'csv') f.downloadCsv(tables[i].rows, name(i))
      else await f.downloadXlsx(tables[i].rows, name(i))
    } catch (e) { flash(i, `Not saved: ${(e as Error).message}`) }
  }
  return (
    <>
      {at.map((p, i) => (
        <div key={i} className="ws-tbl-acts" data-on={on === i || busy === i || said?.i === i ? 1 : 0} style={{ top: touch ? p.bottom + 2 : Math.max(0, p.top - 15), right: touch ? p.right : p.right + 6 }}
          role="toolbar" aria-label={`table ${i + 1} actions`} onPointerEnter={() => setOn(i)}>
          {said?.i === i ? <span className="px-2 h-[26px] inline-flex items-center text-[12px] text-ink-dim" role="status">{said.s}</span> : <>
            {ctx?.openTable && (
              <button onClick={() => void chart(i)} disabled={busy === i} title="Open this table as a chart beside the chat">
                {busy === i ? <span className="w-3 h-3 rounded-full border-[1.5px] border-current border-t-transparent animate-spin" aria-hidden /> : CHART}Chart
              </button>
            )}
            <button onClick={() => void out(i, 'csv')} title="Download this table as CSV">{DOWN}CSV</button>
            <button onClick={() => void out(i, 'xlsx')} title="Download this table as an Excel workbook">{DOWN}Excel</button>
          </>}
        </div>
      ))}
    </>
  )
}

const P = { viewBox: '0 0 24 24', className: 'w-[13px] h-[13px]', fill: 'none', stroke: 'currentColor', strokeWidth: 1.9, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }
const CHART = <svg {...P}><path d="M4 19.5h16" /><path d="M4 15l5-5 4 3 7-7" /></svg>
const DOWN = <svg {...P}><path d="M12 4v11M7 10.5l5 5 5-5M5 20h14" /></svg>
