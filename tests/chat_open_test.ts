// Opening an attached file (chat/artifacts/api.ts openArtifact) for a member (insurance 12938): the store's import
// (POST /api/ws/artifacts/open) is the owner's and answers a member 403, so their open must be the plain file,
// read-only, through /api/chat/file (which admits a file a message they can read attached), never an error.
// Called by tests/test_chat_open.py:  node tests/chat_open_test.ts
let answer: () => Response = () => new Response('{}', { status: 200 })
const g = globalThis as Record<string, unknown>
g.window = { dispatchEvent: () => true, addEventListener: () => {}, location: { search: '' } }
g.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} }
g.sessionStorage = g.localStorage
g.fetch = async () => answer()

let fails = 0
const arm = (name: string, ok: boolean, got?: unknown) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `\n        ${JSON.stringify(got)}`}`); if (!ok) fails++ }
const json = (status: number, body: unknown) => () => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

const { openArtifact } = await import('../observatory/web/src/chat/artifacts/api.ts')
const PATH = '/srv/org/homes/a/out/sales.xlsx'
const open = async () => { try { return await openArtifact(PATH, 'obs:insurance', 'insurance') } catch (e) { return { threw: String(e) } } }

answer = json(403, { error: 'forbidden' })
const m = await open() as Record<string, unknown>
arm("a MEMBER's open (the import answers 403): the plain file, read-only, not an error",
  m.store === false && m.source === PATH && m.kind === 'sheet' && !('threw' in m), m)

answer = json(200, { id: 'a1', thread: 'obs:insurance', name: 'sales.xlsx', kind: 'sheet', path_in_store: 'x', size: 8, head: 'r1', versions: [] })
const o = await open() as Record<string, unknown>
arm("the OWNER's open (the import answers 200): the stored artifact, with its history",
  o.store === true && o.id === 'a1', o)

answer = json(400, { error: 'not a file' })
const bad = await open() as Record<string, unknown>
arm('a real refusal (400) is still an error the panel shows', typeof bad.threw === 'string', bad)

answer = json(403, { error: 'forbidden' })
const again = await open() as Record<string, unknown>
arm("...and a member's 403 never marks the store down (the next open still asks it)", again.store === false && !('threw' in again), again)

process.exit(fails ? 1 : 0)
