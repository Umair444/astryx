import { useEffect, useState } from 'react'
import { Drawer, ScrollArea } from '@mantine/core'
import { api, agentColor, displayName, fmtTokens, shortModel } from '../api'
import type { TurnDetail } from '../types'

/* The signature move (plan-2 §5): any rendered message/turn peels open into the
   turn that produced it — trigger → interleaved reasoning + tool chips → outputs,
   with tokens, duration, and the causal links. One component, reused everywhere. */

function fmtDur(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  return s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
}

export default function TurnPeek({
  turnId,
  onClose,
  onOpenTurn,
}: {
  turnId: number | null
  onClose: () => void
  onOpenTurn?: (id: number) => void
}) {
  const [d, setD] = useState<TurnDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    setD(null)
    setErr(null)
    if (turnId != null)
      api<TurnDetail>(`/turns/${turnId}`).then(setD).catch((e) => setErr(String(e)))
  }, [turnId])

  return (
    <Drawer
      opened={turnId != null}
      onClose={onClose}
      position="right"
      size="lg"
      title={
        d ? (
          <span className="flex items-center gap-2">
            <span
              className="w-6 h-6 rounded-lg grid place-items-center text-[11px] font-bold text-deck"
              style={{ background: agentColor(d.agent) }}
            >
              {d.agent[0].toUpperCase()}
            </span>
            <span className="text-sm text-ink">
              {displayName(d.agent)} · turn #{d.id}
            </span>
            <span className="text-[10px] font-mono text-ink-mute">
              {shortModel(d.model)} · {fmtDur(d.duration_ms)} · {fmtTokens(d.tokens_out)} out
            </span>
          </span>
        ) : (
          `turn #${turnId ?? ''}`
        )
      }
      styles={{ content: { background: '#0b1020' }, header: { background: '#0b1020' } }}
    >
      {err && <div className="text-sm text-red-400 font-mono">{err}</div>}
      {!d && !err && <div className="text-sm text-ink-mute">opening the turn…</div>}
      {d && (
        <ScrollArea className="h-full">
          <div className="space-y-3 pb-8">
            {/* the trigger — what woke this mind */}
            <div className="rounded-lg border border-line bg-deck-2 p-3">
              <div className="text-[10px] uppercase tracking-[0.15em] text-ink-mute mb-1.5">
                trigger {d.trigger ? `· msg #${d.trigger.id} · ${d.trigger.from_agent} → ${d.agent}` : `· ${d.source ?? 'self'}`}
                {d.trigger?.thread && <span className="ml-1 font-mono">({d.trigger.thread})</span>}
              </div>
              <div className="text-[12px] text-ink-dim whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                {(d.trigger?.body ?? d.input_prompt ?? '(self-initiated)').slice(0, 1500)}
              </div>
            </div>

            {/* the thinking — interleaved responses and tool chips, in order */}
            <div className="space-y-2">
              {d.events.map((e, i) =>
                e.kind === 'tool' ? (
                  <div key={i} className="flex items-center gap-2 pl-3">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400/70 shrink-0" />
                    <span className="text-[11px] font-mono text-amber-200/70 truncate">
                      {e.name}
                      {e.brief ? ` · ${e.brief}` : ''}
                    </span>
                  </div>
                ) : (
                  <div key={i} className="rounded-lg border border-line/60 bg-deck-3/40 p-3">
                    <div className="text-[12.5px] text-ink leading-relaxed whitespace-pre-wrap break-words">
                      {e.text}
                    </div>
                  </div>
                ),
              )}
              {!d.events.length && (
                <div className="text-[12px] text-ink-mute">(no recorded events — a silent turn)</div>
              )}
            </div>

            {/* the outputs — what left this turn onto the wire */}
            {d.outputs.length > 0 && (
              <div className="rounded-lg border border-cyan/20 bg-deck-2 p-3">
                <div className="text-[10px] uppercase tracking-[0.15em] text-cyan-soft/70 mb-1.5">
                  sent from this turn
                </div>
                {d.outputs.map((o) => (
                  <div key={o.id} className="text-[12px] text-ink-dim mb-1.5">
                    <span className="font-mono text-[10px] text-ink-mute">
                      #{o.id} → {o.to_org && o.to_org !== 'local' ? `${o.to_agent}@${o.to_org}` : o.to_agent}
                      {o.thread ? ` (${o.thread})` : ''}:
                    </span>{' '}
                    {o.body}
                  </div>
                ))}
              </div>
            )}

            <div className="text-[10px] font-mono text-ink-mute px-1">
              {d.started_at ? new Date(d.started_at).toLocaleString() : ''} · in {fmtTokens(d.tokens_in)} / out{' '}
              {fmtTokens(d.tokens_out)} tok
              {onOpenTurn && d.trigger && (
                <span> · trigger msg #{d.trigger.id}</span>
              )}
            </div>
          </div>
        </ScrollArea>
      )}
    </Drawer>
  )
}
