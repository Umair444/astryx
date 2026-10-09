import type { AgentRow, Presence } from '../types'

/* The ONE rule for whether an agent is working, awake or asleep — the Floor, the sidebar and the
   cards all read it, so the room never disagrees with itself. */
export type Mood = 'working' | 'awake' | 'asleep'
export const WORK_WINDOW = 90_000          // a step this recent means "working right now"
export const FRESH_PRESENCE = 20 * 60_000

export function moodOf(a: AgentRow, p: Presence | undefined, now: number): Mood {
  if (!a.alive) return 'asleep'
  // a presence row says "working", but only recent activity proves it: one that's gone quiet for
  // 3 minutes has settled, whatever the row says (the same self-healing rule canvas uses)
  const live = p && p.surface && now - Date.parse(p.updated_at) < 3 * 60_000
  if (live && (p!.state === 'working' || p!.state === 'moving')) return 'working'
  if (a.last_seen && now - Date.parse(a.last_seen) < WORK_WINDOW && a.last_kind !== 'response') return 'working'
  return 'awake'
}

export function surfaceLabel(s: string | null) {
  if (!s) return ''
  if (s.startsWith('canvas:')) return `on canvas #${s.slice(7)}`
  if (s.startsWith('goal:')) return `on goal #${s.slice(5)}`
  if (s.startsWith('thread:')) return 'in a conversation'
  return s
}

// a step that only says a tool finished ("Bash done", "Bash: No-op") is noise, not a description of work
const NOISE = /^(?:[\w.:-]+\s+done|[\w.:-]+:\s*no-?op|mcp__[\w-]+\s+done)$/i

/** What an agent is doing, in one line: its own words (presence) when fresh, else its last step. */
export function nowLine(a: AgentRow, p: Presence | undefined, mood: Mood, now: number): { where: string; line: string } {
  const fresh = p && p.surface && now - Date.parse(p.updated_at) < FRESH_PRESENCE
  const where = fresh ? surfaceLabel(p!.surface) : ''
  const last = a.last_content && !NOISE.test(a.last_content.trim()) ? a.last_content : null
  const line = fresh && p!.say ? p!.say : (last ?? (mood === 'working' ? 'working through its tools…' : mood === 'asleep' ? 'asleep' : 'between tasks'))
  return { where, line }
}
