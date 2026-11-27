import { ownWords, type Msg } from '../../types'
import { stripEmbeds } from '../model'

/* cog-gaps: a human's message in the thread. It is the viewer's own (right, by = null) only when from === their handle;
   another human's (the owner's in a member's view, a member's or a canvas guest's in the owner's) is on the left
   under their name (by = their handle). One message fanned out to several agents (a row per recipient, same words,
   within a minute) is one bubble naming them all, never across two humans. Returns the new bubble, or null when
   `msg` merged into `last` (its recipient added). Pure: tests/chat_sides_test.ts. */
export interface HumanBubble { msg: Msg; to: string[]; by: string | null }

export function placeHuman(last: HumanBubble | null, msg: Msg, me: string): HumanBubble | null {
  if (last && last.msg.from === msg.from && stripEmbeds(last.msg.body) === stripEmbeds(msg.body)
      && Date.parse(msg.ts) - Date.parse(last.msg.ts) < 60_000) {
    if (msg.to && !last.to.includes(msg.to)) last.to.push(msg.to)
    return null
  }
  return { msg, to: msg.to ? [msg.to] : [], by: ownWords(msg.from, me) ? null : msg.from }
}
