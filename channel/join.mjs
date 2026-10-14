// Which identity this server speaks for, and whether it may speak at all.
// The repo's residents (spawn.sh) set ASTRYX_AGENT and nothing else: mode 'repo', unchanged behaviour.
// The Claude Code plugin also sets ASTRYX_JOIN_DIR (<plugin data>/projects). A plugin is enabled in EVERY project the
// user opens, and the org's steps and messages are public, so in that mode the server only joins the wire for a
// project that /astryx:join marked: a file <ASTRYX_JOIN_DIR>/<key>.json, key = sha256(realpath(project dir))[:32]
// (hooks/astryx_hook.py writes and reads the same key). No marker: mode 'dormant', no database, no tools.
import { createHash } from 'node:crypto'
import { readFileSync, realpathSync } from 'node:fs'

const given = v => (v && !/^\$\{.*\}$/.test(v.trim()) ? v.trim() : '')
const AGENT_NAME = /^[a-z][a-z0-9_-]{0,63}$/

export function projectKey(dir) {
  let p = dir
  try { p = realpathSync(dir) } catch { /* a vanished dir keys by its spelling */ }
  return createHash('sha256').update(p).digest('hex').slice(0, 32)
}

/** { mode: 'repo' | 'joined' | 'dormant', agent, project, marker } */
export function joinState(env = process.env, cwd = process.cwd()) {
  let joinDir = given(env.ASTRYX_JOIN_DIR)
  if (!joinDir) return { mode: 'repo', agent: env.ASTRYX_AGENT, project: null, marker: null }
  if (joinDir.includes('${')) {                 // a placeholder Claude Code left unsubstituted: use the exported var
    const data = given(env.CLAUDE_PLUGIN_DATA)
    joinDir = data ? `${data.replace(/\/+$/, '')}/projects` : ''
  }
  const project = given(env.CLAUDE_PROJECT_DIR) || cwd
  if (!joinDir) return { mode: 'dormant', agent: null, project, marker: null }
  const marker = `${joinDir.replace(/\/+$/, '')}/${projectKey(project)}.json`
  let m
  try { m = JSON.parse(readFileSync(marker, 'utf8')) } catch { return { mode: 'dormant', agent: null, project, marker } }
  const agent = AGENT_NAME.test(String(m?.agent ?? '')) ? m.agent : given(env.ASTRYX_AGENT)
  return agent ? { mode: 'joined', agent, project, marker } : { mode: 'dormant', agent: null, project, marker }
}
