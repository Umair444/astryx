import { isHuman, type Msg, type Step } from '../../types'

/* WHO IS WORKING ON THIS CONVERSATION (the live line's input; pure, so tests/chat_pending_test.ts runs it under node).
   Two ways an agent is at work here, the way Claude Code shows a turn until it ends:
   (a) ASKED: a human's newest row to it here (anyone's: the org has no walls inside) that it hasn't spoken after.
   (b) ITS OPEN TURN SERVES THIS THREAD: its live lane (steps since its last turn ended, /api/chat/work) carries a step
       whose turn a message on this thread opened (step.turn_msgs, hooks/step.py), and no later step belongs to a turn
       another thread opened. An agent that REPLIED and kept working stays on the line (owner 11-15: "db replied but
       is still working … I'm not seeing anything"). A step stamped [] (the turn absorbed a message mid-way) is still
       this turn's.
   `steps`: the lane from where this turn's work starts (b), or since the ask (a). `by` names the asker when it isn't
   the viewer, so the line reads "for Faran". 11-15: (a) once compared from to the literal 'owner'. */
export interface Pending { agent: string; since: string; steps: Step[]; by?: string }

export function pendingOf(agents: string[], rows: Msg[], live: Record<string, Step[]> | undefined, me: string): Pending[] {
  const out: Pending[] = []
  const here = new Set(rows.map((m) => m.id))
  const serves = (s: Step) => !!s.turn_msgs?.some((id) => here.has(id))
  const elsewhere = (s: Step) => !!s.turn_msgs?.length && !serves(s)
  for (const a of agents) {
    const lane = live?.[a] ?? []
    const ask = [...rows].reverse().find((m) => isHuman(m.from) && m.to === a)
    const saidAt = Math.max(0, ...rows.filter((m) => m.from === a).map((m) => m.id))
    const asked = !!ask && ask.id > saidAt
    // (b) the newest step of a turn this thread opened, and nothing after it from a turn another thread opened
    let k = -1
    for (let i = lane.length - 1; i >= 0; i--) { if (serves(lane[i])) { k = i; break } if (elsewhere(lane[i])) break }
    if (k >= 0) {
      let start = k
      while (start > 0 && !elsewhere(lane[start - 1])) start--
      const opener = rows.find((m) => lane[k].turn_msgs!.includes(m.id))
      const who = asked ? ask!.from : opener?.from
      out.push({ agent: a, since: asked ? ask!.ts : lane[start].ts, steps: lane.slice(start),
                 by: who && isHuman(who) && who !== me ? who : undefined })
      continue
    }
    if (!asked) continue
    const t0 = Date.parse(ask!.ts)
    out.push({ agent: a, since: ask!.ts, by: ask!.from === me ? undefined : ask!.from!,
               steps: lane.filter((s) => Date.parse(s.ts) >= t0) })
  }
  return out
}
