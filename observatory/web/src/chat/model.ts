import { api, obsKey } from '../api'
import type { Msg, Step } from '../types'

/* /chat's data layer (plan-11884). A chat is ONE wire thread, `chat:<id>`. Nothing here writes a message except
   through the store's send (POST /api/messages): one row per recipient, all on the same thread (R4). */

export const CHAT_PREFIX = 'chat:'
export const isChat = (t: string | null | undefined) => !!t && t.startsWith(CHAT_PREFIX)

export function newThread(): string {
  const d = new Date()
  const day = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
  const rnd = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => b.toString(36).padStart(2, '0')).join('').slice(0, 6)
  return `${CHAT_PREFIX}${day}-${rnd}`
}

/* @mentions: the names that exist on the roster, in the order typed, deduplicated */
export function mentions(body: string, roster: string[]): string[] {
  const known = new Set(roster)
  const out: string[] = []
  for (const m of body.matchAll(/(^|[\s(])@([a-z0-9][a-z0-9_-]{0,40})/gi)) {
    const n = m[2].toLowerCase()
    if (known.has(n) && !out.includes(n)) out.push(n)
  }
  return out
}

/* who is in a chat: every non-owner party of its rows, first-seen order */
export function participants(rows: Msg[], roster: string[]): string[] {
  const known = new Set(roster)                     // agents only: pulse, a canvas, a federation peer never join
  const out: string[] = []
  for (const m of rows) for (const n of [m.from, m.to]) if (n && known.has(n) && !out.includes(n)) out.push(n)
  return out
}

/* the body every recipient gets: alone, the text as typed; with others, a first line naming the team, so each agent
   knows who else hears this thread and can answer them on it */
export function bodyFor(text: string, to: string[], me: string): string {
  if (to.length < 2) return text
  return `[chat with ${to.filter((n) => n !== me).map((n) => '@' + n).join(' ')} — everyone here reads this thread; reply on it]\n${text}`
}

export const FILE_EMBED = /\[\[file:([^\]\n]+)\]\](?: \(([^)\n]{1,120})\))?/g    // an upload adds its display name
export interface Embed { path: string; label?: string }
export function embeds(body: string): Embed[] { return [...body.matchAll(FILE_EMBED)].map((m) => ({ path: m[1].trim(), label: m[2] })) }
export function stripEmbeds(body: string): string { return body.replace(FILE_EMBED, '').replace(/^\[chat with [^\]]*\]\n/, '').trim() }
export const fileUrl = (path: string) => `/api/chat/file?path=${encodeURIComponent(path)}`
export function kindOf(path: string): 'image' | 'pdf' | 'audio' | 'video' | 'text' | 'other' {
  const e = path.toLowerCase().split('.').pop() ?? ''
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'avif'].includes(e)) return 'image'
  if (e === 'pdf') return 'pdf'
  if (['mp3', 'm4a', 'ogg', 'wav', 'flac'].includes(e)) return 'audio'
  if (['mp4', 'webm', 'mov'].includes(e)) return 'video'
  if (['txt', 'md', 'csv', 'json', 'log', 'py', 'ts', 'tsx', 'sql', 'yaml', 'yml', 'toml', 'sh', 'html'].includes(e)) return 'text'
  return 'other'
}

/* D1/D2 (plan-11884): a file is FETCHED with the owner key as a header (the file route refuses ?key=, so no URL this
   page builds ever carries the key), and its type is the RESPONSE's (serve_untrusted sniffed it), never one this page
   names. What the page then does with it is one of three shapes the active-content census (C5) accepts: an image or a
   media element's src, a text node, or a download. */
