import { useEffect, useRef, useState } from 'react'
import { viewer } from '../../api'
import { I } from '../icons'
import { loadPeople, type Person, type Project } from '../model'

/* WHO CAN SEE IT (owner 11-17: "the person who create project should be able to decide which member can see it"):
   the project's maker picks the members it is shared with; the org's owner always sees every project. Anyone else
   who can see it only reads this card. The server decides (workspace.project_visible); this is its control. */

export default function Sharing({ p, onChange }: { p: Project; onChange: (shared: string[]) => void }) {
  const me = viewer()
  const maker = p.by || 'owner'
  const mine = me === maker || me === 'owner'
  const shared = p.shared ?? []
  const [people, setPeople] = useState<Person[] | null>(null)
  const [adding, setAdding] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { loadPeople().then(setPeople).catch(() => setPeople([])) }, [])
  useEffect(() => {
    if (!adding) return
    const off = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setAdding(false) }
    addEventListener('mousedown', off)
    return () => removeEventListener('mousedown', off)
  }, [adding])
  const name = (h: string) => people?.find((x) => x.handle === h)?.name ?? h.replace(/^cv-/, '').replace(/\.\d+$/, '')
  const offer = (people ?? []).filter((x) => !shared.includes(x.handle) && x.handle !== maker)

  return (
    <section className="ws-kcard p-4" aria-label="who can see it">
      <div className="flex items-center gap-2 mb-1" ref={box}>
        <h2 className="text-[13px] font-medium text-ink">Who can see it</h2>
        {mine && (
          <div className="relative ml-auto">
            <button className="ws-icon !w-auto px-2 gap-1 !flex items-center text-[12.5px]" onClick={() => setAdding((x) => !x)}
              aria-expanded={adding} disabled={!offer.length}>{I.plus('w-3.5 h-3.5')}Share</button>
            {adding && (
              <div className="ws-menu absolute right-0 top-[calc(100%+4px)] z-30 w-[240px] max-h-[300px] overflow-y-auto p-1" role="menu"
                aria-label="share with" style={{ ['--ws-pip-bg' as string]: 'var(--t-panel)' }}>
                {offer.map((x) => (
                  <button key={x.handle} role="menuitem" className="ws-row w-full rounded-lg px-2 py-1.5 text-left text-[13px] text-ink"
                    onClick={() => { onChange([...shared, x.handle]); setAdding(false) }}>{x.name}</button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      <p className="text-[12px] text-ink-mute mb-2">{maker === 'owner' ? 'You' : name(maker)} and the people below.{maker !== 'owner' ? ' The owner sees every project.' : ''}</p>
      {shared.length === 0
        ? <p className="text-[12.5px] text-ink-dim">{mine ? 'Not shared with anyone yet.' : 'Shared with no one else.'}</p>
        : <ul className="flex flex-wrap gap-1.5">{shared.map((h) => (
            <li key={h} className="inline-flex items-center gap-1 h-6 pl-2 pr-1 rounded-md border border-line text-[12px] text-ink-dim">
              {name(h)}
              {mine && <button aria-label={`Stop sharing with ${name(h)}`} className="grid place-items-center w-4 h-4 rounded text-ink-mute hover:text-bad"
                onClick={() => onChange(shared.filter((x) => x !== h))}>×</button>}
            </li>))}</ul>}
    </section>
  )
}
