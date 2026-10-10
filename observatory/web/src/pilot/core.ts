/* plan-9000 S1: the pilot's executor core. Pure (no React, no imports) so node runs its tests directly
   (tests/pilot_core_test.ts) and the browser, the palette and later the voice share one gate.

   THE PRINCIPAL IS NEVER A VALUE A CALLER PASSES (a1 #44141 R1). createExecutor() returns one entry point per
   transport, made once here: `owner` (the palette, in a tab holding the key), `visitor` (the palette without it),
   `room` (the realtime model), `agent` (S4's command rows). Each runs only what the matrix grants ITS principal:
     · unknown action, or args failing the schema → refused (C2: the model's args are untrusted);
     · matrix[principal][class]; a missing cell is DENY, a missing class reads as actuate (R6);
     · "allow" runs; "projection" runs only when a projector is installed (S2's egress wrapper) and returns the
       projected result, else it is refused (fail closed: no projector, no read for the room);
     · "confirm" runs NOTHING: the call becomes the ONE pending confirm, with a nonce kept in this module only
       (R4: the caller learns "pending_owner_confirm", never the nonce, so it never reaches the provider).
   Write and actuate then run ONLY through confirm(nonce, event), which checks the event itself (#44109):
   isTrusted, a pointer (mouse / touch / pen: keyboard is refused), its currentTarget the very element bound to
   that nonce, and its timeStamp at least CONFIRM_ARM_MS after that element was bound. A new request replaces the
   pending one, so a tap aimed at an old prompt never runs a new call (a4 #44113 arm v). */

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
export type Handler = (args: Record<string, Json>) => Json | void | Promise<Json | void>
export interface Pending { nonce: string; action: string; args: Record<string, Json>; at: number }
export type Outcome =
  | { status: 'done'; action: string; result: Json; ms: number }
  | { status: 'pending_owner_confirm'; action: string }
  | { status: 'refused'; action: string; reason: string }
  | { status: 'failed'; action: string; reason: string }
/** The fields of a DOM click the confirm checks. Typed loosely so node can test it. */
export interface TapEvent { isTrusted: boolean; pointerType?: string; currentTarget: unknown; timeStamp: number }

/** The keywords validate() implements. A schema using any other keyword is a catalog error (the test checks). */
export const KEYWORDS = ['type', 'properties', 'required', 'additionalProperties', 'enum', 'minLength', 'maxLength',
  'minimum', 'maximum'] as const
/** A confirm control is inert this long after it is bound: a click already in flight can't land on it. */
export const CONFIRM_ARM_MS = 500
const POINTERS = ['mouse', 'touch', 'pen']

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

export interface ExecutorOpts {
  onPending?: (p: Pending | null) => void
  /** S2's egress projection for the room's reads; absent means the room reads nothing. */
  project?: (action: string, result: Json) => Json | null
  /** The clock event timeStamps share (performance.now in a page). */
  clock?: () => number
}

