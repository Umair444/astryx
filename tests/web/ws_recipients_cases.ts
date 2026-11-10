// The chat's default recipients (observatory/web/src/chat/model.ts participants), run by tests/test_ws_recipients.py.
// Rule: an agent is a recipient only if it exchanged a message WITH THE OWNER on the thread; an agent→agent row on an
// owner thread (seed correcting finance, a handoff) never adds its sender (the owner's reply would copy them in).
import { participants } from '../../observatory/web/src/chat/model'
import type { Msg } from '../../observatory/web/src/types'

let fails = 0
const arm = (name: string, got: unknown, want: unknown) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (!ok) fails++
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `\n        got ${JSON.stringify(got)} want ${JSON.stringify(want)}`}`)
}
let id = 0
const m = (from: string, to: string | null): Msg => ({ id: ++id, ts: '2026-11-10T10:00:00Z', from, from_org: null, to, to_org: null, thread: 'cv:x', intent: null, body: 'x', status: null })
const R = ['seed', 'finance', 'db', 'lending']

arm('cv:0b7661abb9 shape: seed→finance correction does not add seed',
  participants([m('owner', 'finance'), m('finance', 'owner'), m('seed', 'finance'), m('owner', 'finance')], R), ['finance'])
arm('an agent replying to the owner is a recipient', participants([m('db', 'owner')], R), ['db'])
arm('the owner asking an agent makes it a recipient (before any reply)', participants([m('owner', 'lending')], R), ['lending'])
arm('a handoff row alone (db→seed) adds nobody', participants([m('db', 'seed')], R), [])
arm('first-seen order, no duplicates', participants([m('owner', 'db'), m('owner', 'seed'), m('db', 'owner'), m('seed', 'owner')], R), ['db', 'seed'])
arm('non-agents never join (canvas page, pulse)', participants([m('canvas-1', 'lending'), m('owner', 'pulse'), m('lending', 'owner')], R), ['lending'])
arm('a null recipient is ignored', participants([m('owner', null)], R), [])
console.log(`\n${fails ? 'FAIL' : 'PASS'}: ${fails} failing arm(s)`)
process.exit(fails ? 1 : 0)
