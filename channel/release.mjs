// The JS seam of src/astryx/security/release.py, the ONE door for personal-tier content (plan-9139 S1b-2). server.mjs
// never decides a label or writes a labelled row itself: it asks this module, which runs the Python door by PATH
// (release.py's own shim puts its checkout on sys.path), exactly as address.mjs runs address.py. Its own module so
// tests/test_release_server.py can EXECUTE the seam on a fixture home.
// POLARITY, the opposite of address.mjs: every failure here REFUSES. address.mjs allows an unevaluable check because
// muting every send is worse than one unchecked name; a label nobody could read is UNKNOWN, and tier.py's rule is that
// an unresolvable identity is private, never public. So an unreadable label refuses the server's start, and an
// unrunnable send refuses the send. Nothing falls back to the raw INSERT.
import { execFile } from 'node:child_process'
import { homePath } from './home.mjs'

const PY = homePath('venv/bin/python')
const DOOR = homePath('src/astryx/security/release.py')

function run(args, { input, agent, py = PY, door = DOOR } = {}) {
  return new Promise((resolve, reject) => {
    const env = { ...process.env, ...(agent ? { ASTRYX_AGENT: agent } : {}) }
    const p = execFile(py, [door, ...args], { timeout: 15_000, env, maxBuffer: 8 << 20 }, (err, stdout, stderr) => {
      if (!err) return resolve(stdout)
      let why = ''
      try { why = JSON.parse((stdout || '').trim().split('\n').pop()).error || '' } catch {}
      // stderr can carry a traceback quoting the request; only its last line, and only when the door said nothing
      reject(new Error(why || `the release door could not run (${(stderr || err.message).trim().split('\n').pop()
        .slice(-120)})`))
    })
    p.stdin.end(input ?? '')
  })
}

/** The tiers this agent's session carries ([] = org). THROWS on a malformed grant, no charter, or no door. */
export async function readLabel(agent, opts = {}) {
  const out = await run(['label', agent], opts)
  let tiers
  try { tiers = JSON.parse(out) } catch { throw new Error('the release door answered something that is not a label') }
  if (!Array.isArray(tiers) || !tiers.every(t => typeof t === 'string')) throw new Error('the label is not a tier list')
  return tiers
}

/** A labelled member's send, written by the door. Returns the row id. THROWS with the door's reason; no row then. */
export async function releaseSend(agent, req, opts = {}) {
  const out = await run(['send'], { ...opts, agent, input: JSON.stringify(req) })
  const id = JSON.parse(out).id
  if (!Number.isInteger(id)) throw new Error('the release door wrote no row')
  return id
}
