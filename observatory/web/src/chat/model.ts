import { api, obsKey } from '../api'
import { isHuman, type Msg, type Step } from '../types'

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

/* who is in a chat: the agents that exchanged a message WITH THE OWNER here (the owner wrote to them, or they wrote
   to the owner), first-seen order. An agent→agent row on an owner thread (seed correcting finance, a handoff) stays
   in the history and draws its divider, but never makes its sender a recipient: the owner's next reply would copy
   them in silently (workspace.py agents_of is the same rule for the list) */
export function participants(rows: Msg[], roster: string[]): string[] {
  const known = new Set(roster)                     // agents only: pulse, a canvas, a federation peer never join
  const out: string[] = []
  for (const m of rows) {
    const n = isHuman(m.from) ? m.to : isHuman(m.to) ? m.from : null      // the human side: the owner or a member
    if (n && known.has(n) && !out.includes(n)) out.push(n)
  }
  return out
}

/* the body every recipient gets: alone, the text as typed; with others, a first line naming the team, so each agent
   knows who else hears this thread and can answer them on it */
/* a message to several agents is a TEAM: the server stamps each row {team, lead} and every agent reads its own lead/
   helper line (channel/team.mjs), so the body stays the human's words. The old "[chat with …]" prefix is still
   stripped on display for rows written before (stripEmbeds). */
export function bodyFor(text: string, _to: string[], _me: string): string { return text }
/* the order rows are written in: helpers first, the lead (first named) LAST, so a bare follow-up goes to the lead */
export function teamOrder(to: string[]): string[] { return to.length > 1 ? [...to.slice(1), to[0]] : [...to] }

export const FILE_EMBED = /\[\[file:([^\]\n]+)\]\](?: \(([^)\n]{1,120})\))?/g    // an upload adds its display name
export interface Embed { path: string; label?: string }
export function embeds(body: string): Embed[] { return [...body.matchAll(FILE_EMBED)].map((m) => ({ path: m[1].trim(), label: m[2] })) }
/* an annotation ask's [[ann:<id>]] marker (artifacts/annotate/ask.ts) is the margin's, never the reader's */
/* a project chat's first message opens with the project's context block (projects/context.ts): the agents', hidden here */
export const PROJECT_BLOCK = /^\[project: [^\]\n]{1,80}\]\n(?:[\s\S]*?\n\[\/project\]\n?|[\s\S]*$)/
export function stripEmbeds(body: string): string { return body.replace(FILE_EMBED, '').replace(/\s*\[\[ann:[\w.-]{1,80}\]\]/g, '').trimStart().replace(PROJECT_BLOCK, '').replace(/^\[chat with [^\]]*\]\n/, '').trim() }
/* a body as it READS: its text runs and its [[file:]] embeds in place (thread/Inline.tsx draws a file where it was
   embedded), cleaned exactly as stripEmbeds cleans: with no embed, the one text run IS stripEmbeds(body) */
export type Part = { text: string } | { embed: Embed }
export function parts(body: string): Part[] {
  const clean = body.replace(/\s*\[\[ann:[\w.-]{1,80}\]\]/g, '').trimStart().replace(PROJECT_BLOCK, '').replace(/^\[chat with [^\]]*\]\n/, '')
  const out: Part[] = []
  let at = 0
  const run = (s: string) => { const t = s.trim(); if (t) out.push({ text: t }) }
  for (const m of clean.matchAll(FILE_EMBED)) {
    run(clean.slice(at, m.index))
    out.push({ embed: { path: m[1].trim(), label: m[2] } })
    at = m.index! + m[0].length
  }
  run(clean.slice(at))
  return out
}
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
/* a file's size without its bytes: a one-byte Range read of the same gated route (Content-Range carries the total);
   null when it can't tell */
export async function fileSize(path: string): Promise<number | null> {
  const r = await fetch(fileUrl(path), { headers: { 'x-obs-key': obsKey(), range: 'bytes=0-0' } })
  if (r.status === 206) await r.arrayBuffer()                  // the one byte; a server that ignored the range: let go
  else void r.body?.cancel().catch(() => {})
  if (!r.ok) throw new Error(r.status === 404 ? 'that file is not readable from here' : `the file did not load (${r.status})`)
  const n = Number(/\/(\d+)\s*$/.exec(r.headers.get('content-range') ?? '')?.[1] ?? (r.status === 200 ? r.headers.get('content-length') : NaN))
  return Number.isFinite(n) ? n : null
}
/* An SVG (the server typed it image/svg+xml only after proving the bytes are one: serve.is_svg) is drawn from a data:
   URL, never a blob: one. Inside the <img> both are inert, but a blob: URL carries THIS page's origin, so "Open image
   in new tab" would run the SVG's script as a document beside the owner key; a data: document's origin is opaque. */
const showing = new WeakMap<HTMLElement, Blob>()
export function showMedia(el: HTMLImageElement | HTMLAudioElement | HTMLVideoElement, b: Blob) {
  if (el.src.startsWith('blob:')) URL.revokeObjectURL(el.src)
  showing.set(el, b)
  if (el instanceof HTMLImageElement && b.type.split(';')[0].trim() === 'image/svg+xml') {
    el.removeAttribute('src')
    const fr = new FileReader()
    fr.onload = () => { if (showing.get(el) === b && typeof fr.result === 'string') el.src = fr.result }
    fr.readAsDataURL(b)
    return
  }
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
/* iteration 5: a project = its instructions (the brief its team works under), its TEAM, its conversations (any owner
   surface), its pinned files (artifact ids); created/updated are stamped by the server. Logic: projects/model.ts */
export interface Project {
  id: string; name: string; instructions: string; agents: string[]; threads: string[]; files: string[]
  color?: string | null; emoji?: string | null; created?: string | null; updated?: string | null; missing?: string[]
}
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
export interface Turn { id: number; agent: string; started_at: string | null; ended_at: string | null; input_msg_id: number | null; elsewhere: string[]; steps: Step[]
  msgs?: number[] }               // this thread's rows the turn wrote (the server's back-filled turn_id; a live copy has none)
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
