import { lazy, Suspense, useState } from 'react'
import { Loading } from '../artifacts/viewers/common'
import './tables.css'

/* A table in the artifact panel, data-forward (iteration 9): Table | Chart, and the table out as CSV or Excel. The
   chart (pick.ts + an SVG renderer) is its own chunk, fetched the first time a chart is asked for; the table stays
   what it was (viewers/Table.tsx's Grid, annotatable). The mode is remembered per table for the session, and a table
   opened from a turn's "Chart" (thread/TableActions.tsx) asks for the chart up front. */

const ChartView = lazy(() => import('./ChartView'))
const modes = new Map<string, 'table' | 'chart'>()
/* a table that should open as its chart (keyed by artifact id) */
export const preferChart = (key: string) => modes.set(key, 'chart')

export default function DataView({ rows, name, memo, source, sheet, children }: {
  rows: string[][]                // the header row first
  name: string                    // the file's name: the chart's title, the download's name
  memo: string                    // what the mode and the chart's settings are remembered under
  source: string                  // the PNG's source line
  sheet?: string
  children: React.ReactNode       // the table view
}) {
  const art = memo.split('#')[0]
  const [mode, setModeRaw] = useState<'table' | 'chart'>(() => modes.get(memo) ?? modes.get(art) ?? 'table')
  const setMode = (m: 'table' | 'chart') => { modes.set(memo, m); setModeRaw(m) }
  const [said, setSaid] = useState('')
  const out = async (fmt: 'csv' | 'xlsx') => {
    try {
      const f = await import('./files')
      const label = sheet ? `${f.stemOf(name)} - ${sheet}` : name
      if (fmt === 'csv') f.downloadCsv(rows, label)
      else { setSaid('Writing…'); await f.downloadXlsx(rows, label, sheet ?? 'Sheet1') }
      setSaid('')
    } catch (e) { setSaid(`Not saved: ${(e as Error).message}`); setTimeout(() => setSaid(''), 2400) }
  }
  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="shrink-0 h-11 flex items-center gap-2 px-3 border-b border-line/60" data-ann-skip>
        <div className="ws-seg" role="group" aria-label="view as">
          <button aria-pressed={mode === 'table'} onClick={() => setMode('table')}>{TABLE}Table</button>
          <button aria-pressed={mode === 'chart'} onClick={() => setMode('chart')}>{CHART}Chart</button>
        </div>
        <span className="ml-auto text-[12px] text-ink-mute" role="status">{said}</span>
        <div className="flex items-center gap-0.5" role="group" aria-label="download the table">
          <button className="ws-tool" onClick={() => void out('csv')} title="Download this table as CSV">{DOWN}<span>CSV</span></button>
          <button className="ws-tool" onClick={() => void out('xlsx')} title="Download this table as an Excel workbook">{DOWN}<span>Excel</span></button>
        </div>
      </div>
      <div className="flex-1 min-h-0">
        {mode === 'table' ? children : (
          <Suspense fallback={<Loading what="Drawing the chart" />}>
            <ChartView key={memo} rows={rows} name={sheet ? `${name.replace(/\.[a-z0-9]{1,5}$/i, '')} · ${sheet}` : name} memo={memo} source={source} />
          </Suspense>
        )}
      </div>
    </div>
  )
}

const P = { viewBox: '0 0 24 24', className: 'w-[14px] h-[14px]', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }
const TABLE = <svg {...P}><rect x="3.5" y="4.5" width="17" height="15" rx="2.5" /><path d="M3.5 9.5h17M3.5 14.5h17M9.5 9.5v10" /></svg>
const CHART = <svg {...P}><path d="M4 19.5h16" /><path d="M4 15l5-5 4 3 7-7" /></svg>
const DOWN = <svg {...P}><path d="M12 4v11M7 10.5l5 5 5-5M5 20h14" /></svg>
