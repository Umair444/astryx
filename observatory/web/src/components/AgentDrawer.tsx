import { useEffect, useState } from 'react'
import { Badge, Drawer, ScrollArea } from '@mantine/core'
import { api, agentColor, fmtAgo, fmtTime, fmtTokens } from '../api'
import { useStore } from '../store'
import type { Step } from '../types'

const KIND_COLOR: Record<string, string> = {
  tool: 'cyan',
  response: 'violet',
  milestone: 'teal',
  error: 'red',
  heartbeat: 'gray',
}

export default function AgentDrawer({ name, onClose }: { name: string; onClose: () => void }) {
  const [steps, setSteps] = useState<Step[] | null>(null)
  const { agents } = useStore()
  const row = agents.find((a) => a.agent === name)
  const col = agentColor(name)

  useEffect(() => {
    setSteps(null)
    api<Step[]>(`/steps?agent=${encodeURIComponent(name)}&limit=50`)
      .then((s) => setSteps([...s].reverse())) // newest first
      .catch(() => setSteps([]))
  }, [name])

  return (
    <Drawer
      opened
      onClose={onClose}
      position="right"
      size="md"
      title={
        <div className="flex items-center gap-2.5">
          <span className="w-8 h-8 rounded-lg grid place-items-center text-sm font-bold text-deck" style={{ background: col }}>
            {name[0]}
          </span>
          <span className="font-semibold" style={{ color: col }}>
            {name}
          </span>
          <Badge size="xs" color={row?.alive ? 'teal' : 'gray'} variant="light">
            {row?.alive ? 'live' : `last seen ${fmtAgo(row?.last_seen ?? null)}`}
          </Badge>
        </div>
      }
      styles={{ content: { background: '#0f1630' }, header: { background: '#0f1630' } }}
    >
      {row && (
        <div className="grid grid-cols-3 gap-2 mb-3">
          <div className="bg-deck border border-line rounded-lg p-2 text-center">
            <div className="text-[10px] uppercase tracking-wider text-ink-mute">steps</div>
            <div className="text-sm font-bold font-mono text-ink mt-0.5">{fmtTokens(row.steps)}</div>
          </div>
          <div className="bg-deck border border-line rounded-lg p-2 text-center">
            <div className="text-[10px] uppercase tracking-wider text-ink-mute">tok in</div>
            <div className="text-sm font-bold font-mono text-ink mt-0.5">{fmtTokens(row.tokens_in)}</div>
          </div>
          <div className="bg-deck border border-line rounded-lg p-2 text-center">
            <div className="text-[10px] uppercase tracking-wider text-ink-mute">tok out</div>
            <div className="text-sm font-bold font-mono text-ink mt-0.5">{fmtTokens(row.tokens_out)}</div>
          </div>
        </div>
      )}
      <div className="text-[11px] uppercase tracking-wider text-ink-dim mb-1.5">Recent steps</div>
      <ScrollArea h={row ? 'calc(100dvh - 220px)' : 'calc(100dvh - 140px)'}>
        {steps === null && <div className="text-xs text-ink-mute py-4">loading…</div>}
        {steps?.map((s) => (
          <div key={s.id} className="py-1.5 border-b border-line/50">
            <div className="flex items-center gap-2 text-[11px] text-ink-mute">
              <Badge size="xs" variant="light" color={KIND_COLOR[s.kind] ?? 'gray'}>
                {s.kind}
              </Badge>
              <span>{fmtTime(s.ts)}</span>
              {s.goal_id != null && <span className="font-mono">goal #{s.goal_id}</span>}
              {(s.tokens_in || s.tokens_out) ? (
                <span className="ml-auto font-mono">
                  ↓{fmtTokens(s.tokens_in)} ↑{fmtTokens(s.tokens_out)}
                </span>
              ) : null}
            </div>
            {s.content && <div className="text-[13px] text-ink-dim line-clamp-3 mt-0.5">{s.content}</div>}
          </div>
        ))}
        {steps?.length === 0 && <div className="text-xs text-ink-mute py-4">no steps recorded</div>}
      </ScrollArea>
    </Drawer>
  )
}
