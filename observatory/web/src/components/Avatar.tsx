import { useId } from 'react'
import { avatarInitial } from '../api'

/* A deterministic portrait, not a letter-in-a-circle. Every astryx agent is a person,
   so its identity mark must be instantly recognizable and unique. From the name we derive
   a stable hash, then paint:
     · a two-stop gradient field (the agent's own hue ± a companion hue)
     · a layered geometric "face" — a brow arc, two eyes at hashed positions, a mouth line —
       so the mark reads as a portrait glyph, calm and premium, never a bootstrap monogram.
   A status ring (green=live, slate=dormant, amber=retired) wraps the frame.
   The same hash seeds both hues and every feature offset, so a name always paints the
   same face, and two different names almost never collide. */

export type AvatarStatus = 'live' | 'dormant' | 'retired'

function hash(name: string): number {
  let h = 2166136261
  for (const c of (name || '?').toUpperCase()) {
    h ^= c.charCodeAt(0)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

const RING: Record<AvatarStatus, string> = {
  live: '#34d399', // emerald
  dormant: '#5b6890', // slate (ink-mute)
  retired: '#e8b339', // amber tombstone
}

export default function Avatar({
  name,
  size = 40,
  status = 'dormant',
  ring = true,
  title,
}: {
  name: string
  size?: number
  status?: AvatarStatus
  ring?: boolean
  title?: string
}) {
  const uid = useId().replace(/:/g, '')
  const h = hash(name)
  // primary + companion hue (30–90° apart) for a living gradient rather than a flat fill
  const hue = h % 360
  const hue2 = (hue + 30 + (h % 60)) % 360
  const light1 = 60 + ((h >> 8) % 12)
  const light2 = 44 + ((h >> 12) % 12)
  const c1 = `hsl(${hue} 70% ${light1}%)`
  const c2 = `hsl(${hue2} 66% ${light2}%)`

  // feature geometry on a 0..100 viewBox, derived deterministically from the hash bits
  const eyeY = 40 + ((h >> 3) % 8)
  const eyeGap = 20 + ((h >> 5) % 10)
  const eyeR = 4 + ((h >> 7) % 3)
  const browLift = 4 + ((h >> 9) % 6)
  const mouthY = 66 + ((h >> 11) % 8)
  const mouthCurve = ((h >> 13) % 14) - 5 // negative = smile, positive = flat/frown
  const mouthW = 18 + ((h >> 15) % 12)
  const cx = 50
  const stroke = `hsl(${hue} 40% 96% / 0.9)`

  const showInitial = size <= 22 // tiny chips read better as a mark; large frames get a face

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      role="img"
      aria-label={title ?? name}
      style={{ display: 'block', flexShrink: 0 }}
    >
      {title && <title>{title}</title>}
      <defs>
        <linearGradient id={`g-${uid}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={c1} />
          <stop offset="100%" stopColor={c2} />
        </linearGradient>
        <radialGradient id={`glow-${uid}`} cx="0.5" cy="0.32" r="0.75">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.28" />
          <stop offset="60%" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* status ring */}
      {ring && (
        <circle cx={cx} cy="50" r="48" fill="none" stroke={RING[status]} strokeWidth={status === 'retired' ? 3 : 4} strokeOpacity={status === 'dormant' ? 0.5 : 0.95} strokeDasharray={status === 'retired' ? '3 4' : undefined} />
      )}

      {/* portrait field */}
      <circle cx={cx} cy="50" r={ring ? 42 : 48} fill={`url(#g-${uid})`} />
      <circle cx={cx} cy="50" r={ring ? 42 : 48} fill={`url(#glow-${uid})`} />

      {showInitial ? (
        <text x="50" y="50" textAnchor="middle" dominantBaseline="central" fontSize="46" fontWeight="700" fill="hsl(0 0% 100% / 0.92)" fontFamily="inherit">
          {avatarInitial(name)}
        </text>
      ) : (
        <g stroke={stroke} strokeLinecap="round" fill="none" strokeWidth="3">
          {/* brow arc — one confident line above the eyes */}
          <path d={`M ${cx - eyeGap - 4} ${eyeY - browLift} Q ${cx} ${eyeY - browLift - 6} ${cx + eyeGap + 4} ${eyeY - browLift}`} strokeOpacity="0.55" />
          {/* eyes */}
          <circle cx={cx - eyeGap / 2} cy={eyeY} r={eyeR} fill={stroke} stroke="none" />
          <circle cx={cx + eyeGap / 2} cy={eyeY} r={eyeR} fill={stroke} stroke="none" />
          {/* mouth — a quadratic whose curve is hashed (personality: smile ↔ set) */}
          <path d={`M ${cx - mouthW / 2} ${mouthY} Q ${cx} ${mouthY + mouthCurve} ${cx + mouthW / 2} ${mouthY}`} strokeOpacity="0.8" />
        </g>
      )}
    </svg>
  )
}
