import { Marked } from 'marked'
import { codeBlock, escapeHtml, fenceBareCode } from './code'

/* A HUMAN's words as markdown (owner 11-15: "the standard of modern chat interfaces is md"). Its own parser: raw HTML in
   a human's text is SHOWN, never rendered (medic 12168: with class attributes and the app's own utility classes, a
   human could draw an overlay, "Sign in again", on every reader's screen; a member's or a canvas guest's text is not
   the org's). Code is detected and fenced (code.ts) and drawn by codeBlock. Pure (no DOM), so tests run it under node;
   Prose.tsx sanitizes its output like every other. */
const human = new Marked({ gfm: true, breaks: true }, {
  renderer: {
    code: ({ text, lang }) => codeBlock(text, lang),
    html: ({ text }) => escapeHtml(text),
  },
})

export function humanHtml(text: string): string {
  return human.parse(fenceBareCode(text), { async: false }) as string
}
