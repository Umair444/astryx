// 11-11: the call's open asks (pilot/asks.ts): which reply answers which ask, read back once, a progress line keeps it open.
//   node tests/pilot_asks_test.ts
import { answer, ASK_TTL, isAck, openAsk, readBack, READ_CAP, spoken, type Ask } from '../observatory/web/src/pilot/asks.ts'

let fails = 0
const arm = (name: string, ok: boolean) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}`); if (!ok) fails++ }
const t0 = 1_000_000
const chat: Ask = { agent: 'db', via: 'chat', thread: 'chat:abc', at: t0 }
const room: Ask = { agent: 'seed', via: 'room', thread: null, at: t0 }
let asks = openAsk(openAsk([], chat), room)

arm('one ask per agent per thread (a re-ask refreshes it)', openAsk(asks, { ...chat, at: t0 + 5 }).length === 2)
arm("the owner's own row on the thread answers nothing", answer(asks, { type: 'message', from: 'owner', thread: 'chat:abc', body: 'hi' }, t0).ask === null)
arm('the agent on ANOTHER thread answers nothing', answer(asks, { type: 'message', from: 'db', thread: 'chat:zzz', body: '42' }, t0).ask === null)
arm('a room_say from a chat-asked agent answers nothing', answer(asks, { type: 'room_say', agent: 'db', text: '42' }, t0).ask === null)

const ack = answer(asks, { type: 'message', from: 'db', thread: 'chat:abc', body: 'On it, about a minute.' }, t0 + 1000)
arm('a progress line is read back and keeps the ask open', ack.ask === chat && ack.ack && ack.asks.length === 2)
const real = answer(ack.asks, { type: 'message', from: 'db', thread: 'chat:abc', body: 'Yesterday: 4.2 million transactions, 97.1% success.\n[[file:/x/a.png]] (chart)' }, t0 + 60_000)
arm('the answer is read back and closes the ask', real.ask === chat && !real.ack && real.asks.length === 1 && real.asks[0] === room)
arm('embeds are not read out', real.text === 'Yesterday: 4.2 million transactions, 97.1% success.')
arm('a room_say answers the room ask', answer(asks, { type: 'room_say', agent: 'seed', text: 'All twelve agents are up.' }, t0).ask === room)
arm('an ask past its window answers nothing (and is dropped)', (() => { const r = answer(asks, { type: 'message', from: 'db', thread: 'chat:abc', body: 'late' }, t0 + ASK_TTL + 1); return r.ask === null && r.asks.length === 0 })())
arm('a long reply is capped', spoken('x'.repeat(5000)).length === READ_CAP)
arm('a long reply is never an ack', !isAck('on it. ' + 'detail '.repeat(60)))
arm('an answer is not an ack', !isAck('Yesterday: 4.2 million transactions.'))
arm('the read-back names the agent and asks for brevity', /^db answered: 42\. Tell the owner the answer briefly/.test(readBack('db', '42', false)))

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
process.exit(fails ? 1 : 0)
