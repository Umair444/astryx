// cog-gaps: whose words sit where. A human's message is the viewer's own (right, the 'mine' block with by=null) only
// when from === the viewer's handle; another human's (the owner's in a member's view, a member's or a canvas guest's
// in the owner's) is on the left under their name. Turns.tsx's blocksOf places every human row through placeHuman. Called by tests/test_chat_sides.py:  node tests/chat_sides_test.ts
import { humanName, ownWords } from '../observatory/web/src/types.ts'
import { placeHuman, type HumanBubble } from '../observatory/web/src/chat/thread/sides.ts'

let fails = 0
const arm = (name: string, ok: boolean, got?: unknown) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `\n        ${JSON.stringify(got)}`}`); if (!ok) fails++ }

const ALICE = 'cv-alice.7'
let id = 0
const msg = (from: string, to: string, body: string, ts = '2099-01-01T10:00:00Z') =>
  ({ id: ++id, ts, from, from_org: 'local', to, to_org: null, thread: 'chat:x', intent: 'chat', body, status: 'delivered' }) as never
const rows = [msg('owner', 'seed', 'owner asks'), msg(ALICE, 'seed', 'alice asks'), msg('seed', ALICE, 'an answer'),
  msg(ALICE, 'db', 'alice asks', '2099-01-01T10:00:10Z'), msg('cv-bob', 'seed', 'guest asks')]
const place = (ms: unknown[], me: string) => {         // blocksOf's human path: each row merges or starts a bubble
  const out: HumanBubble[] = []
  for (const m of ms) { const b = placeHuman(out.at(-1) ?? null, m as never, me); if (b) out.push(b) }
  return out.map((b) => `${b.msg.body}:${b.by ?? 'ME'}:${b.to.join('+')}`)
}

arm('ownWords: the viewer handle decides; no handle = the owner', ownWords('owner', undefined) && ownWords(ALICE, ALICE) && !ownWords('owner', ALICE) && !ownWords(ALICE, 'owner'))
arm("humanName: 'owner' -> Owner, cv-<label>.<uid> -> its label, a guest -> its name",
  humanName('owner') === 'Owner' && humanName(ALICE) === 'Alice' && humanName('cv-mary-jo.12') === 'Mary Jo' && humanName('cv-bob') === 'Bob',
  [humanName('owner'), humanName(ALICE), humanName('cv-mary-jo.12'), humanName('cv-bob')])
const humans = rows.filter((m) => (m as { from: string }).from !== 'seed')
const asAlice = place(humans, ALICE)
arm("a member's view: her words right, the owner's and a guest's left by name; her fan-out still merges",
  JSON.stringify(asAlice) === JSON.stringify(['owner asks:owner:seed', 'alice asks:ME:seed+db', 'guest asks:cv-bob:seed']), asAlice)
const asOwner = place(humans, 'owner')
arm("the owner's view: his right, the member's and the guest's left",
  JSON.stringify(asOwner) === JSON.stringify(['owner asks:ME:seed', `alice asks:${ALICE}:seed+db`, 'guest asks:cv-bob:seed']), asOwner)
const same = place([msg('owner', 'seed', 'same words'), msg(ALICE, 'seed', 'same words')], ALICE)
arm("two humans' identical words never merge into one bubble", same.length === 2, same)
const late = place([msg(ALICE, 'seed', 'again', '2099-01-01T10:00:00Z'), msg(ALICE, 'db', 'again', '2099-01-01T10:02:00Z')], ALICE)
arm('the same words a minute or more later are a new bubble', late.length === 2, late)

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
process.exit(fails ? 1 : 0)
