import type { Part } from '../model'
import { kindOfName, nameOf, type Kind } from '../artifacts/api'

/* which embeds a body draws IN PLACE (thread/Inline.tsx), apart from React so node can test it
   (tests/test_chat_inline.py) */
export const MEDIA = new Set<Kind>(['image', 'audio', 'video', 'pdf'])

/* the embeds to draw in place: each path once (its first spot), trailing non-media embeds left to the chip row */
export function inlineParts(ps: Part[]): Part[] {
  const seen = new Set<string>()
  const out = ps.filter((p) => !('embed' in p) || (!seen.has(p.embed.path) && !!seen.add(p.embed.path)))
  while (out.length) {
    const p = out[out.length - 1]
    if (!('embed' in p) || MEDIA.has(kindOfName(nameOf(p.embed.path, p.embed.label)))) break
    out.pop()
  }
  return out
}
