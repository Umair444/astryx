/* The call's open asks (owner report 11-11: "asked db, heard nothing"). ask_agent hands a request to an agent, on the
   open chat thread (an owner message, shown like a typed one) or, off the chat, on the room's wire. Each ask stays
   OPEN here until that agent answers it, so the call can read the answer back: every reply from that agent on that
   thread while the ask is open is spoken; a short progress line ("on it, about a minute") keeps it open, anything
   else closes it; ASK_TTL closes it regardless. Pure: no React, no DOM, so node can test it. */

export const ASK_TTL = 15 * 60_000
export const READ_CAP = 1500
export interface Ask { agent: string; via: 'chat' | 'room'; thread: string | null; at: number }
type Ev = { type: string; [k: string]: any }

/** A progress line, not the answer: short and saying it's still working. */
export function isAck(text: string): boolean {
  const t = text.trim()
  return t.length < 240 && /\b(on it|working on|looking (into|at)|checking|digging|running|give me|(a|one) (sec|second|minute|moment)|few minutes|shortly|will (get back|report|come back|share|send)|i'?ll (get back|report|come back|share|send)|stand by|in progress|pulling)\b/i.test(t)
}

/** The words worth reading back: embeds and the chat's preamble lines out, whitespace folded, capped. */
export function spoken(body: string): string {
  return body.replace(/\[\[(file|ann):[^\]\n]*\]\](?: \([^)\n]{1,120}\))?/g, '').replace(/^\[chat with [^\]]*\]\n/, '')
    .replace(/\s+/g, ' ').trim().slice(0, READ_CAP)
}

/** Open (or refresh) an ask: one per agent per thread. */
export function openAsk(asks: Ask[], a: Ask): Ask[] {
  return [...asks.filter((x) => !(x.agent === a.agent && x.via === a.via && x.thread === a.thread)), a]
}

/** The asks still inside their window. */
export const live = (asks: Ask[], now: number) => asks.filter((a) => now - a.at < ASK_TTL)

/** One stream event against the open asks: the ask it answers (null if none), its text, and the asks after it. */
export function answer(asks: Ask[], ev: Ev, now: number): { ask: Ask | null; text: string; ack: boolean; asks: Ask[] } {
  const open = live(asks, now)
  const hit = ev.type === 'message'
    ? open.find((a) => a.via === 'chat' && ev.from === a.agent && ev.thread === a.thread)
    : ev.type === 'room_say' ? open.find((a) => a.via === 'room' && ev.agent === a.agent) : undefined
  const text = hit ? spoken(String((ev.type === 'message' ? ev.body : ev.text) ?? '')) : ''
  if (!hit || !text) return { ask: null, text: '', ack: false, asks: open }
  const ack = isAck(text)
  return { ask: hit, text, ack, asks: ack ? open : open.filter((a) => a !== hit) }
}

/** What the model is told when an answer lands. */
export function readBack(agent: string, text: string, ack: boolean): string {
  return ack
    ? `${agent} replied (still working on it): ${text}. Tell the owner that briefly, in one sentence; the full answer comes later.`
    : `${agent} answered: ${text}. Tell the owner the answer briefly, in a sentence or two.`
}
