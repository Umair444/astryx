import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { animate, motion, useMotionValue, useTransform } from 'motion/react'
import AgentFace from '../components/AgentFace'

/* THE KIT — the observatory's one visual language. An astryx org is an agentic system that runs
   itself, so every surface should read as ALIVE: numbers arrive (never a fake 0 while loading),
   things that are working breathe, people are faces, and nothing here knows what any particular
   org does. Views compose these; they don't invent their own panels, stats or headers. */

/* ---------------------------------------------------------------- surfaces */

/** A glass panel. `live` draws a slow scanning light along its top edge — the panel's subject is
 *  working right now. `interactive` lifts it on hover. */
export function Panel({ children, className = '', live = false, interactive = false, onClick, as = 'div' }: {
  children: ReactNode; className?: string; live?: boolean; interactive?: boolean; onClick?: () => void; as?: 'div' | 'button' | 'section'
}) {
  const Tag = as as 'div'
  return (
    <Tag onClick={onClick}
      className={`ax-panel relative rounded-2xl ${interactive ? 'ax-panel-hover cursor-pointer text-left' : ''} ${className}`}>
      {live && <span aria-hidden className="ax-scan" />}
      {children}
    </Tag>
  )
}

/** Every view opens the same way: a title, one live sentence about right now, the faces of
 *  whoever is involved, and the view's own actions. */
export function ViewHeader({ title, kicker, live, faces, actions }: {
  title: string; kicker?: string; live?: ReactNode; faces?: string[]; actions?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end gap-x-4 gap-y-3 mb-6">
      <div className="min-w-0">
        {kicker && <div className="text-[11px] uppercase tracking-[0.18em] text-ink-mute mb-1.5">{kicker}</div>}
        <h1 className="text-[26px] sm:text-[30px] font-semibold tracking-[-0.02em] text-ink leading-none ax-title">{title}</h1>
        {live && <div className="mt-2 text-[13px] text-ink-dim flex flex-wrap items-center gap-x-2 gap-y-1">{live}</div>}
      </div>
      <div className="ml-auto flex items-center gap-3">
        {faces && faces.length > 0 && <FaceStack names={faces} />}
        {actions}
      </div>
    </div>
  )
}

export function SectionHead({ title, count, right }: { title: string; count?: number | string; right?: ReactNode }) {
  return (
    <div className="flex items-center gap-2 mb-3 mt-1">
      <h2 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-ink-dim">{title}</h2>
      {count != null && <span className="text-[11px] font-mono text-ink-mute">{count}</span>}
      <div className="flex-1 h-px bg-gradient-to-r from-line to-transparent" />
      {right}
    </div>
  )
}

/* ---------------------------------------------------------------- numbers */

/** A number that arrives: it counts up from where it was. `undefined` renders a skeleton — a
 *  page must never show 0 for "not loaded yet". */
export function Count({ value, format = (n) => Math.round(n).toLocaleString() }: { value: number | undefined | null; format?: (n: number) => string }) {
  const mv = useMotionValue(0)
  const text = useTransform(mv, (v) => format(v))
  const first = useRef(true)
  useEffect(() => {
    if (value == null) return
    if (first.current) { first.current = false; mv.set(0) }
    const c = animate(mv, value, { duration: 0.9, ease: [0.16, 1, 0.3, 1] })
    return () => c.stop()
  }, [value, mv])
  if (value == null) return <Skeleton className="inline-block h-[0.9em] w-16 align-middle" />
  return <motion.span className="tabular-nums">{text}</motion.span>
}

export function Stat({ label, value, format, sub, spark, tone = 'accent' }: {
  label: string; value: number | undefined | null; format?: (n: number) => string; sub?: ReactNode; spark?: number[]; tone?: Tone
}) {
  return (
    <Panel className="p-4 overflow-hidden">
      <div className="text-[11px] uppercase tracking-[0.14em] text-ink-mute">{label}</div>
      <div className="mt-2 text-[28px] font-semibold tracking-tight text-ink leading-none"><Count value={value} format={format} /></div>
      {sub && <div className="mt-1.5 text-[12px] text-ink-mute">{sub}</div>}
      {spark && spark.length > 1 && <Spark data={spark} tone={tone} className="absolute right-0 bottom-0 w-[55%] h-12 opacity-80" />}
    </Panel>
  )
}

type Tone = 'accent' | 'accent2' | 'good' | 'warn' | 'bad'
const TONE: Record<Tone, string> = { accent: 'var(--t-accent)', accent2: 'var(--t-accent2)', good: 'var(--t-good)', warn: 'var(--t-warn)', bad: 'var(--t-bad)' }

