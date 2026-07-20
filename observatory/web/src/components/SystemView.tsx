import { useEffect, useRef, useState } from 'react'
import MonitorView from './MonitorView'
import SqlView from './SqlView'

/* One tab, stacked: live system stats on top, the SQL workbench below.
   The split drags to resize, and either half can be hidden entirely. */
export default function SystemView() {
  const ref = useRef<HTMLDivElement>(null)
  const [topH, setTopH] = useState(() => +(localStorage.getItem('sys_topH') || 320))
  const [sqlHidden, setSqlHidden] = useState(() => localStorage.getItem('sys_sqlHidden') === '1')
  const [monHidden, setMonHidden] = useState(() => localStorage.getItem('sys_monHidden') === '1')
  useEffect(() => { localStorage.setItem('sys_topH', String(topH)) }, [topH])
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
          className="shrink-0 h-6 border-b border-line text-[10px] uppercase tracking-[0.2em] text-ink-mute hover:text-cyan-soft"
        >
          ▾ show monitor
        </button>
      ) : (
        <div className="min-h-0 border-b border-line" style={sqlHidden ? { flex: 1 } : { height: topH }}>
          <MonitorView />
        </div>
      )}

      {!monHidden && !sqlHidden && (
        <div
          onMouseDown={startDrag}
          className="group relative h-1.5 shrink-0 cursor-row-resize bg-line/40 hover:bg-cyan-soft/40 flex items-center"
        >
          <div className="absolute right-3 flex gap-3" onMouseDown={(e) => e.stopPropagation()}>
            <button onClick={() => setMonHidden(true)} title="hide monitor" className="text-[10px] text-ink-mute hover:text-cyan-soft">
              ▲
            </button>
            <button onClick={() => setSqlHidden(true)} title="hide SQL workbench" className="text-[10px] text-ink-mute hover:text-cyan-soft">
              ▼
            </button>
          </div>
        </div>
      )}

      {sqlHidden ? (
        <button
          onClick={() => setSqlHidden(false)}
          className="shrink-0 h-6 border-t border-line text-[10px] uppercase tracking-[0.2em] text-ink-mute hover:text-cyan-soft"
        >
          ▴ show SQL workbench
        </button>
      ) : (
        <div className="flex-1 min-h-0">
          <SqlView />
        </div>
      )}
    </div>
  )
}
