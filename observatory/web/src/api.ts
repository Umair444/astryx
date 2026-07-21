import type { WhoAmI } from './types'

export async function api<T>(path: string): Promise<T> {
  const key = obsKey()
  const r = await fetch('/api' + path, { headers: key ? { 'x-obs-key': key } : {} })
  if (!r.ok) throw new Error(`${path}: ${r.status}`)
  return r.json()
}

/* obs key — lives in localStorage; empty string means anonymous reader */
export function obsKey(): string {
  return localStorage.getItem('obs_key') ?? ''
}

/* SSE cannot send headers — owner mode rides ?key= (server just filters if wrong) */
export function eventsUrl(): string {
  const key = obsKey()
  return '/api/events' + (key ? `?key=${encodeURIComponent(key)}` : '')
}

export function saveObsKey(key: string) {
  if (key) localStorage.setItem('obs_key', key)
  else localStorage.removeItem('obs_key')
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const key = obsKey()
  const r = await fetch('/api' + path, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...(key ? { 'x-obs-key': key } : {}) },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${path}: ${r.status}`)
  return r.json()
}

/* PUT/DELETE with the owner key — for the SQL workbench's saved files */
export async function apiSend<T>(method: string, path: string, body?: unknown): Promise<T> {
  const key = obsKey()
  const r = await fetch('/api' + path, {
    method,
    headers: {
      ...(body !== undefined ? { 'content-type': 'application/json' } : {}),
      ...(key ? { 'x-obs-key': key } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) throw new Error(`${path}: ${r.status}`)
  return r.json()
}

export async function fetchWhoami(): Promise<WhoAmI> {
  const key = obsKey()
  const r = await fetch('/api/whoami', { headers: key ? { 'x-obs-key': key } : {} })
  if (!r.ok) throw new Error(`/whoami: ${r.status}`)
  return r.json()
}

/* deterministic per-agent hue — no departments in astryx, the name is the identity */
/* The filename stem is the canonical name (wire id, home, tmux); the dashboard
   shows it prettified — separators to spaces, each word capitalized. So
   'abstractor-1' -> 'Abstractor 1', 'seed' -> 'Seed'. Display-only. */
export function displayName(name: string): string {
  return (name || '')
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/* the mark in an agent's avatar chip: a trailing number distinguishes ranked
   members (abstractor-1 -> '1'), otherwise the first letter */
export function avatarInitial(name: string): string {
  const num = (name || '').match(/(\d+)$/)
  return num ? num[1] : (name || '?')[0].toUpperCase()
}

/* 'claude-opus-4-8' -> 'opus 4.8'; a bare pin like 'haiku' passes through */
export function shortModel(id: string | null | undefined): string {
  if (!id) return ''
  const m = /^(?:claude-)?([a-z]+)-(\d+)-(\d+)/.exec(id)
  return m ? `${m[1]} ${m[2]}.${m[3]}` : id.replace(/^claude-/, '')
}

export function agentColor(name: string): string {
  let h = 0
  for (const c of (name || '?').toUpperCase()) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return `hsl(${h % 360} 72% 64%)`
}

/* same hue, custom alpha — for borders and glows */
export function agentColorA(name: string, alpha: number): string {
  let h = 0
  for (const c of (name || '?').toUpperCase()) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return `hsl(${h % 360} 72% 64% / ${alpha})`
}

export function fmtTime(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function fmtDay(ts: string): string {
  const d = new Date(ts)
  const today = new Date()
  const yd = new Date(today.getTime() - 864e5)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === yd.toDateString()) return 'Yesterday'
  return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
}

export function fmtAgo(ts: string | null): string {
  if (!ts) return '—'
  const s = (Date.now() - +new Date(ts)) / 1000
  if (s < 90) return 'now'
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 86400) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

export function fmtTokens(n: number | null | undefined): string {
  const v = n ?? 0
  if (v >= 1e9) return (v / 1e9).toFixed(1) + 'B'
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M'
  if (v >= 1e3) return (v / 1e3).toFixed(1) + 'k'
  return String(v)
}
