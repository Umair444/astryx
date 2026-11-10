import { useState } from 'react'
import { displayName } from '../../api'
import AgentFace from '../../components/AgentFace'
import type { Color } from './model'
import { ProjectMark, Swatches } from './parts'

/* NEW PROJECT: a name, what it is for (the instructions; optional, editable on its home later), a colour and an
   optional emoji. Made from inside a conversation, that conversation and its agents join it (shown, so the owner
   knows what moves). Esc or a click outside closes it; nothing is made until "Create project". */

const seg = typeof Intl !== 'undefined' && 'Segmenter' in Intl ? new Intl.Segmenter(undefined, { granularity: 'grapheme' }) : null
const firstGrapheme = (s: string) => (seg ? ([...seg.segment(s)][0]?.segment ?? '') : [...s].slice(0, 2).join(''))

export interface Draft { name: string; instructions: string; color: Color; emoji: string | null }

export default function NewProject({ suggest, seedAgents, seedThread, onClose, onCreate }: {
  suggest: Color
  seedAgents: string[]
  seedThread: string | null            // the conversation it is made from, by title
  onClose: () => void
  onCreate: (d: Draft) => void
}) {
  const [name, setName] = useState('')
  const [instructions, setInstructions] = useState('')
  const [color, setColor] = useState<Color>(suggest)
  const [emoji, setEmoji] = useState('')
  const e = firstGrapheme(emoji.trim())                                    // one emoji, a flag or a family whole
  const okEmoji = !e || !/[\sA-Za-z0-9<>&"']/.test(e)
  const submit = () => { if (name.trim() && okEmoji) onCreate({ name: name.trim(), instructions: instructions.trim(), color, emoji: e || null }) }
  return (
    <div className="fixed inset-0 z-50 ws-scrim grid place-items-start justify-center pt-[12vh] px-4 overflow-y-auto" onMouseDown={onClose}>
      <form role="dialog" aria-label="new project" className="ws-menu w-full max-w-[520px] !rounded-[20px] p-6 mb-10" onMouseDown={(x) => x.stopPropagation()}
        onSubmit={(x) => { x.preventDefault(); submit() }} onKeyDown={(x) => { if (x.key === 'Escape') { x.stopPropagation(); onClose() } }}>
        <div className="flex items-center gap-3">
          <ProjectMark p={{ color, emoji: e || null }} size={40} />
          <div>
            <div className="ws-display text-[30px] leading-none text-ink">New project</div>
            <div className="text-[12.5px] text-ink-mute mt-1">Instructions, a team, its files and its conversations, in one place.</div>
          </div>
        </div>

        <label className="block mt-6 text-[12.5px] font-medium text-ink" htmlFor="np-name">Name</label>
        <input id="np-name" autoFocus value={name} onChange={(x) => setName(x.target.value)} maxLength={80} placeholder="Q4 lending review"
          className="mt-1.5 w-full rounded-[12px] bg-[var(--t-bg)] border border-line focus:border-[color-mix(in_srgb,var(--t-accent)_45%,var(--t-line))] outline-none px-3 py-2.5 text-[15px] text-ink placeholder:text-ink-mute" />

        <label className="block mt-4 text-[12.5px] font-medium text-ink" htmlFor="np-ins">What is it for? <span className="font-normal text-ink-mute">optional</span></label>
        <textarea id="np-ins" value={instructions} onChange={(x) => setInstructions(x.target.value)} rows={3} maxLength={20000}
          placeholder="The outcome you want, the data to trust, how answers should look. Every new chat in this project starts with it."
          className="mt-1.5 w-full rounded-[12px] bg-[var(--t-bg)] border border-line focus:border-[color-mix(in_srgb,var(--t-accent)_45%,var(--t-line))] outline-none px-3 py-2.5 text-[14px] leading-relaxed text-ink placeholder:text-ink-mute resize-y" />

        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-3">
          <div>
            <div className="text-[12.5px] font-medium text-ink mb-1.5">Colour</div>
            <Swatches value={color} onPick={(c) => setColor(c as Color)} />
          </div>
          <div>
            <label className="block text-[12.5px] font-medium text-ink mb-1.5" htmlFor="np-emoji">Emoji <span className="font-normal text-ink-mute">optional</span></label>
            <input id="np-emoji" value={emoji} onChange={(x) => setEmoji(x.target.value)} maxLength={8} placeholder="📈" aria-invalid={!okEmoji}
              className="w-14 h-8 text-center rounded-[10px] bg-[var(--t-bg)] border border-line outline-none text-[16px] aria-[invalid=true]:border-bad" />
          </div>
        </div>

        {(seedThread || seedAgents.length > 0) && (
          <div className="mt-5 rounded-[12px] border border-line px-3 py-2.5 text-[12.5px] text-ink-dim flex items-center gap-2 flex-wrap">
            <span>Joins it:</span>
            {seedThread && <span className="text-ink truncate max-w-[220px]">“{seedThread}”</span>}
            {seedAgents.map((a) => <span key={a} className="inline-flex items-center gap-1"><AgentFace name={a} size={16} />{displayName(a)}</span>)}
          </div>
        )}

        <div className="mt-6 flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} className="ws-btn">Cancel</button>
          <button type="submit" disabled={!name.trim() || !okEmoji} className="ws-btn ws-btn-primary">Create project</button>
        </div>
      </form>
    </div>
  )
}

