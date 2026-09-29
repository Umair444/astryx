import { useState } from 'react'
import { Badge, Button, Modal, ScrollArea, Select, TextInput, Textarea, Tooltip } from '@mantine/core'
import { agentColor, apiPost, displayName, fmtAgo, fmtTokens } from '../api'
import { useStore } from '../store'
import type { Goal } from '../types'

/* owner files a goal; the assignment rides the wire as a task message */
function NewGoalButton() {
  const { agents, refreshGoals } = useStore()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [assignee, setAssignee] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const file = async () => {
    if (!title.trim() || !assignee) return
    setBusy(true)
    try {
      await apiPost('/goals', {
        title: title.trim(),
        assignee,
        scope_note: note.trim() || null,
        // no budget_tokens: goal 4227 retired budgets (the API stores 0 when it's absent)
      })
      setOpen(false)
      setTitle(''); setNote(''); setAssignee(null)
      refreshGoals()
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Button size="compact-sm" color="cyan" variant="light" onClick={() => setOpen(true)}>
        ＋ File goal
      </Button>
      <Modal opened={open} onClose={() => setOpen(false)} title="File a goal" centered size="md">
        <div className="space-y-3">
          <TextInput
            label="Title"
            placeholder="what should get done"
            value={title}
            onChange={(e) => setTitle(e.currentTarget.value)}
            data-autofocus
          />
          <Select
            label="Assign to"
            placeholder="the responsible agent"
            searchable
            data={[...agents]
              .sort((x, y) => x.agent.localeCompare(y.agent))
              .map((a) => ({ value: a.agent, label: displayName(a.agent) }))}
            value={assignee}
            onChange={setAssignee}
          />
          <Textarea
            label="Scope note"
            placeholder="boundaries, context, what done looks like (optional)"
            autosize
            minRows={2}
            value={note}
            onChange={(e) => setNote(e.currentTarget.value)}
          />
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="subtle" color="gray" onClick={() => setOpen(false)}>
              cancel
            </Button>
            <Button color="cyan" loading={busy} disabled={!title.trim() || !assignee} onClick={file}>
              file → wire
            </Button>
          </div>
          <div className="text-[11px] text-ink-mute">
            Filing inserts the goal (proposed) and sends the assignment to the agent on thread{' '}
            <span className="font-mono">goal-&lt;id&gt;</span> — the doorbell wakes them immediately.
          </div>
        </div>
      </Modal>
    </>
  )
}

const COLS: { key: string; label: string; color: string }[] = [
  { key: 'proposed', label: 'proposed', color: '#9aa7c7' },
  { key: 'active', label: 'active', color: '#22d3ee' },
  { key: 'shipped', label: 'shipped', color: '#2fbf71' },
  { key: 'done', label: 'done', color: '#f2c14e' },
  { key: 'hibernated', label: 'hibernated', color: '#7c5cff' },
  { key: 'refused', label: 'refused', color: '#ff5c7a' },
]

function GoalCard({ g }: { g: Goal }) {
  // Goal 4227: there are no budgets. A legacy goal's budget is shown only as muted HISTORY. No
  // progress bar: spent_tokens was never written (0 on every row), so a bar would read "unused"
  // where the truth is "never measured".
  const budgetEra = g.budget_tokens ?? 0
  return (
    <div className="bg-deck-2 border border-line rounded-lg p-3 hover:border-cyan/40 transition-colors duration-75">
      <div className="text-sm text-ink leading-snug">{g.title}</div>
      {g.scope_note && <div className="text-[11px] text-ink-mute mt-1 line-clamp-2">{g.scope_note}</div>}
      <div className="flex items-center gap-2 mt-2">
        <span
          className="w-4 h-4 rounded-full grid place-items-center text-[9px] font-bold text-deck"
          style={{ background: agentColor(g.owner) }}
        >
          {g.owner?.[0]}
        </span>
        <span className="text-[11px] text-ink-mute">{g.owner}</span>
        {g.dead_epochs > 0 && (
          <Tooltip label={`${g.dead_epochs} epoch${g.dead_epochs > 1 ? 's' : ''} without progress`} withArrow>
            <Badge size="xs" color="red" variant="light">
              ☠ {g.dead_epochs}
            </Badge>
          </Tooltip>
        )}
        <span className="ml-auto text-[10px] font-mono text-ink-mute">#{g.id}</span>
      </div>
      {budgetEra > 0 && (
        <div className="text-[10px] font-mono text-ink-mute/70 mt-2" title="set before goal 4227 retired budgets; history, not a limit">
          budget-era · {fmtTokens(budgetEra)}
        </div>
      )}
      <div className="text-[10px] text-ink-mute mt-2">
        last progress {fmtAgo(g.last_progress)}
        {g.epoch_hours ? ` · epoch ${g.epoch_hours}h` : ''}
      </div>
    </div>
  )
}

export default function GoalsView() {
  const { goals } = useStore()

  return (
    <ScrollArea className="h-full">
      <div className="flex items-center justify-between px-3 pt-3">
        <span className="text-xs text-ink-mute">
          goals are the org's funded purposes — assignment travels the wire
        </span>
        <NewGoalButton />
      </div>
      <div className="p-3 grid gap-3 md:grid-cols-5">
        {COLS.map((col) => {
          const items = goals.filter((g) => (g.state || 'proposed') === col.key)
          return (
            <div key={col.key} className="min-w-0">
              <div className="flex items-center gap-2 px-1 mb-2">
                <span className="w-2 h-2 rounded-full" style={{ background: col.color }} />
                <span className="text-xs font-semibold uppercase tracking-wider text-ink-dim">{col.label}</span>
                <Badge size="xs" variant="light" color="gray">
                  {items.length}
                </Badge>
              </div>
              <div className="space-y-2">
                {items.map((g) => (
                  <GoalCard key={g.id} g={g} />
                ))}
                {!items.length && <div className="text-xs text-ink-mute px-1">—</div>}
              </div>
            </div>
          )
        })}
      </div>
    </ScrollArea>
  )
}
