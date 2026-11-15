// The live line's input (11-15): who is working on an ask here, for any human's ask. Called by
// tests/test_chat_pending.py:  node tests/chat_pending_test.ts
import { pendingOf } from '../observatory/web/src/chat/thread/pending.ts'

let fails = 0
const arm = (name: string, ok: boolean, got?: unknown) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `\n        ${JSON.stringify(got)}`}`); if (!ok) fails++ }
const row = (id: number, from: string, to: string | null, ts: string) => ({ id, from, to, ts, thread: 'obs:db', body: 'x' }) as never
const step = (id: number, ts: string) => ({ id, ts, agent: 'db', kind: 'tool', content: 'Bash: q' }) as never
const PAT = 'cv-pat-lee.2'
const live = { db: [step(1, '2026-11-15T07:20:00Z'), step(2, '2026-11-15T07:23:00Z')] }

const m1 = [row(10, PAT, 'db', '2026-11-15T07:22:52Z')]
const asMember = pendingOf(['db'], m1, live, PAT)
arm("a MEMBER's own ask: db is pending for them, no asker named", asMember.length === 1 && asMember[0].by === undefined, asMember)
arm('...its steps are the ones since the ask, not before', asMember[0]?.steps.length === 1, asMember[0]?.steps)
const asOwner = pendingOf(['db'], m1, live, 'owner')
arm("the OWNER watching the member's ask: pending, the asker named", asOwner.length === 1 && asOwner[0].by === PAT, asOwner)
const m2 = [row(10, 'owner', 'db', '2026-11-15T07:22:52Z')]
const ownerOwn = pendingOf(['db'], m2, live, 'owner')
arm("the owner's own ask: as before, no asker named", ownerOwn.length === 1 && ownerOwn[0].by === undefined, ownerOwn)
arm("a member watching the owner's ask: pending, 'owner' named", pendingOf(['db'], m2, live, PAT)[0]?.by === 'owner')
const answered = [...m1, row(11, 'db', PAT, '2026-11-15T07:33:07Z')]
arm('an answered ask is not pending', pendingOf(['db'], answered, live, PAT).length === 0)
const handoff = [row(10, 'seed', 'db', '2026-11-15T07:22:52Z')]
arm("an agent's handoff is not a human's ask", pendingOf(['db'], handoff, live, 'owner').length === 0)
const again = [...answered, row(12, PAT, 'db', '2026-11-15T07:40:00Z')]
const p2 = pendingOf(['db'], again, live, PAT)
arm('a new ask after the answer is pending again, timed from the new ask', p2.length === 1 && p2[0].since === '2026-11-15T07:40:00Z', p2)

// 11-15: an agent that REPLIED and kept working stays on the line while its open turn serves this thread
const st = (id: number, ts: string, turn_msgs: number[] | null, sub?: object) => ({ id, ts, agent: 'db', kind: 'tool', content: 'Bash: q', turn_msgs, sub }) as never
const replied = [row(10, PAT, 'db', '2026-11-15T09:00:00Z'), row(11, 'db', PAT, '2026-11-15T09:05:00Z')]
const going = { db: [st(1, '2026-11-15T09:00:05Z', [10]), st(2, '2026-11-15T09:06:00Z', [10]), st(3, '2026-11-15T09:07:00Z', [])] }
const g = pendingOf(['db'], replied, going, 'owner')
arm('replied but its turn goes on: still on the line, every step of the turn, the asker named',
  g.length === 1 && g[0].steps.length === 3 && g[0].by === PAT && g[0].since === '2026-11-15T09:00:05Z', g)
arm('...for the asker themself, no name', pendingOf(['db'], replied, going, PAT)[0]?.by === undefined)
const moved = { db: [st(1, '2026-11-15T09:00:05Z', [10]), st(2, '2026-11-15T09:08:00Z', [999])] }
arm('a later step from a turn another thread opened: not working HERE', pendingOf(['db'], replied, moved, 'owner').length === 0)
arm('an empty lane (the turn ended) after the reply: nothing', pendingOf(['db'], replied, { db: [] }, 'owner').length === 0)
const helper = { db: [st(1, '2026-11-15T09:00:05Z', [10]), st(2, '2026-11-15T09:06:00Z', [10], { id: 'a1', desc: 'check partitions' })] }
const h = pendingOf(['db'], replied, helper, 'owner')
arm("a helper's step for this thread keeps the line, and carries who it is", h.length === 1 && (h[0].steps.at(-1) as { sub?: { desc?: string } }).sub?.desc === 'check partitions', h)

// a TEAM (owner 11-15: one line for several agents, the lead's): the lead the ask named comes first, whatever the order
const team = [{ ...row(20, 'owner', 'seed', '2026-11-15T10:00:00Z'), lead: 'db' }, { ...row(21, 'owner', 'db', '2026-11-15T10:00:00Z'), lead: 'db' }] as never[]
const both = pendingOf(['seed', 'db'], team, {}, 'owner')
arm("a team's ask: both agents are pending, the named lead first", both.map((p) => p.agent).join() === 'db,seed', both.map((p) => p.agent))
const nolead = pendingOf(['seed', 'db'], [row(20, 'owner', 'seed', '2026-11-15T10:00:00Z'), row(21, 'owner', 'db', '2026-11-15T10:00:01Z')], {}, 'owner')
arm('...with no lead named, the chat\'s own order stands', nolead.map((p) => p.agent).join() === 'seed,db', nolead.map((p) => p.agent))
const desk = pendingOf(['db'], team, {}, 'owner')
arm("on a desk (recipients: the desk's agent alone), the team's other member still works here", desk.map((p) => p.agent).join() === 'db,seed', desk.map((p) => p.agent))
const answered2 = [...(team as never[]), row(22, 'db', 'owner', '2026-11-15T10:05:00Z')] as never[]
arm("once the lead has answered, an idle helper is no longer waited for", pendingOf(['db'], answered2, {}, 'owner').length === 0, pendingOf(['db'], answered2, {}, 'owner').map((p) => p.agent))

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
