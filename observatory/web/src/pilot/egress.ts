/* plan-9000 S2, C1: what may leave this page for the realtime provider. Pure, so node tests it.

   project() is the executor's projector for the ROOM's reads (matrix room/read = projection). It is an
   ALLOWLIST per action: a field it does not name never leaves, whatever the handler returned. An action it does
   not know returns null, so the executor refuses it (fail closed).
     · get_usage: the owner's line (a4 #44261): the USAGE_ALLOWLIST gauge fields only, percentages and reset
       times; dollars and spend are absent by construction (never named here).
     · list_goals: id, title, state and the owner agent only (a4 #44261); never a body or scope_note.
   functionOutput() turns an executor outcome into the function_call_output the provider sees. A pending confirm
   says only that the owner must tap (R4: never the nonce). */
import type { Json, Outcome } from './core'

const num = (v: Json | undefined) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: Json | undefined, n = 200) => (typeof v === 'string' ? v.slice(0, n) : null)

export function project(action: string, result: Json): Json | null {
  const r = (result && typeof result === 'object' && !Array.isArray(result) ? result : {}) as Record<string, Json>
  if (action === 'get_usage') {
    if (typeof r.state === 'string') return { state: str(r.state, 40) }
    return {
      five_hour_pct: num(r.five_hour_pct), seven_day_pct: num(r.seven_day_pct),
      five_hour_reset: str(r.five_hour_reset, 40), seven_day_reset: str(r.seven_day_reset, 40),
      age_seconds: num(r.age_seconds),
    }
  }
  if (action === 'list_goals') {
    const goals = Array.isArray(r.goals) ? r.goals : []
    return {
      state: str(r.state, 20), count: num(r.count),
      goals: goals.slice(0, 12).map((g) => {
        const o = (g && typeof g === 'object' && !Array.isArray(g) ? g : {}) as Record<string, Json>
        return { id: num(o.id), title: str(o.title, 140), state: str(r.state, 20), owner: str(o.owner, 64) }
      }),
    }
  }
  return null
}

export function functionOutput(o: Outcome): Json {
  if (o.status === 'done') return { ok: true, result: o.result }
  if (o.status === 'pending_owner_confirm') return { ok: false, waiting: 'the owner must tap Allow on the screen' }
  return { ok: false, error: o.reason.slice(0, 200) }
}
