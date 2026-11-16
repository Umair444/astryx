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
   the viewer, so the line reads "for Pat". 11-15: (a) once compared from to the literal 'owner'. */
/* `busy`: asked here, but its newest step belongs to a turn another conversation opened: it hasn't reached this message
   yet (owner 11-15: the line said "reading your message" for 20 minutes while seed worked on something else) */
/* `passed`: asked here, its newest turn ENDED after the ask, nothing from it since and nothing running: it finished
   without replying (owner 11-15: "you never replied, so the counter ran for 20 minutes"). The line says so and offers
   a reminder instead of a timer that never stops. */
/* `stopped`: its newest step is 'stopped' (hooks/step.py StopFailure: a usage limit, an overload, a server error), in
   Claude Code's own words ("You've hit your session limit · resets 2:50pm"). It can't take a turn until that clears, for
   this conversation or any other, so the line says why instead of a timer (owner 11-16: "users can't wait forever"). */
export interface Pending { agent: string; since: string; steps: Step[]; by?: string; leads?: boolean; busy?: boolean; passed?: boolean; stopped?: string }

export function pendingOf(agents: string[], rows: Msg[], live: Record<string, Step[]> | undefined, me: string,
                          ended: Record<string, string | null> = {}, now = Date.now()): Pending[] {
  const out: Pending[] = []
  const here = new Set(rows.map((m) => m.id))
  const serves = (s: Step) => !!s.turn_msgs?.some((id) => here.has(id))
  const elsewhere = (s: Step) => !!s.turn_msgs?.length && !serves(s)
  // the newest TEAM ask's members work here too, even where the chat's own recipients are one agent (a desk, where
  // "@db @seed …" reaches seed by its @mention): its rows share the lead and the moment they were sent
  const t = [...rows].reverse().find((m) => isHuman(m.from) && m.lead)
  const team = t ? rows.filter((m) => m.lead === t.lead && m.from === t.from && m.to && Math.abs(Date.parse(m.ts) - Date.parse(t.ts)) < 5000).map((m) => m.to!) : []
  for (const a of [...agents, ...team.filter((x, i) => !agents.includes(x) && team.indexOf(x) === i)]) {
    const lane = live?.[a] ?? []
    const ask = [...rows].reverse().find((m) => isHuman(m.from) && m.to === a)
    const saidAt = Math.max(0, ...rows.filter((m) => m.from === a).map((m) => m.id))
    // a team HELPER waits only until the lead has ANSWERED THE HUMAN (helpers answer the lead over the wire; its real
    // work still shows through its live lane, (b)). Keyed on THIS ask's own lead (an older team never ends a later
    // solo ask), and only the lead's rows to a human count (its wire to a helper is delegation, not an answer: medic
    // 12222 X1/X2). Everyone else waits for their own word
    const leadAt = ask?.lead && ask.lead !== a
      ? Math.max(0, ...rows.filter((m) => m.from === ask.lead && !!m.to && isHuman(m.to)).map((m) => m.id)) : 0
    const asked = !!ask && ask.id > saidAt && ask.id > leadAt
    const newest = lane[lane.length - 1]
    const stopped = newest?.kind === 'stopped' ? newest.content || 'stopped' : undefined
    // (b) the newest step of a turn this thread opened, and nothing after it from a turn another thread opened
    let k = -1
    for (let i = lane.length - 1; i >= 0; i--) { if (serves(lane[i])) { k = i; break } if (elsewhere(lane[i])) break }
    if (k >= 0) {
      let start = k
      while (start > 0 && !elsewhere(lane[start - 1])) start--
      const opener = rows.find((m) => lane[k].turn_msgs!.includes(m.id))
      const who = asked ? ask!.from : opener?.from
      out.push({ agent: a, since: asked ? ask!.ts : lane[start].ts, steps: lane.slice(start), stopped,
                 by: who && isHuman(who) && who !== me ? who : undefined })
      continue
    }
    if (!asked) continue
    const t0 = Date.parse(ask!.ts)
    const last = lane[lane.length - 1]
    const end = ended[a] ? Date.parse(ended[a]!) : 0
    out.push({ agent: a, since: ask!.ts, by: ask!.from === me ? undefined : ask!.from!,
               steps: lane.filter((s) => Date.parse(s.ts) >= t0 && !elsewhere(s)),
               stopped,
               busy: !stopped && !!last && elsewhere(last) && Date.parse(last.ts) >= t0 - 600_000,
               // a GRACE both ways (medic 12453): an ask that lands at a turn boundary isn't "passed" in the seconds
               // before its own turn starts; only a turn that ended a minute after the ask, half a minute ago, passed it
               passed: !lane.length && end > t0 + 60_000 && now - end > 30_000 })
  }
  // A TEAM's lead first (LiveActivity draws a team as ONE line, the lead's): the newest human ask here that named one
  const lead = t?.lead
  const i = lead ? out.findIndex((p) => p.agent === lead) : -1
  if (i < 0) return out
  return [{ ...out[i], leads: true }, ...out.slice(0, i), ...out.slice(i + 1)]   // `leads`: the line may say "helping"
}
