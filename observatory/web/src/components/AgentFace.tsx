import { useState } from 'react'
import Avatar, { type AvatarStatus } from './Avatar'
import { displayName } from '../api'
import { focusBase, safeBase } from '../cog'

/* An agent's FACE: the avatar it authored for itself (agents/<x>/avatar.svg, mandatory since
   2026-10-09), served at /api/agents/<x>/avatar. Anyone without one — a human on a channel, a
   peer, an agent that hasn't drawn itself yet — gets the deterministic generated portrait, so
   no face is ever a bare letter. One component for every surface: a person looks the same
   in the sidebar, the wire, the network and the profile. */

/* faces known to be missing, for five minutes: the same window as the server's 204 (max-age 300), so a face an agent
   draws shows on the next mount after that, in a tab left open as after a reload (medic 15039). Kept in memory only: a
   browser-stored list kept a miss for six hours, and three new seats' faces stayed hidden all evening (owner 15017) */
const MISS_TTL = 5 * 60_000
const missing = new Map<string, number>()
const missingNow = (k: string) => { const t = missing.get(k); return t !== undefined && Date.now() - t < MISS_TTL }
function markMissing(k: string) { missing.set(k, Date.now()) }
try { localStorage.removeItem('ax_face_missing') } catch { /* the old six-hour list: nothing reads it now */ }
const HUMAN = /^(owner|(wa|tg|dc|cv|canvas)-.+)$|@/

const RING: Record<AvatarStatus, string> = { live: 'var(--t-good)', dormant: 'var(--t-mute)', retired: 'var(--t-warn)' }

export default function AgentFace({ name, size = 32, radius = '9999px', dim = false, title, status, base }: {
  name: string
  size?: number
  radius?: string
  dim?: boolean
  title?: string
  status?: AvatarStatus      // a status ring (live / dormant / retired), as the people page shows
  base?: string              // a cog's room (/o/<org>/): its agent's face from ITS backend; only a base safeBase admits
}) {
  if (status) {
    const pad = Math.max(2, Math.round(size / 16))
    return (
      <span className="shrink-0 inline-grid place-items-center" title={title ?? displayName(name)}
        style={{ width: size, height: size, borderRadius: radius, padding: pad,
                 boxShadow: `0 0 0 ${pad}px ${RING[status]}`, opacity: status === 'dormant' ? 0.85 : 1,
                 outline: status === 'retired' ? `1px dashed ${RING.retired}` : undefined }}>
        <AgentFace name={name} size={size - pad * 2} radius={radius} dim={dim} title={title} base={base} />
      </span>
    )
  }
  // every org has a seed: a face missing in one room is not missing in another
  const room = base && safeBase(base) ? base : focusBase()   // in a cog the focused org's own base; one org: /
  const mk = room === '/' ? name : room + name
  const [failed, setFailed] = useState(() => missingNow(mk))
  const style = { width: size, height: size, borderRadius: radius, opacity: dim ? 0.55 : 1 }
  if (!name || HUMAN.test(name) || failed) {
    return (
      <span className="shrink-0 overflow-hidden inline-block" style={style} title={title ?? displayName(name)}>
        <Avatar name={name || '?'} size={size} ring={false} />
      </span>
    )
  }
  return (
    <img
      src={`${room}api/agents/${encodeURIComponent(name)}/avatar`}
      alt={name}
      title={title ?? displayName(name)}
      width={size}
      height={size}
      draggable={false}
      onError={() => { markMissing(mk); setFailed(true) }}
      className="shrink-0 object-cover select-none"
      style={{ ...style, boxShadow: '0 0 0 1px var(--t-line2)' }}
    />
  )
}
