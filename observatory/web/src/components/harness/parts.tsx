import type { ReactNode } from 'react'
import type { Energy, Harness, Provider } from './model'
import { left, resetIn } from './model'

/* The small pieces every Harness and Keys surface shares: a provider's mark, a harness chip, a login's energy. */

/** A provider's mark: its initial on its own colour (the catalog's `hex`). Marks, not logos: no trademark is copied. */
export function Mark({ p, size = 32 }: { p: Provider | undefined; size?: number }) {
  const hex = p?.hex ?? 'var(--t-mute)'
  return (
    <span aria-hidden className="shrink-0 grid place-items-center font-semibold select-none"
      style={{ width: size, height: size, borderRadius: size * 0.3, fontSize: size * 0.44, color: hex,
               background: `color-mix(in srgb, ${hex} 16%, transparent)`, boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${hex} 30%, transparent)` }}>
      {(p?.name ?? '?').slice(0, 1)}
    </span>
  )
}

/** A harness: ready ones carry a live dot; one that isn't ready says so and why on hover. */
export function HarnessChip({ h, active, onClick, disabled }: { h: Harness; active?: boolean; onClick?: () => void; disabled?: boolean }) {
  const Tag = onClick ? 'button' : 'span'
  return (
    <Tag type={onClick ? 'button' : undefined} onClick={onClick} disabled={disabled} title={h.ready ? `${h.name} by ${h.by}` : h.why}
      aria-pressed={onClick ? !!active : undefined}
      className={`inline-flex items-center gap-2 rounded-full pl-2.5 pr-3 py-1 text-[12.5px] border transition-colors
        ${active ? 'border-[color-mix(in_srgb,var(--t-accent)_60%,var(--t-line))] bg-[color-mix(in_srgb,var(--t-accent)_12%,transparent)] text-ink'
                 : 'border-line text-ink-dim'} ${onClick && !disabled ? 'hover:border-line-2 hover:text-ink' : ''} disabled:opacity-45 disabled:cursor-not-allowed`}>
      <span className={`w-1.5 h-1.5 rounded-full ${h.ready ? 'bg-good shadow-[0_0_8px_var(--t-good)]' : 'bg-ink-mute'}`} />
      {h.name}
      {!h.ready && <span className="text-[11px] text-ink-mute">soon</span>}
    </Tag>
  )
}

/** A login's energy: a thin bar of what's left of its tighter window, and when it resets. */
export function EnergyBar({ e, compact = false }: { e: Energy | null; compact?: boolean }) {
  const l = left(e)
  if (!l) return <span className="text-[12px] text-ink-mute">no reading yet</span>
  const tone = l.pct < 15 ? 'var(--t-bad)' : l.pct < 35 ? 'var(--t-warn)' : 'var(--t-good)'
  return (
    <span className="inline-flex items-center gap-2 min-w-0" title={`${l.pct}% of the ${l.window} limit left · ${resetIn(l.reset)}`}>
      <span className="relative h-1.5 w-16 rounded-full overflow-hidden bg-[color-mix(in_srgb,var(--t-line)_70%,transparent)]">
        <span className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-700" style={{ width: `${l.pct}%`, background: tone }} />
      </span>
      <span className="text-[12px] tabular-nums text-ink-dim whitespace-nowrap">{l.pct}% left{compact ? '' : ` · ${resetIn(l.reset)}`}</span>
    </span>
  )
}

/** An API key's day: what its agents have used against its daily cap, refilled at the org's midnight. */
export function SpendBar({ spent, cap, compact = false }: { spent: number; cap: number; compact?: boolean }) {
  const pct = cap > 0 ? Math.min(100, Math.round((100 * spent) / cap)) : 100
  const tone = pct >= 85 ? 'var(--t-bad)' : pct >= 65 ? 'var(--t-warn)' : 'var(--t-good)'
  const words = pct >= 100 ? "today's cap is used up" : `${100 - pct}% of today's cap left`
  return (
    <span className="inline-flex items-center gap-2 min-w-0" title={`${Math.round(spent).toLocaleString()} of ${cap.toLocaleString()} tokens today · refills at midnight`}>
      <span className="relative h-1.5 w-16 rounded-full overflow-hidden bg-[color-mix(in_srgb,var(--t-line)_70%,transparent)]">
        <span className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-700" style={{ width: `${100 - pct}%`, background: tone }} />
      </span>
      <span className="text-[12px] tabular-nums text-ink-dim whitespace-nowrap">{words}{compact || pct >= 100 ? '' : ' · refills at midnight'}</span>
    </span>
  )
}

export const field = 'w-full rounded-lg bg-transparent border border-line px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-mute outline-none focus:border-[color-mix(in_srgb,var(--t-accent)_55%,var(--t-line))]'
export const quiet = 'rounded-lg px-3 py-1.5 text-[12.5px] font-medium text-ink border border-line hover:border-line-2 disabled:opacity-40'

export function Label({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <span className="flex items-baseline justify-between gap-2 text-[12px] text-ink-dim mb-1">
      <span>{children}</span>{hint && <span className="text-ink-mute">{hint}</span>}
    </span>
  )
}
