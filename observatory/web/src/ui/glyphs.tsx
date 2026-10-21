import { BRAND } from './brands'
import type { ChatKind, ChatRef, Glyph } from './routes'

/* A channel's mark, small: a disc in the brand's colour with its glyph in white, ringed in the floor's own background so
   it reads as cut out of the face it sits on. Group vs person shows as a tiny second mark. */
export function ChannelMark({ channel, size = 16, ring = 'var(--t-bg)', title }: {
  channel: string; size?: number; ring?: string; title?: string
}) {
  const b = BRAND[channel]
  if (!b) return null
  const pad = Math.round(size * 0.2)
  return (
    <span role="img" aria-label={title ?? b.title} title={title ?? b.title}
      className="inline-grid place-items-center rounded-full shrink-0"
      style={{ width: size, height: size, background: b.hex, boxShadow: `0 0 0 2px ${ring}` }}>
      <svg viewBox="0 0 24 24" width={size - pad * 2} height={size - pad * 2} aria-hidden fill="#fff"><path d={b.path} /></svg>
    </span>
  )
}

export const KIND_WORD: Record<ChatKind, string> = { group: 'group', person: 'person' }

/* The marks an agent wears on the floor: one per channel (counted), at most 3 then +N. `chats` (owner only) adds names
   to the hover; a visitor sees "2 WhatsApp groups", never which. */
export function GlyphStack({ glyphs, chats, size = 15, max = 3 }: { glyphs: Glyph[]; chats?: ChatRef[]; size?: number; max?: number }) {
  if (!glyphs.length) return null
  const byCh = new Map<string, Glyph[]>()
  for (const g of glyphs) byCh.set(g.channel, [...(byCh.get(g.channel) ?? []), g])
  const chans = [...byCh.keys()].sort()
  const shown = chans.slice(0, max)
  const more = chans.length - shown.length
  const line = (ch: string) => {
    const named = chats?.filter((c) => c.channel === ch && c.enabled)
    if (named?.length) return `${BRAND[ch]?.title ?? ch}: ${named.map((c) => c.label).join(', ')}`
    const parts = (byCh.get(ch) ?? []).map((g) => `${g.count} ${KIND_WORD[g.kind]}${g.count === 1 ? '' : 's'}`)
    return `${BRAND[ch]?.title ?? ch}: ${parts.join(', ')}`
  }
  const title = chans.map(line).join('\n')
  return (
    <span className="inline-flex items-center" title={title} aria-label={title}>
      {shown.map((ch, i) => (
        <span key={ch} style={{ marginLeft: i ? -5 : 0, zIndex: 10 - i }} className="relative">
          <ChannelMark channel={ch} size={size} title={line(ch)} />
        </span>
      ))}
      {more > 0 && <span className="ml-1 text-[10px] font-medium text-ink-dim tabular-nums">+{more}</span>}
    </span>
  )
}