/** A soft area sparkline, oldest first: a smooth curve that draws itself in left to right. */
export function Spark({ data, tone = 'accent', className = '', max: ceil }: { data: number[]; tone?: Tone; className?: string; max?: number }) {
  const id = useRef(`sp${Math.random().toString(36).slice(2, 8)}`).current
  const max = ceil ?? Math.max(1, ...data)   // a fixed ceiling (e.g. 100 for a percent) keeps a steady value from filling the tile
  const W = 100, H = 30
  const pts = data.map((v, i) => [(i / (data.length - 1)) * W, H - 1.5 - (v / max) * (H - 5)] as const)
  // Catmull-Rom → cubic Bézier: a curve through every point, no overshoot below the baseline
  let line = `M${pts[0][0]},${pts[0][1]}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] ?? p2
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, Math.min(H - 1.5, p1[1] + (p2[1] - p0[1]) / 6)]
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, Math.min(H - 1.5, p2[1] - (p3[1] - p1[1]) / 6)]
    line += ` C${c1[0].toFixed(2)},${c1[1].toFixed(2)} ${c2[0].toFixed(2)},${c2[1].toFixed(2)} ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className={className} aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={TONE[tone]} stopOpacity="0.38" />
          <stop offset="1" stopColor={TONE[tone]} stopOpacity="0" />
        </linearGradient>
        <clipPath id={`${id}c`}>
          <motion.rect x="0" y="-2" height={H + 4} initial={{ width: 0 }} animate={{ width: W }} transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1] }} />
        </clipPath>
      </defs>
      <g clipPath={`url(#${id}c)`}>
        <path d={`${line} L${W},${H} L0,${H} Z`} fill={`url(#${id})`} />
        <path d={line} fill="none" stroke={TONE[tone]} strokeWidth="1.5" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      </g>
    </svg>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  // inline by default (a number's placeholder), but a caller's own display/position class wins
  const disp = /(^|\s)(block|flex|grid|absolute|fixed)(\s|$)/.test(className) ? '' : 'inline-block'
  return <span className={`ax-skel rounded-md ${disp} ${className}`} />
}

/* ---------------------------------------------------------------- life */

export type LiveState = 'working' | 'awake' | 'asleep'

export function LiveDot({ state, className = '' }: { state: LiveState; className?: string }) {
  const c = state === 'working' ? 'bg-cyan' : state === 'awake' ? 'bg-good' : 'bg-ink-mute/40'
  return (
    <span className={`relative inline-flex w-2 h-2 ${className}`}>
      {state !== 'asleep' && <span className={`absolute inset-0 rounded-full ${c} opacity-60 animate-ping`} style={{ animationDuration: state === 'working' ? '1.4s' : '2.8s' }} />}
      <span className={`relative w-2 h-2 rounded-full ${c}`} />
    </span>
  )
}

/** Overlapping faces — who is here. */
export function FaceStack({ names, max = 6, size = 28 }: { names: string[]; max?: number; size?: number }) {
  const shown = names.slice(0, max)
  return (
    <div className="flex items-center">
      {shown.map((n, i) => (
        <motion.span key={n} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.04 }}
          className="rounded-full ring-2 ring-[var(--t-bg)]" style={{ marginLeft: i ? -size * 0.3 : 0, zIndex: max - i }}>
          <AgentFace name={n} size={size} />
        </motion.span>
      ))}
      {names.length > max && <span className="ml-1.5 text-[11px] text-ink-mute font-mono">+{names.length - max}</span>}
    </div>
  )
}

/** The breathing orb — what an empty or waiting surface shows instead of a sentence alone. */
export function Orb({ size = 64, tone = 'accent' }: { size?: number; tone?: Tone }) {
  return (
    <span className="ax-orb inline-block rounded-full" aria-hidden
      style={{ width: size, height: size, ['--orb' as string]: TONE[tone] }} />
  )
}

export function Empty({ title, hint, tone = 'accent' }: { title: string; hint?: ReactNode; tone?: Tone }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-14 gap-4">
      <Orb size={56} tone={tone} />
      <div>
        <div className="text-[14px] text-ink-dim">{title}</div>
        {hint && <div className="text-[12px] text-ink-mute mt-1 max-w-sm">{hint}</div>}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- controls */

/** Pill tabs with a sliding indicator. */
export function Tabs<T extends string>({ items, value, onChange, id }: {
  items: readonly { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void; id: string
}) {
  return (
    <div className="ax-panel inline-flex max-w-full overflow-x-auto [scrollbar-width:none] gap-0.5 p-1 rounded-xl">
      {items.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={`relative shrink-0 px-3.5 py-1.5 text-[13px] rounded-lg whitespace-nowrap transition-colors ${value === t.id ? 'text-ink' : 'text-ink-mute hover:text-ink-dim'}`}>
          {value === t.id && (
            <motion.span layoutId={`tab-${id}`} className="absolute inset-0 rounded-lg"
              style={{ background: 'color-mix(in srgb, var(--t-accent) 16%, var(--t-panel2))', boxShadow: 'inset 0 0 0 1px color-mix(in srgb, var(--t-accent) 30%, transparent)' }}
              transition={{ type: 'spring', damping: 30, stiffness: 380 }} />
          )}
          <span className="relative">{t.label}</span>
        </button>
      ))}
    </div>
  )
}

/** The primary action: an accent gradient button. */
export function Action({ children, onClick, disabled, className = '' }: { children: ReactNode; onClick?: () => void; disabled?: boolean; className?: string }) {
  return (
    <button onClick={onClick} disabled={disabled}
      className={`ax-action inline-flex items-center gap-2 px-4 py-2 rounded-xl text-[13px] font-medium disabled:opacity-40 ${className}`}>
      {children}
    </button>
  )
}

/** Re-render on a cadence so relative times ("2m ago") and moods stay true. */
export function useNow(ms = 5000) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(t) }, [ms])
  return now
}
