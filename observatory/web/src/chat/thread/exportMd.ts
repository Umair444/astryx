import { displayName, personName } from '../../api'
import { isHuman, type Msg } from '../../types'
import { download, embeds, stripEmbeds } from '../model'
import { nameOf } from '../artifacts/api'
import { parseChanges } from '../artifacts/versions/changes'

/* "Export conversation" (iteration 9): the thread as one Markdown file the owner keeps or forwards. The owner's turns
   and the agents', each with who and when (and to whom), the files each carried as links, handoffs between agents
   named as handoffs. Everything the WIRE needs and the reader does not stays out: a project's context block, the
   [chat with …] team line, annotation markers, a canvas context tag; a "send my changes" message becomes one line
   naming the file and versions (its diff is in the file's history, not in the transcript). A message the owner sent
   to several agents (one wire row each) is written once. */

const when = (ts: string) => new Date(ts).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
const CANVAS = /^\[canvas #\d+[^\]\n]*\]\s*/

export function conversationMarkdown(rows: Msg[], title: string, thread: string, roster: string[]): string {
  const agents = new Set(roster)
  const out: string[] = [`# ${title}`, '', `*Exported from astryx chat on ${when(new Date().toISOString())} · conversation \`${thread}\`*`, '']
  const sorted = [...rows].sort((a, b) => a.id - b.id)
  for (let i = 0; i < sorted.length; i++) {
    const m = sorted[i]
    let to = m.to ? [m.to] : []
    const human = isHuman(m.from)                               // the owner's or a member's words (11-15)
    if (human) {                                                // one fan-out, one entry
      while (sorted[i + 1] && sorted[i + 1].from === m.from && sameSend(sorted[i + 1], m)) { i++; if (sorted[i].to) to.push(sorted[i].to!) }
    }
    const who = personName(m.from)
    const handoff = !human && !!m.to && !isHuman(m.to) && agents.has(m.from) && agents.has(m.to)
    const head = handoff
      ? `**${who} → ${displayName(m.to!)}** · handoff · ${when(m.ts)}`
      : `**${who}** · ${when(m.ts)}${human && to.length ? ` · to ${to.map(displayName).join(', ')}` : ''}`
    const ch = human ? parseChanges(m.body) : null
    const text = ch
      ? `*Sent changes to ${ch.name}: v${ch.fromN} (${ch.fromWho}) → v${ch.toN} (${ch.toWho}).*${ch.note.trim() ? `\n\n${ch.note.trim()}` : ''}`
      : stripEmbeds(m.body).replace(CANVAS, '').trim()
    const files = embeds(m.body).map((e) => `- [${nameOf(e.path, e.label).replace(/[[\]]/g, '')}](<${e.path}>)`)
    out.push('---', '', head, '')
    if (text) out.push(text, '')
    if (files.length) out.push(human ? 'Attached:' : 'Files:', ...files, '')
  }
  if (!sorted.length) out.push('*No messages yet.*', '')
  return out.join('\n')
}
/* the rows the wire wrote for ONE owner send: the same words, seconds apart */
function sameSend(a: Msg, b: Msg) {
  const strip = (s: string) => s.replace(/^\[project: [\s\S]*?\[\/project\]\n?/, '').replace(/^\[chat with [^\]]*\]\n/, '')
  return strip(a.body) === strip(b.body) && Math.abs(Date.parse(a.ts) - Date.parse(b.ts)) < 15_000
}

export function exportConversation(rows: Msg[], title: string, thread: string, roster: string[]) {
  const md = conversationMarkdown(rows, title, thread, roster)
  const name = (title.replace(/[\\/:*?"<>|\u0000-\u001f]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80) || 'conversation') + '.md'
  download(new Blob([md], { type: 'text/markdown;charset=utf-8' }), name)
}
