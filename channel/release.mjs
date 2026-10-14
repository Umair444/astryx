// The JS seam of src/astryx/security/release.py, the ONE door for personal-tier content (plan-9139 S1b-2). server.mjs
// never decides a label or writes a labelled row itself: it asks this module, which runs the Python door by PATH
// (release.py's own shim puts its checkout on sys.path), exactly as address.mjs runs address.py. Its own module so
// tests/test_release_server.py can EXECUTE the seam on a fixture home.
// POLARITY, the opposite of address.mjs: nothing here ever falls back to the raw INSERT. address.mjs allows an
// unevaluable check because muting every send is worse than one unchecked name; a label nobody could read is
// UNKNOWN (tier.py: an unresolvable identity is private, never public), so its sends are refused. Three answers:
//   [tiers]  the label ([] = org, today's paths)
//   null     UNKNOWN: no charter resolves, or the door can't run. The body starts (its ear works) and every send
//            is refused by the door, as step.py withholds a reply it can't label
//   throws   a MALFORMED private grant: the server refuses to start (a4 #46035)
import { execFile } from 'node:child_process'
import { homePath } from './home.mjs'

const PY = homePath('venv/bin/python')
const DOOR = homePath('src/astryx/security/release.py')

function run(args, { input, agent, py = PY, door = DOOR } = {}) {
  return new Promise((resolve) => {
    const env = { ...process.env, ...(agent ? { ASTRYX_AGENT: agent } : {}) }
    const p = execFile(py, [door, ...args], { timeout: 15_000, env, maxBuffer: 8 << 20 }, (err, stdout, stderr) => {
      let said = null
      try { said = JSON.parse((stdout || '').trim().split('\n').pop()) } catch {}
      // a door that ran answers in JSON; anything else (no python, no door, a crash) is a door that couldn't run.
      // stderr can carry a traceback quoting the request: only its last line, and only to this session
      const ran = said !== null && (!err || typeof err.code === 'number')
      resolve({ code: err ? err.code : 0, said, ran,
        why: (said && said.error) || `the release door could not run (${(stderr || err?.message || '').trim()
          .split('\n').pop().slice(-120)})` })
    })
    p.stdin.on('error', () => {})
    p.stdin.end(input ?? '')
  })
}

/** The tiers this agent's session carries ([] = org), or null for UNKNOWN. THROWS on a malformed private grant. */
export async function readLabel(agent, opts = {}) {
  const r = await run(['label', agent], opts)
  if (!r.ran || r.code === 3) return null
  if (r.code !== 0) throw new Error(r.why)
  if (!Array.isArray(r.said) || !r.said.every(t => typeof t === 'string')) return null
  return r.said
}

/** A labelled (or UNKNOWN) member's send, written by the door. Returns the row id. THROWS with the door's reason,
 * and then no row was written. */
export async function releaseSend(agent, req, opts = {}) {
  const r = await run(['send'], { ...opts, agent, input: JSON.stringify(req) })
  if (r.code !== 0 || !Number.isInteger(r.said?.id)) throw new Error(r.why)
  return r.said.id
}
