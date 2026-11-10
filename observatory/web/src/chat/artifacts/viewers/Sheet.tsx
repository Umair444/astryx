import { useEffect, useState } from 'react'
import { Grid } from './Table'
import { Failed, Loading } from './common'
import { readXlsx, type Sheet } from './office'

/* An .xlsx as its sheets' VALUES (no formulas, no styles: what an agent's export carries), one tab per sheet. Read
   with JSZip + the browser's XML parser (office.ts), a few KB instead of a spreadsheet engine. */
export default function SheetView({ blob }: { blob: Blob }) {
  const [sheets, setSheets] = useState<Sheet[] | null>(null)
  const [err, setErr] = useState('')
  const [at, setAt] = useState(0)
  useEffect(() => {
    let live = true
    readXlsx(blob).then((s) => live && setSheets(s)).catch((e) => live && setErr(`This spreadsheet could not be read (${(e as Error).message}).`))
    return () => { live = false }
  }, [blob])
  if (err) return <Failed err={err} />
  if (!sheets) return <Loading what="Reading the spreadsheet" />
  if (!sheets.length) return <Failed err="This spreadsheet has no sheets." />
  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 min-h-0"><Grid key={at} rows={sheets[at].rows} /></div>
      {sheets.length > 1 && (
        <div className="shrink-0 flex gap-0.5 px-2 py-1.5 border-t border-line overflow-x-auto" role="tablist" aria-label="sheets">
          {sheets.map((s, i) => (
            <button key={i} role="tab" aria-selected={i === at} onClick={() => setAt(i)}
              className={`px-3 h-7 rounded-[8px] text-[12.5px] whitespace-nowrap ${i === at ? 'bg-[color-mix(in_srgb,var(--t-fg)_8%,transparent)] text-ink font-medium' : 'text-ink-dim hover:text-ink'}`}>{s.name}</button>
          ))}
        </div>
      )}
    </div>
  )
}
