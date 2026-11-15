import { codeBlock, escapeHtml } from './code'

/* DELIVERABLES (owner 11-15: "Faran asked db to write an email and had to copy it again … it should be general; later
   realtime artifacts, HTML generated and shown as it's written, so chat becomes one interface for everything").
   Something an agent makes for a person to take elsewhere comes in ONE fenced block named for its kind (the channel
   server tells every agent so: channel/server.mjs). The chat draws that block as a CARD, not as code: its kind and
   title in a bar, its content rendered, and the actions every deliverable has: Copy (formatted for a mail client or a
   document, clean words for a plain editor: clip.ts), Open (an artifact in the store: versions, annotations, download,
   send changes back) and, per kind, more (an email's subject on its own, a short one handed to the mail app).
   A kind is a row in KINDS; a new kind is a row, never a new path. The clicks are delegated from the answer
   (Prose.tsx), so no script rides in the sanitized HTML. The card's SOURCE never rides in the HTML either: an answer's
   own raw HTML could draw a card that shows one text and copies another (medic 12245 F1). The renderer keeps each
   card's data in the answer's own map under a random id made at render time (data-dl-id); a card whose id isn't in
   that map is inert. Pure: tests run it. */

export interface Kind { label: string; ext: string; md: boolean }
export const KINDS: Record<string, Kind> = {
  email: { label: 'Email', ext: 'md', md: true },
  doc: { label: 'Document', ext: 'md', md: true },
  document: { label: 'Document', ext: 'md', md: true },
  message: { label: 'Message', ext: 'md', md: true },
  letter: { label: 'Letter', ext: 'md', md: true },
  html: { label: 'HTML', ext: 'html', md: false },
}
export const kindOf = (lang?: string | null): string | null => {
  const k = (lang || '').trim().split(/\s+/)[0].toLowerCase()
  return k in KINDS ? k : null
}

const MAILTO_MAX = 1800          // mail clients cut a mailto: body near 2,000 characters; past this, Copy is the path

/* a deliverable's title and the content under it: an email's "Subject:" line, a document's first heading, else its
   first words */
export function parseDeliverable(text: string, kind: string): { title: string; subject: string | null; body: string } {
  const t = text.replace(/\n+$/, '')
  const subj = kind === 'email' ? /^\s*(?:\*\*)?subject:(?:\*\*)?\s*(.+)\n?/i.exec(t) : null
  if (subj) return { title: subj[1].trim(), subject: subj[1].trim(), body: t.slice(subj[0].length).replace(/^\s*\n/, '') }
  const h = /^\s*#{1,3}\s+(.+)\n?/.exec(t)
  if (h && KINDS[kind].md) return { title: h[1].trim(), subject: null, body: t }
  const first = t.split('\n').find((l) => l.trim())?.trim() ?? ''
  return { title: first.length > 60 ? first.slice(0, 57) + '…' : first, subject: null, body: t }
}

/* the artifact's file name: the title, safe and short, with the kind's extension */
export function deliverableName(title: string, kind: string): string {
  const stem = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || kind
  return `${stem}.${KINDS[kind].ext}`
}

/* what a card's buttons act on, kept OUT of the HTML (the answer's map, by the card's id) */
export interface Card { kind: string; src: string; subject: string; name: string }
export function cardData(text: string, kind: string): Card {
  const d = parseDeliverable(text, kind)
  return { kind, src: d.body, subject: d.subject ?? '', name: deliverableName(d.title, kind) }
}

/* the card: `render` is the answer's own markdown renderer (Prose's), so a deliverable reads like the rest of it; `id`
   is the render's own key for this card's data (cardData), never the data itself */
export function deliverableBlock(text: string, kind: string, render: (md: string) => string, id: string): string {
  const k = KINDS[kind]
  const d = parseDeliverable(text, kind)
  const mailto = kind === 'email' && d.body.length <= MAILTO_MAX
    ? `mailto:?subject=${encodeURIComponent(d.subject ?? '')}&body=${encodeURIComponent(d.body)}` : ''
  const btn = (act: string, label: string, title: string) =>
    `<button type="button" class="ws-dl-btn" data-dl="${act}" title="${escapeHtml(title)}">${label}</button>`
  return `<div class="ws-dl" data-kind="${kind}" data-dl-id="${escapeHtml(id)}">`
    + `<div class="ws-dl-bar"><span class="ws-dl-kind">${k.label}</span><span class="ws-dl-title">${escapeHtml(d.title)}</span>`
    + (d.subject ? btn('subject', 'Copy subject', 'Copy the subject line') : '')
    + btn('copy', 'Copy', k.md ? 'Copy it, formatted: paste into an email or a document' : 'Copy the source')
    + btn('open', 'Open', 'Open as a file: edit, annotate, version, download')
    + (mailto ? `<a class="ws-dl-btn" href="${escapeHtml(mailto)}" title="Start this email in your mail app">Mail</a>` : '')
    + `</div><div class="ws-dl-body">${k.md ? render(d.body) : codeBlock(d.body, kind)}</div></div>`
}
