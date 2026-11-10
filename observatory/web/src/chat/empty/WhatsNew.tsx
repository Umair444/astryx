import { useState } from 'react'
import { I } from '../icons'
import './briefing.css'

/* "NEW IN YOUR WORKSPACE" (iteration 15): what tonight's rebuild added, once. Each line says what it does in the
   owner's terms and has a "Show me" that goes there. Dismissed for good per browser (localStorage); storage that
   can't be written just means the card shows again next time, never an error. */

export type Feature = 'projects' | 'files' | 'annotate' | 'changes' | 'library' | 'charts' | 'search' | 'map' | 'stop' | 'canvas' | 'phone' | 'keys'

const KEY = 'ws.whatsnew.v1'
const ITEMS: { k: Feature; name: string; what: string }[] = [
  { k: 'projects', name: 'Projects', what: 'Instructions, files and a team in one place; the team can run a project on its own.' },
  { k: 'files', name: 'Files with versions', what: 'Files open beside the chat. Every version is kept, with a word-by-word diff.' },
  { k: 'annotate', name: 'Annotate', what: 'Highlight a passage to comment, or ask an agent about it in the margin.' },
  { k: 'changes', name: 'Send changes', what: 'Edit a file, then send your changes to the agent who made it.' },
  { k: 'library', name: 'Library', what: 'Every file from every conversation, in one place.' },
  { k: 'charts', name: 'Tables to charts', what: 'Any table becomes a chart, or downloads as CSV or Excel.' },
  { k: 'search', name: 'Search', what: 'Search every conversation; a result opens at the message.' },
  { k: 'map', name: 'Team map', what: 'Who is working, and where work is passing between agents, live.' },
  { k: 'stop', name: 'Stop', what: 'Stop an agent mid-answer from the line that shows it working.' },
  { k: 'canvas', name: 'Canvases and Talk', what: 'Painted canvases open in the chat; Talk is a voice conversation.' },
  { k: 'phone', name: 'On your phone', what: 'Open this page on your phone and add it to the home screen.' },
  { k: 'keys', name: 'Keyboard', what: 'Everything has a key. ⌘K finds anything.' },
]

export function useWhatsNew(): [boolean, () => void] {
  const [shown, setShown] = useState(() => { try { return localStorage.getItem(KEY) !== 'dismissed' } catch { return true } })
  return [shown, () => { setShown(false); try { localStorage.setItem(KEY, 'dismissed') } catch { /* shows again next time */ } }]
}

export default function WhatsNew({ onShow, onDismiss }: { onShow: (f: Feature) => void; onDismiss: () => void }) {
  return (
    <section className="ws-new" aria-label="new in your workspace">
      <div className="flex items-start gap-3">
        <div className="min-w-0">
          <h2 className="text-[14px] font-medium text-ink">New in your workspace</h2>
          <p className="text-[12.5px] text-ink-mute mt-0.5">Rebuilt overnight. What you can do now:</p>
        </div>
        <button className="ws-icon ml-auto -mr-2 -mt-1.5 shrink-0" onClick={onDismiss} aria-label="dismiss what's new" title="Got it">{I.x('w-4 h-4')}</button>
      </div>
      <ul className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-x-8" role="list">
        {ITEMS.map((x) => (
          <li key={x.k} className="ws-new-item">
            <span className="min-w-0 flex-1 text-[13px] leading-snug"><span className="text-ink font-medium">{x.name}.</span> <span className="text-ink-dim">{x.what}</span></span>
            <button className="ws-new-show shrink-0" onClick={() => onShow(x.k)}>Show me</button>
          </li>
        ))}
      </ul>
    </section>
  )
}