export async function fetchFile(path: string): Promise<Response> {
  const r = await fetch(fileUrl(path), { headers: { 'x-obs-key': obsKey() } })
  if (!r.ok) throw new Error(r.status === 404 ? 'that file is not readable from here' : `the file did not load (${r.status})`)
  return r
}
export function showMedia(el: HTMLImageElement | HTMLAudioElement | HTMLVideoElement, b: Blob) {
  if (el.src.startsWith('blob:')) URL.revokeObjectURL(el.src)
  el.src = URL.createObjectURL(b)
}
export function download(b: Blob, name: string) {
  const url = URL.createObjectURL(b)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export interface Uploaded { path: string; name: string; size: number; type: string }   // name: display only (D3)
export async function upload(file: Blob, name: string): Promise<Uploaded> {
  const r = await fetch(`/api/chat/upload?name=${encodeURIComponent(name)}`, {
    method: 'POST', body: file, headers: { 'x-obs-key': obsKey(), 'content-type': 'application/octet-stream' },
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j.error || `the upload failed (${r.status})`)
  return j as Uploaded
}

/* ------------------------------------------------------------------------------------------------- projects */
export interface Project { id: string; name: string; brief: string; agents: string[]; threads: string[] }
export interface Projects { etag: string; projects: Project[] }
export const loadProjects = () => api<Projects>('/chat/projects')
export async function saveProjects(etag: string, projects: Project[]): Promise<Projects> {
  const r = await fetch('/api/chat/projects', {
    method: 'PUT', body: JSON.stringify(projects),
    headers: { 'content-type': 'application/json', 'if-match': etag, 'x-obs-key': obsKey() },
  })
  const j = await r.json().catch(() => ({}))
  if (r.status === 409) throw Object.assign(new Error(j.error), { fresh: j as Projects })
  if (!r.ok) throw new Error(j.error || `projects did not save (${r.status})`)
  return j as Projects
}
export const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'project'

/* ------------------------------------------------------------------------------------------------- commands */
export interface Skill { name: string; description: string }
export interface McpTool { server: string; name: string; description: string }
export async function loadCommands(): Promise<{ skills: Skill[]; tools: McpTool[] }> {
  const [c, t] = await Promise.all([
    api<{ skills: Skill[] }>('/chat/commands').catch(() => ({ skills: [] })),
    api<{ servers: { server: string; tools: { name: string; description?: string }[] }[] }>('/tools').catch(() => ({ servers: [] })),
  ])
  const tools = t.servers.flatMap((s) => s.tools.map((x) => ({ server: s.server, name: x.name, description: x.description ?? '' })))
  return { skills: c.skills, tools }
}

/* ------------------------------------------------------------------------------------------------- work */
/* D4: the thread's work at TURN level (server: /api/chat/work). A turn belongs to every thread it touched; its other
   threads come named. `live` is each agent's newest unlinked steps ("current work, any thread"); `unlinked` counts
   the older ones that were never filed. */
export interface Turn { id: number; agent: string; started_at: string | null; ended_at: string | null; input_msg_id: number | null; elsewhere: string[]; steps: Step[] }
export interface Work { turns: Turn[]; live: Record<string, Step[]>; unlinked: Record<string, number> }
export const loadWork = (thread: string) => api<Work>(`/chat/work?thread=${encodeURIComponent(thread)}`)

/* ------------------------------------------------------------------------------------------------- steps */
export async function stepsOf(agent: string, limit = 120): Promise<Step[]> {
  const rows = await api<Step[]>(`/steps?agent=${encodeURIComponent(agent)}&limit=${limit}`)
  return [...rows].sort((a, b) => a.id - b.id)
}

/* a step in domain language: what the agent DID, in a few words, never a dump. Tool steps arrive as
   "Bash: <its own description>" or "mcp__server__tool: <args>"; the tool's done-marks carry nothing and are dropped. */
export function stepLine(s: Step): string {
  const c = (s.content ?? '').replace(/\s+/g, ' ').trim()
  if (s.kind === 'tool') {
    const m = /^([\w.:-]+?):\s*(?:·\s*)?(.*)$/.exec(c)
    if (!m) return c.replace(/^mcp__\w+?__/, '').slice(0, 120)
    const tool = m[1].replace(/^mcp__\w+?__/, '')
    return m[2] ? `${tool}  ${m[2].slice(0, 110)}` : tool
  }
  return c.slice(0, 140)
}
export const visible = (s: Step) => s.kind !== 'tool_done' && s.kind !== 'response' && s.kind !== 'heartbeat'
