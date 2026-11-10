import type { Msg } from '../../../types'

/* The annotation shape (ARTIFACTS_API.md "Shapes"): the server validates it and drops unknown fields, so everything
   the client needs is carried by these fields alone. An ASK (a question put to an agent from a highlight) is a
   comment whose id names the agent: `ask.<rand>.<agent>` (agent names never hold a dot); its question is the body,
   and the agent's answer is the reply that arrives on the wire after it (see ask.ts). */

export type Color = 'yellow' | 'green' | 'blue' | 'pink'
export const COLORS: Color[] = ['yellow', 'green', 'blue', 'pink']

export interface Anchor { quote: string; prefix: string; suffix: string; start?: number; end?: number; page?: number }
export interface Reply { author: string; body: string; ts: string }
export interface Ann {
  id: string
  kind: 'highlight' | 'comment' | 'suggest'
  color?: Color
  anchor: Anchor
  body?: string
  author: string
  ts: string
  replies?: Reply[]
  resolved?: boolean
}

/* what the conversation lends the annotation layer: its rows (for ask replies), who can be asked, and how to ask */
export interface AnnotateCtx {
  rows: Msg[]
  roster: string[]
  agents: string[]                                    // this conversation's agents; the first is the default to ask
  ask: (agent: string, body: string) => Promise<Msg | null>
  focus: { name: string; ann: string; n: number } | null   // a quoted ask chip in the chat asked to show its highlight
}

export const newId = (prefix = 'a') => `${prefix}.${Array.from(crypto.getRandomValues(new Uint8Array(6)), (b) => b.toString(36).padStart(2, '0')).join('').slice(0, 10)}`
