import { useEffect, useMemo, useState } from 'react'
import { Button, Modal, ScrollArea, Select, TextInput, Textarea, Tooltip } from '@mantine/core'
import { AnimatePresence, motion } from 'motion/react'
import { apiPost, displayName, fmtAgo, fmtTokens } from '../api'
import { useStore } from '../store'
import type { Goal } from '../types'
import AgentFace from './AgentFace'
import GoalDetail from './GoalDetail'
import { Action, Empty, LiveDot, Panel, Skeleton, ViewHeader, useNow } from '../ui/kit'

/* GOALS — what the org is pursuing, as a board that breathes: a goal with progress in the last
   day glows (its owner is on it), a stalled one says so, and every card is its owner's face. */

const LIVE_WINDOW = 24 * 3600_000 // progress this recent means the goal is moving right now

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
      <Action onClick={() => setOpen(true)}><span className="text-base leading-none">+</span> File a goal</Action>
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

type Col = { key: string; label: string; color: string }
// two tiers so the board never runs off the screen: what is in motion, then what has settled
const MOTION: Col[] = [
  { key: 'proposed', label: 'Proposed', color: 'var(--t-dim)' },
  { key: 'active', label: 'Active', color: 'var(--t-accent)' },
  { key: 'shipped', label: 'Shipped', color: 'var(--t-good)' },
]
const SETTLED: Col[] = [
  { key: 'done', label: 'Done', color: 'var(--t-warn)' },
  { key: 'hibernated', label: 'Hibernated', color: 'var(--t-accent2)' },
  { key: 'refused', label: 'Refused', color: 'var(--t-bad)' },
]

const ago = (t: string | null) => { const a = fmtAgo(t); return a === 'now' ? 'just now' : `${a} ago` }

const isMoving = (g: Goal, now: number) =>
  (g.state === 'active' || g.state === 'proposed') && !!g.last_progress && now - Date.parse(g.last_progress) < LIVE_WINDOW

function GoalCard({ g, now, onOpen }: { g: Goal; now: number; onOpen: (id: number) => void }) {
  // Goal 4227: there are no budgets. A legacy goal's budget is shown only as muted HISTORY. No
  // progress bar: spent_tokens was never written (0 on every row), so a bar would read "unused"
  // where the truth is "never measured".
  const budgetEra = g.budget_tokens ?? 0
  const moving = isMoving(g, now)
  return (
    <motion.div layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }}
      transition={{ type: 'spring', damping: 28, stiffness: 300 }}>
      <Panel as="button" interactive live={moving} onClick={() => onOpen(g.id)} className="w-full p-3.5 flex flex-col gap-2.5">
        <div className="text-[13.5px] font-medium text-ink leading-snug line-clamp-3">{g.title}</div>
        {g.scope_note && <div className="text-[11.5px] text-ink-mute leading-snug line-clamp-1">{g.scope_note}</div>}
        <div className="flex items-center gap-2 min-w-0">
          <AgentFace name={g.owner} size={20} />
          <span className="text-[12px] text-ink-dim truncate">{displayName(g.owner)}</span>
          <span className="ml-auto text-[10.5px] font-mono text-ink-mute shrink-0">#{g.id}</span>
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-mute">
          {moving ? (
            <span className="flex items-center gap-1.5 text-cyan"><LiveDot state="working" />moving · {ago(g.last_progress)}</span>
          ) : (
            <span>{g.last_progress ? `progress ${ago(g.last_progress)}` : 'no progress yet'}</span>
          )}
          {g.dead_epochs > 0 && (
            <Tooltip label={`${g.dead_epochs} epoch${g.dead_epochs > 1 ? 's' : ''} without progress${g.epoch_hours ? ` (epoch ${g.epoch_hours}h)` : ''}`} withArrow>
              <span className="px-1.5 py-px rounded-full border border-bad/40 text-bad text-[10px]">stalled · {g.dead_epochs}</span>
            </Tooltip>
          )}
          {budgetEra > 0 && (
            <span className="ml-auto font-mono text-[10px] text-ink-mute/70" title="set before goal 4227 retired budgets; history, not a limit">
              budget-era · {fmtTokens(budgetEra)}
            </span>
          )}
        </div>
      </Panel>
    </motion.div>
  )
}