export function createExecutor(catalog: Catalog, handlers: Record<string, Handler>, opts: ExecutorOpts = {}) {
  const byName = new Map(catalog.actions.map((a) => [a.name, a]))
  const clock = opts.clock ?? now
  let pending: Pending | null = null
  let bound: { nonce: string; el: unknown; at: number } | null = null
  const times: Record<string, number[]> = {}
  const log: { action: string; at: number }[] = []
  const setPending = (p: Pending | null) => { pending = p; bound = null; opts.onPending?.(p) }

  async function execute(a: Action, args: Record<string, Json>): Promise<Outcome> {
    const h = handlers[a.name]
    if (!h) return { status: 'refused', action: a.name, reason: 'no handler for this action' }
    const t0 = now()
    log.push({ action: a.name, at: Date.now() })
    if (log.length > 50) log.shift()
    try {
      const result = ((await h(args)) ?? null) as Json
      const ms = now() - t0
      ;(times[a.name] ??= []).push(ms)
      if (times[a.name].length > 200) times[a.name].shift()
      return { status: 'done', action: a.name, result, ms }
    } catch (e) {
      return { status: 'failed', action: a.name, reason: e instanceof Error ? e.message : String(e) }
    }
  }

  function entry(principal: string) {
    return async function run(name: string, args?: unknown): Promise<Outcome> {
      const a = byName.get(name)
      if (!a) return { status: 'refused', action: name, reason: 'unknown action' }
      const bad = validate(a.parameters, args ?? {})
      if (bad) return { status: 'refused', action: name, reason: bad }
      const cls = a.class && catalog.classes.includes(a.class) ? a.class : 'actuate'
      const cell = catalog.matrix[principal]?.[cls]
      const clean = (args ?? {}) as Record<string, Json>
      if (cell === 'allow') return execute(a, clean)
      if (cell === 'projection') {
        if (!opts.project) return { status: 'refused', action: name, reason: 'not readable by voice yet' }
        const out = await execute(a, clean)
        if (out.status !== 'done') return out
        const shown = opts.project(name, out.result)
        return shown === null ? { status: 'refused', action: name, reason: 'not readable by voice' } : { ...out, result: shown }
      }
      if (cell === 'confirm') {
        setPending({ nonce: newNonce(), action: name, args: clean, at: Date.now() })
        return { status: 'pending_owner_confirm', action: name }
      }
      return { status: 'refused', action: name, reason: `${principal} may not ${cls}` }
    }
  }

  /** The confirm control for `nonce` is on screen as `el`; it arms CONFIRM_ARM_MS from now. */
  function bindConfirm(nonce: string, el: unknown): boolean {
    if (!pending || pending.nonce !== nonce || !el) return false
    bound = { nonce, el, at: clock() }
    return true
  }

  /** The owner's tap on the confirm control. Runs the pending call once, only for a trusted pointer click on the
   *  element bound to that nonce, after it armed. Anything else runs nothing and leaves the prompt as it was. */
  async function confirm(nonce: string, ev?: TapEvent | null): Promise<Outcome> {
    const p = pending
    const refuse = (reason: string): Outcome => ({ status: 'refused', action: p?.action ?? '', reason })
    if (!p || p.nonce !== nonce) return refuse('that prompt is no longer pending')
    // in a page, only the browser's own Event (a plain object can claim isTrusted; a real Event can't)
    if (!ev || (typeof window !== 'undefined' && !(ev instanceof Event)) || ev.isTrusted !== true) return refuse('not a real tap')
    if (!POINTERS.includes((ev as TapEvent).pointerType ?? '')) return refuse('confirm by clicking or tapping, not a key')
    if (!bound || bound.nonce !== nonce || ev.currentTarget !== bound.el) return refuse('that tap was not on this prompt')
    if (ev.timeStamp - bound.at < CONFIRM_ARM_MS) return refuse('too soon after the prompt appeared')
    setPending(null)
    const a = byName.get(p.action)
    return a ? execute(a, p.args) : refuse('unknown action')
  }

  function dismiss(nonce: string) { if (pending?.nonce === nonce) setPending(null) }

  /** p50 / p95 per action in ms, from the last 200 runs (C6 f). */
  function metrics() {
    const q = (xs: number[], f: number) => { const s = [...xs].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(f * s.length))] }
    return Object.fromEntries(Object.entries(times).map(([k, xs]) => [k, { n: xs.length, p50: q(xs, 0.5), p95: q(xs, 0.95) }]))
  }

  return {
    owner: { run: entry('owner') },
    visitor: { run: entry('visitor') },
    room: { run: entry('room') },
    agent: { run: entry('agent') },
    bindConfirm, confirm, dismiss, metrics,
    pending: () => pending,
    ran: () => log.slice(),
    actions: catalog.actions,
  }
}
export type Executor = ReturnType<typeof createExecutor>
