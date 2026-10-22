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
export function participants(rows: Msg[]): string[] {
  const out: string[] = []
  for (const m of rows) for (const n of [m.from, m.to]) if (n && n !== 'owner' && !n.includes('@') && !out.includes(n)) out.push(n)
  return out
}

/* the body every recipient gets: alone, the text as typed; with others, a first line naming the team, so each agent
   knows who else hears this thread and can answer them on it */
export function bodyFor(text: string, to: string[], me: string): string {
  if (to.length < 2) return text
  return `[chat with ${to.filter((n) => n !== me).map((n) => '@' + n).join(' ')} — everyone here reads this thread; reply on it]\n${text}`
}

export const FILE_EMBED = /\[\[file:([^\]\n]+)\]\]/g
export function embeds(body: string): string[] { return [...body.matchAll(FILE_EMBED)].map((m) => m[1].trim()) }
export function stripEmbeds(body: string): string { return body.replace(FILE_EMBED, '').replace(/^\[chat with [^\]]*\]\n/, '').trim() }
export const fileUrl = (path: string) => `/api/chat/file?path=${encodeURIComponent(path)}`
export function kindOf(path: string): 'image' | 'pdf' | 'audio' | 'video' | 'text' {
  const e = path.toLowerCase().split('.').pop() ?? ''
  if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(e)) return 'image'
  if (e === 'pdf') return 'pdf'
  if (['mp3', 'm4a', 'ogg', 'wav'].includes(e)) return 'audio'
  if (['mp4', 'webm'].includes(e)) return 'video'
  return 'text'
}

/* file fetches carry the owner key as a header, so a file is fetched into a blob URL, never linked with ?key= */
export async function blobUrl(path: string): Promise<string> {
  const r = await fetch(fileUrl(path), { headers: { 'x-obs-key': obsKey() } })
  if (!r.ok) throw new Error(r.status === 404 ? 'that file is not readable from here' : `the file did not load (${r.status})`)
  return URL.createObjectURL(await r.blob())
}

export interface Uploaded { path: string; name: string; size: number; type: string }
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

/* ------------------------------------------------------------------------------------------------- steps */
export async function stepsOf(agent: string, limit = 120): Promise<Step[]> {
  const rows = await api<Step[]>(`/steps?agent=${encodeURIComponent(agent)}&limit=${limit}`)
  return [...rows].sort((a, b) => a.id - b.id)
}

/* a step in domain language: what the agent DID, in a few words, never a dump */
export function stepLine(s: Step): string {
  const c = (s.content ?? '').replace(/\s+/g, ' ').trim()
  if (s.kind === 'tool') {
    const tool = c.match(/^([\w.:-]+)/)?.[1] ?? 'a tool'
    return `${tool.replace(/^mcp__\w+__/, '')}${c.length > tool.length ? ' · ' + c.slice(tool.length).trim().slice(0, 90) : ''}`
  }
  return c.slice(0, 140)
}