function Board({ cols, byState, now, onOpen }: { cols: Col[]; byState: Map<string, Goal[]>; now: number; onOpen: (id: number) => void }) {
  return (
    <div className="-mx-5 sm:-mx-8 px-5 sm:px-8 overflow-x-auto pb-2 snap-x snap-mandatory md:snap-none">
      <div className="grid gap-4 items-start" style={{ gridTemplateColumns: `repeat(${cols.length}, minmax(264px, 1fr))` }}>
        {cols.map((col) => {
          const items = byState.get(col.key) ?? []
          return (
            <section key={col.key} className="min-w-0 snap-start">
              <div className="flex items-center gap-2 px-1 mb-3">
                <span className="w-2 h-2 rounded-full" style={{ background: col.color, boxShadow: `0 0 10px ${col.color}` }} />
                <span className="text-[12px] font-semibold uppercase tracking-[0.14em] text-ink-dim">{col.label}</span>
                <span className="text-[11px] font-mono text-ink-mute">{items.length}</span>
                <span className="flex-1 h-px ml-1" style={{ background: `linear-gradient(90deg, color-mix(in srgb, ${col.color} 45%, transparent), transparent)` }} />
              </div>
              <div className="flex flex-col gap-3">
                <AnimatePresence initial={false}>
                  {items.map((g) => <GoalCard key={g.id} g={g} now={now} onOpen={onOpen} />)}
                </AnimatePresence>
                {!items.length && (
                  <div className="rounded-2xl border border-dashed border-line px-3 py-6 text-center text-[12px] text-ink-mute">nothing here yet</div>
                )}
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
}

export default function GoalsView() {
  const { goals } = useStore()
  const now = useNow(30_000)
  const [open, setOpen] = useState<number | null>(null)
  // the store can't tell "loading" from "none": give the first fetch a moment before saying empty
  const [settled, setSettled] = useState(false)
  useEffect(() => { const t = setTimeout(() => setSettled(true), 2500); return () => clearTimeout(t) }, [])

  const byState = useMemo(() => {
    const m = new Map<string, Goal[]>()
    for (const g of goals) {
      const k = g.state || 'proposed'
      m.set(k, [...(m.get(k) ?? []), g])
    }
    for (const list of m.values())
      list.sort((a, b) => Number(isMoving(b, now)) - Number(isMoving(a, now)) ||
        (b.last_progress ? Date.parse(b.last_progress) : 0) - (a.last_progress ? Date.parse(a.last_progress) : 0) || b.id - a.id)
    return m
  }, [goals, now])

  const count = (k: string) => byState.get(k)?.length ?? 0
  const moving = goals.filter((g) => isMoving(g, now))
  const owners = [...new Set(goals.filter((g) => g.state === 'active').map((g) => g.owner))]
  const settled_ = SETTLED.filter((c) => count(c.key) > 0)

  return (
    <ScrollArea className="h-full">
      <div className="px-5 sm:px-8 py-7 max-w-[1500px] mx-auto">
        <ViewHeader
          kicker="what the org is pursuing"
          title="Goals"
          live={goals.length ? <>
            <span className="flex items-center gap-1.5"><LiveDot state={moving.length ? 'working' : 'awake'} />{moving.length} moving now</span>
            <span className="text-ink-mute">·</span>
            <span>{count('active')} active</span>
            <span className="text-ink-mute">·</span>
            <span>{count('shipped')} shipped</span>
            <span className="text-ink-mute">·</span>
            <span>{count('proposed')} proposed</span>
            <span className="text-ink-mute hidden sm:inline">— assignment travels the wire</span>
          </> : <span className="text-ink-mute">goals are the org's purposes — assignment travels the wire</span>}
          faces={owners}
          actions={<NewGoalButton />}
        />

        {!goals.length && (settled
          ? <Empty title="No goals on the board yet" hint="File the first one — it lands as proposed and its owner is woken on the wire." />
          : <div className="grid gap-4 grid-cols-1 md:grid-cols-3">{[0, 1, 2].map((i) => (
              <div key={i} className="flex flex-col gap-3"><Skeleton className="h-5 w-24" /><Skeleton className="h-28 rounded-2xl" /><Skeleton className="h-20 rounded-2xl" /></div>
            ))}</div>)}

        {goals.length > 0 && <Board cols={MOTION} byState={byState} now={now} onOpen={setOpen} />}
        {goals.length > 0 && settled_.length > 0 && (
          <div className="mt-10">
            <div className="text-[11px] uppercase tracking-[0.18em] text-ink-mute mb-4">settled</div>
            <Board cols={settled_} byState={byState} now={now} onOpen={setOpen} />
          </div>
        )}
      </div>
      {open != null && <GoalDetail id={open} onClose={() => setOpen(null)} onOpen={setOpen} />}
    </ScrollArea>
  )
}
