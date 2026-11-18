// A REQUEST MID-TASK (owner 11-18, 13133; homes/seed/progress-requests/DESIGN.md): a person's message from another
// chat while this agent is mid-turn on other work goes straight in (a short urgent ask must not wait behind hours of
// work), with one line telling the agent its choice. The line rides in a tag attribute the server stamps, never in the
// content, so the agent can tell it from a person's own words (medic 13157). Busy = its newest step is under 15 min
// old and is no turn end; the same chat's follow-up is the same work and gets no line. Unreadable: no line. Its own
// module, executed by tests/test_mid_task.py.
import { asker } from './asker.mjs'

export async function midTask(row, { pool, agent }) {
  const person = row.from_agent === 'owner' || row.from_org !== 'local' || !!asker(row)
  if (!person || !row.thread) return null
  try {
    const r = await pool.query(`SELECT kind, meta FROM steps WHERE agent=$1 AND ts > now() - interval '15 minutes'
                                ORDER BY id DESC LIMIT 1`, [agent])
    const s = r.rows[0]
    if (!s || s.kind === 'response' || s.kind === 'stopped') return null
    const m = s.meta || {}
    const ids = [...(m.turn_msgs || []), ...(m.many || [])].map(Number).filter(Number.isFinite).slice(0, 40)
    if (ids.length) {
      const t = await pool.query(`SELECT 1 FROM messages WHERE id = ANY($1::bigint[]) AND thread = $2 LIMIT 1`,
        [ids, row.thread])
      if (t.rows.length) return null
    }
    return `you are mid-task on another request. If this one is urgent and short and your current work is long, ` +
      `hand it to a helper (Agent tool, run_in_background) with msg_id=${row.id} in its brief. Otherwise finish ` +
      `your current work and reply to it first, then send this chat a one-line 'on it' before you start this one.`
  } catch {
    return null
  }
}
