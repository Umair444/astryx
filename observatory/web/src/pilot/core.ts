/* plan-9000 S1: the pilot's executor core. Pure (no React, no DOM, no imports) so node runs its tests directly
   (tests/pilot_core_test.ts) and the browser, the palette and later the voice share one gate.

   Every call names an action from observatory/pilot/catalog.json and a PRINCIPAL. The executor:
     1. refuses an unknown action, or args that fail the action's schema (C2: the model's args are untrusted);
     2. looks up matrix[principal][class]; a missing cell is DENY, a missing class reads as actuate (R6);
     3. "allow" runs the handler; "projection" runs it and marks the result for S2's egress wrapper;
        "confirm" runs NOTHING: it parks the call as the ONE pending confirm with a fresh nonce, and only
        confirm(nonce) from the owner's tap (principal owner_tap, a control rendered after the request) runs it.
   A new confirm request replaces the pending one (new nonce), so a tap aimed at an old prompt never runs a new
   call (a4 #44113 arm v). */

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json }
export interface Schema {
  type?: 'object' | 'string' | 'integer' | 'number' | 'boolean'
  properties?: Record<string, Schema>
  required?: string[]
  additionalProperties?: boolean
  enum?: Json[]
  minLength?: number
  maxLength?: number
  minimum?: number
  maximum?: number
}
export interface Action { name: string; class?: string; description: string; parameters: Schema }
export interface Catalog { classes: string[]; matrix: Record<string, Record<string, string>>; actions: Action[] }
export type Principal = 'owner_tap' | 'visitor' | 'room' | 'agent' | 'anonymous' | 'peer'
export type Handler = (args: Record<string, Json>) => Json | void | Promise<Json | void>
export interface Pending { nonce: string; action: string; args: Record<string, Json>; at: number }
export type Outcome =
  | { status: 'done'; action: string; result: Json; projection?: true; ms: number }
  | { status: 'needs_confirm'; action: string; nonce: string }
  | { status: 'refused'; action: string; reason: string }
  | { status: 'failed'; action: string; reason: string }

/** The keywords validate() implements. A schema using any other keyword is a catalog error (the test checks). */
export const KEYWORDS = ['type', 'properties', 'required', 'additionalProperties', 'enum', 'minLength', 'maxLength',
  'minimum', 'maximum'] as const

/** Strict validation: the first problem as a sentence, or null when the value fits. */
export function validate(s: Schema, v: unknown, at = 'args'): string | null {
  if (s.enum && !s.enum.some((e) => e === v)) return `${at}: ${JSON.stringify(v)} is not one of ${JSON.stringify(s.enum)}`
  switch (s.type) {
    case 'object': {
      if (typeof v !== 'object' || v === null || Array.isArray(v)) return `${at}: expected an object`
      const o = v as Record<string, unknown>
      for (const k of s.required ?? []) if (!(k in o)) return `${at}.${k}: required`
      for (const k of Object.keys(o)) {
        const sub = s.properties?.[k]
        if (!sub) { if (s.additionalProperties === false) return `${at}.${k}: not allowed`; continue }
        const e = validate(sub, o[k], `${at}.${k}`)
        if (e) return e
      }
      return null
    }
    case 'string':
      if (typeof v !== 'string') return `${at}: expected a string`
      if (s.minLength !== undefined && v.length < s.minLength) return `${at}: shorter than ${s.minLength}`
      if (s.maxLength !== undefined && v.length > s.maxLength) return `${at}: longer than ${s.maxLength}`
      return null
    case 'integer':
    case 'number':
      if (typeof v !== 'number' || !Number.isFinite(v) || (s.type === 'integer' && !Number.isInteger(v))) return `${at}: expected ${s.type === 'integer' ? 'an integer' : 'a number'}`
      if (s.minimum !== undefined && v < s.minimum) return `${at}: below ${s.minimum}`
      if (s.maximum !== undefined && v > s.maximum) return `${at}: above ${s.maximum}`
      return null
    case 'boolean':
      return typeof v === 'boolean' ? null : `${at}: expected true or false`
    default:
      return s.enum ? null : `${at}: schema has no type`
  }
}

const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now())
const newNonce = () => (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`)

export function createExecutor(catalog: Catalog, handlers: Record<string, Handler>, opts: { onPending?: (p: Pending | null) => void } = {}) {
  const byName = new Map(catalog.actions.map((a) => [a.name, a]))
  let pending: Pending | null = null
  const times: Record<string, number[]> = {}
  const setPending = (p: Pending | null) => { pending = p; opts.onPending?.(p) }

  async function execute(a: Action, args: Record<string, Json>, projection: boolean): Promise<Outcome> {
    const h = handlers[a.name]
    if (!h) return { status: 'refused', action: a.name, reason: 'no handler for this action' }
    const t0 = now()
    try {
      const result = ((await h(args)) ?? null) as Json
      const ms = now() - t0
      ;(times[a.name] ??= []).push(ms)
      if (times[a.name].length > 200) times[a.name].shift()
      return projection ? { status: 'done', action: a.name, result, projection: true, ms } : { status: 'done', action: a.name, result, ms }
    } catch (e) {
      return { status: 'failed', action: a.name, reason: e instanceof Error ? e.message : String(e) }
    }
  }

  /** Run one call as `who`. Never throws. */
  async function run(name: string, args: unknown, who: Principal): Promise<Outcome> {
    const a = byName.get(name)
    if (!a) return { status: 'refused', action: name, reason: 'unknown action' }
    const bad = validate(a.parameters, args ?? {})
    if (bad) return { status: 'refused', action: name, reason: bad }
    const cls = a.class && catalog.classes.includes(a.class) ? a.class : 'actuate'
    const cell = catalog.matrix[who]?.[cls]
    const clean = (args ?? {}) as Record<string, Json>
    if (cell === 'allow') return execute(a, clean, false)
    if (cell === 'projection') return execute(a, clean, true)
    if (cell === 'confirm') {
      const p = { nonce: newNonce(), action: name, args: clean, at: Date.now() }
      setPending(p)
      return { status: 'needs_confirm', action: name, nonce: p.nonce }
    }
    return { status: 'refused', action: name, reason: `${who} may not ${cls}` }
  }

  /** The owner tapped the confirm control for `nonce`. Runs the pending call once, only if it is still the pending one. */
  async function confirm(nonce: string): Promise<Outcome> {
    const p = pending
    if (!p || p.nonce !== nonce) return { status: 'refused', action: p?.action ?? '', reason: 'that prompt is no longer pending' }
    setPending(null)
    return run(p.action, p.args, 'owner_tap')
  }

  function dismiss(nonce: string) { if (pending?.nonce === nonce) setPending(null) }

  /** p50 / p95 per action in ms, from the last 200 runs (C6 f). */
  function metrics() {
    const q = (xs: number[], f: number) => { const s = [...xs].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(f * s.length))] }
    return Object.fromEntries(Object.entries(times).map(([k, xs]) => [k, { n: xs.length, p50: q(xs, 0.5), p95: q(xs, 0.95) }]))
  }

  return { run, confirm, dismiss, metrics, pending: () => pending, actions: catalog.actions }
}
export type Executor = ReturnType<typeof createExecutor>
