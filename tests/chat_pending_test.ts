// The live line's input (11-15): who is working on an ask here, for any human's ask. Called by
// tests/test_chat_pending.py:  node tests/chat_pending_test.ts
import { pendingOf } from '../observatory/web/src/chat/thread/pending.ts'

let fails = 0
const arm = (name: string, ok: boolean, got?: unknown) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `\n        ${JSON.stringify(got)}`}`); if (!ok) fails++ }
const row = (id: number, from: string, to: string | null, ts: string) => ({ id, from, to, ts, thread: 'obs:db', body: 'x' }) as never
const step = (id: number, ts: string) => ({ id, ts, agent: 'db', kind: 'tool', content: 'Bash: q' }) as never
const FARAN = 'cv-faran-khalid.2'
const live = { db: [step(1, '2026-11-15T07:20:00Z'), step(2, '2026-11-15T07:23:00Z')] }

const m1 = [row(10, FARAN, 'db', '2026-11-15T07:22:52Z')]
const asMember = pendingOf(['db'], m1, live, FARAN)
arm("a MEMBER's own ask: db is pending for her, no asker named", asMember.length === 1 && asMember[0].by === undefined, asMember)
arm('...its steps are the ones since the ask, not before', asMember[0]?.steps.length === 1, asMember[0]?.steps)
const asOwner = pendingOf(['db'], m1, live, 'owner')
arm("the OWNER watching the member's ask: pending, the asker named", asOwner.length === 1 && asOwner[0].by === FARAN, asOwner)
const m2 = [row(10, 'owner', 'db', '2026-11-15T07:22:52Z')]
const ownerOwn = pendingOf(['db'], m2, live, 'owner')
arm("the owner's own ask: as before, no asker named", ownerOwn.length === 1 && ownerOwn[0].by === undefined, ownerOwn)
arm("a member watching the owner's ask: pending, 'owner' named", pendingOf(['db'], m2, live, FARAN)[0]?.by === 'owner')
const answered = [...m1, row(11, 'db', FARAN, '2026-11-15T07:33:07Z')]
arm('an answered ask is not pending', pendingOf(['db'], answered, live, FARAN).length === 0)
const handoff = [row(10, 'seed', 'db', '2026-11-15T07:22:52Z')]
arm("an agent's handoff is not a human's ask", pendingOf(['db'], handoff, live, 'owner').length === 0)
const again = [...answered, row(12, FARAN, 'db', '2026-11-15T07:40:00Z')]
const p2 = pendingOf(['db'], again, live, FARAN)
arm('a new ask after the answer is pending again, timed from the new ask', p2.length === 1 && p2[0].since === '2026-11-15T07:40:00Z', p2)

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
