import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'

/* HARNESS AND KEYS (owner 11-16; docs/superpowers/specs/2026-11-16-harness-and-keys-design.md). The page's one read,
   GET /api/harness: every fact comes from the server's two tables (providers.json, cli_adapters.json), so a new
   provider or harness shows up here with no change to this code. */

export interface Provider {
  name: string; by: string; auth: 'login' | 'key'; billing: 'subscription' | 'metered'; hex: string; blurb: string
  speaks?: Record<string, string>; native?: string; custom?: boolean; get?: string; check?: unknown
  models: string[]; tiers?: Record<string, string>
}
export interface Harness { id: string; name: string; by: string; ready: boolean; why?: string; speaks: string[]; logins: string[]; signin?: string }
export interface Energy { h5: number | null; h5_reset: string | null; d7: number | null; d7_reset: string | null; age_s: number }
export interface Key {
  name: string; provider: string; kind: 'login' | 'key'; base_url?: string; format?: string
  models?: Record<string, string>; cap_tokens_day?: number; has_value: boolean; used_by: string[]
  fits: string[]; why_not: Record<string, string | null>; energy: Energy | null; spent_today: number | null
}
export interface Connection { harness?: string; credential?: string; model?: string; effort?: string }
export interface AgentRow { name: string; own: boolean; alive: boolean; connection: Connection }
export interface State {
  harnesses: Harness[]; providers: Record<string, Provider>; keys: Key[]
  org: { billing: 'subscription' | 'metered' | 'ambient'; harness: string; energy: Energy | null }
  default: Connection; agents: AgentRow[]
}

export function useHarness(on = true) {
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState<string | null>(null)
  const reload = useCallback(() => {
    if (on) api<State>('/harness').then((s) => { setState(s); setError(null) }).catch((e) => setError((e as Error).message))
  }, [on])
  useEffect(reload, [reload])
  return { state, setState, error, reload }
}

export const EVERYONE = '*'
export const harnessOf = (s: State, c: Connection) => s.harnesses.find((h) => h.id === (c.harness || s.org.harness)) ?? s.harnesses[0]
export const keyOf = (s: State, c: Connection) => s.keys.find((k) => k.name === c.credential) ?? null

/** The org's own login, in words: what an agent with no key of its own runs on. */
export const orgWord = (s: State) =>
  s.org.billing === 'subscription' ? "The org's login" : s.org.billing === 'metered' ? "The org's API key" : "This machine's login"

/** How much of a login's limits is left, the tighter window first ("54% left"), or null when unread. */
export function left(e: Energy | null): { pct: number; window: string; reset: string | null } | null {
  if (!e || e.h5 == null) return null
  const h5 = 100 - e.h5, d7 = e.d7 == null ? 100 : 100 - e.d7
  return h5 <= d7 ? { pct: Math.max(0, Math.round(h5)), window: '5-hour', reset: e.h5_reset } : { pct: Math.max(0, Math.round(d7)), window: 'weekly', reset: e.d7_reset }
}

export function resetIn(iso: string | null): string {
  if (!iso) return ''
  const m = Math.round((new Date(iso).getTime() - Date.now()) / 60000)
  if (m <= 0) return 'resetting now'
  return m < 60 ? `resets in ${m} min` : m < 48 * 60 ? `resets in ${Math.round(m / 60)} h` : `resets in ${Math.round(m / 1440)} days`
}
