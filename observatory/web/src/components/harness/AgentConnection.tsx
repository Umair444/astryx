import { useState } from 'react'
import ConnectionPicker from './ConnectionPicker'
import { useHarness } from './model'

/* An agent's own drawer: the same connection the Agents tab's Harness and Keys edits, for this one agent. */
export default function AgentConnection({ name }: { name: string }) {
  const { state, setState, error } = useHarness()
  const [note, setNote] = useState<string | null>(null)
  if (error) return <div className="text-[12px] text-bad py-4">{error}</div>
  if (!state) return <div className="text-xs text-ink-mute py-4">loading…</div>
  return (
    <div className="flex flex-col gap-3 ax-controls">
      <p className="text-[12px] text-ink-dim">The harness, key and model this agent runs on. Keys are added under Harness and Keys on the Agents tab.</p>
      <ConnectionPicker key={JSON.stringify(state.agents.find((a) => a.name === name))} s={state} agent={name}
        onSaved={(next) => { setState(next); setNote('Saved. It switches the next time it starts.') }} />
      {note && <div className="text-[12px] text-good" role="status">{note}</div>}
    </div>
  )
}
