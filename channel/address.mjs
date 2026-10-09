// The JS seam of nucleus/address.py: `send` asks it before writing a row (seed #37905). Its own module so
// tests/test_send_address.py can EXECUTE the seam, not just grep server.mjs for a call.
// The answer is Python's, read at CALL time: the roster is the agents/ tree (charter.roster()), so a
// charter spawned mid-session is addressable on its next send without restarting this ear. No list here.
// Refused → THROWS, so the MCP handler returns isError and the sender sees it in the same turn.
// Unevaluable (python missing, a timeout, a broken tree) → ALLOW with a note: this sits on every send of
// every agent, and failing closed would mute the whole org at once (secret_guard's rule, a2 #27600).
import { execFile } from 'node:child_process'

const PY = new URL('../venv/bin/python', import.meta.url).pathname
const ADDR = new URL('../nucleus/address.py', import.meta.url).pathname

export function checkAddress(to, { py = PY, addr = ADDR } = {}) {
  return new Promise((resolve, reject) => {
    execFile(py, [addr, String(to)], { timeout: 10_000 }, (err, stdout, stderr) => {
      const out = (stdout || '').trim()
      if (!err) return resolve({ ok: true, note: '' })
      if (err.code === 2 && out) return reject(new Error(out))
      resolve({ ok: true, note: ` · address unchecked (${(stderr || err.message).trim().slice(-120)})` })
    })
  })
}
