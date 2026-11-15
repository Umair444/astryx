import { isHuman, type Msg, type Step } from '../../types'

/* WHO IS WORKING ON AN ASK HERE (the live line's input; pure, so tests/chat_pending_test.ts runs it under node).
   For each agent in the chat: the newest row a HUMAN sent it on this thread (anyone's: the org has no walls inside,
   so every viewer of the thread sees the agent at work), if the agent hasn't spoken here since. Its live steps since
   that ask feed the line; `by` names the asker when it isn't the viewer, so the line reads "for Faran".
   11-15: this compared from to the literal 'owner', and a member's ask drew no line at all through 11 minutes of work. */
export interface Pending { agent: string; since: string; steps: Step[]; by?: string }

export function pendingOf(agents: string[], rows: Msg[], live: Record<string, Step[]> | undefined, me: string): Pending[] {
  const out: Pending[] = []
  for (const a of agents) {
    const ask = [...rows].reverse().find((m) => isHuman(m.from) && m.to === a)
    const saidAt = Math.max(0, ...rows.filter((m) => m.from === a).map((m) => m.id))
    if (!ask || ask.id <= saidAt) continue
    const t0 = Date.parse(ask.ts)
    out.push({ agent: a, since: ask.ts, by: ask.from === me ? undefined : ask.from!,
               steps: (live?.[a] ?? []).filter((s) => Date.parse(s.ts) >= t0) })
  }
  return out
}
