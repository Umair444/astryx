// The chat's reply (owner 11-17: "giving agent the refernce of chat; instead of whole chat"): a person's message opens
// with the one message it answers as a line, and reads back to the same reference. Called by tests/test_chat_reply.py.
import { parseReply, parts, replyLine, REPLY_QUOTE, stripEmbeds } from '../observatory/web/src/chat/model.ts'

let fails = 0
const arm = (name: string, ok: boolean) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}`); if (!ok) fails++ }

const r = { id: 12945, from: 'finance', quote: 'Here is the P&L\nfor   October' }
const line = replyLine(r)
arm('the line names the message, who said it, and its words on one line', line === '[reply #12945 finance] “Here is the P&L for October”')
const back = parseReply(`${line}\nwhat about November?`)
arm('it reads back: the reference, then the person\'s own words', !!back && back.reply.id === 12945 && back.reply.from === 'finance'
  && back.reply.quote === 'Here is the P&L for October' && back.rest === 'what about November?')
const long = replyLine({ id: 1, from: 'cv-haris-sher.6', quote: 'x'.repeat(500) })
arm('a long message rides as its first words, never whole', long.length < REPLY_QUOTE + 40 && long.includes('…”'))
arm('a member is named by their handle', parseReply(`${long}\nok`)?.reply.from === 'cv-haris-sher.6')
arm('a quote holding ” still reads back whole', parseReply(`${replyLine({ id: 2, from: 'db', quote: 'he said “no” twice' })}\nhm`)?.reply.quote === 'he said “no” twice')
arm('a body that only mentions [reply …] later is no reply', parseReply('see [reply #3 db] “x”\nmore') === null)
arm('with a file, the reply line still opens the text', parseReply(stripEmbeds(`${line}\nlook [[file:/m/a.png]]`))?.rest === 'look')
const t0 = parts(`${line}\nhi`)[0]
arm("the text run a bubble draws starts at the reference (the bubble cuts it to a chip)", !!t0 && 'text' in t0 && parseReply(t0.text)?.rest === 'hi')

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
process.exit(fails ? 1 : 0)
