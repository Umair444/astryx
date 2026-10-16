import { useEffect, useRef, useState } from 'react'
import MonitorView from './MonitorView'
import SqlView from './SqlView'

/* One tab, stacked: live system stats on top, the SQL workbench below.
   The split drags to resize, and either half can be hidden entirely. */
export default function SystemView() {
  const ref = useRef<HTMLDivElement>(null)
  // the monitor half opens tall enough for its header and vitals (a new key: the old 320px default
  // predates the header and would crop it)
  const [topH, setTopH] = useState(() => +(localStorage.getItem('sys_monH') || Math.round(window.innerHeight * 0.62)))
  const [sqlHidden, setSqlHidden] = useState(() => localStorage.getItem('sys_sqlHidden') === '1')
  const [monHidden, setMonHidden] = useState(() => localStorage.getItem('sys_monHidden') === '1')
  useEffect(() => { localStorage.setItem('sys_monH', String(topH)) }, [topH])
  useEffect(() => { localStorage.setItem('sys_sqlHidden', sqlHidden ? '1' : '0') }, [sqlHidden])
  useEffect(() => { localStorage.setItem('sys_monHidden', monHidden ? '1' : '0') }, [monHidden])

  function startDrag(e: React.MouseEvent) {
    e.preventDefault()
    const y0 = e.clientY
    const h0 = topH
    const box = ref.current?.getBoundingClientRect()
    const move = (m: MouseEvent) => {
      const max = (box ? box.height : 800) - 140
      setTopH(Math.max(140, Math.min(max, h0 + (m.clientY - y0))))
    }
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      document.body.style.cursor = ''
    }
    document.body.style.cursor = 'row-resize'
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  return (
    <div ref={ref} className="h-full flex flex-col">
      {monHidden ? (
        <button
          onClick={() => setMonHidden(false)}
          className="shrink-0 h-8 border-b border-line text-[10.5px] uppercase tracking-[0.2em] text-ink-mute hover:text-ink hover:bg-deck-3/40 transition-colors"
        >
          ▾ show the monitor
        </button>
      ) : (
        <div className="min-h-0" style={sqlHidden ? { flex: 1 } : { height: topH }}>
          <MonitorView />
        </div>
      )}

      {!monHidden && !sqlHidden && (
        <div
          onMouseDown={startDrag}
          className="group relative h-7 shrink-0 cursor-row-resize flex items-center justify-center border-y border-line bg-deck-2/70 backdrop-blur hover:bg-deck-3/60 transition-colors"
          title="drag to resize"
        >
          <span className="w-10 h-1 rounded-full bg-line-2 group-hover:bg-cyan/60 transition-colors" />
          <span className="absolute left-4 text-[10.5px] uppercase tracking-[0.18em] text-ink-mute">SQL workbench</span>
          <div className="absolute right-3 flex gap-1" onMouseDown={(e) => e.stopPropagation()}>
            <button onClick={() => setMonHidden(true)} title="hide monitor" className="px-1.5 text-[11px] text-ink-mute hover:text-ink">
              ▲
            </button>
            <button onClick={() => setSqlHidden(true)} title="hide SQL workbench" className="px-1.5 text-[11px] text-ink-mute hover:text-ink">
              ▼
            </button>
          </div>
        </div>
      )}

      {sqlHidden ? (
        <button
          onClick={() => setSqlHidden(false)}
          className="shrink-0 h-8 border-t border-line text-[10.5px] uppercase tracking-[0.2em] text-ink-mute hover:text-ink hover:bg-deck-3/40 transition-colors"
        >
          ▴ show the SQL workbench
        </button>
      ) : (
        <div className="flex-1 min-h-0 bg-deck-2/60 backdrop-blur-xl">
          <SqlView />
        </div>
      )}
    </div>
  )
}
