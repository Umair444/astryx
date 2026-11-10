import { apiSend, obsKey } from '../../api'
import type { Msg } from '../../types'
import { embeds, fetchFile } from '../model'

/* The artifact store's client (homes/seed/chat-rebuild/ARTIFACTS_API.md). An artifact is a file a conversation
   produced or was given, kept as a git history server-side: opening a [[file:]] chip IMPORTS it (an agent re-sending
   the same name later is a new version by that agent), and an owner edit or a restore is a new commit, never a
   rewrite. Every route is owner-only, so every fetch carries the header, never a ?key=.

   DEGRADED MODE: while the store is not there (404/5xx on /api/ws/artifacts/open), an artifact is the plain file read
   through /api/chat/file, with no versions; `store: false` tells the panel to hide what needs history. */

export type Kind = 'text' | 'table' | 'code' | 'image' | 'pdf' | 'docx' | 'sheet' | 'audio' | 'video' | 'binary'

export interface Version { rev: string; short: string; n: number; author: string; ts: string; message: string }
export interface Artifact {
  id: string
  thread: string
  name: string
  kind: Kind
  path_in_store: string
  size: number
  head: string
  versions: Version[]        // newest first
}
/* what the panel holds: the artifact plus where it came from (the source path re-opens it; `store` = has history) */
export interface Opened extends Artifact { source: string; store: boolean }

export interface MediaItem { path: string; label?: string; name: string; kind: Kind; from: string; ts: string; msg_id: number }

/* the kind by extension: the contract's table, plus the media the browser plays itself */
const EXT: Record<string, Kind> = {
  md: 'text', markdown: 'text', txt: 'text', log: 'text',
  csv: 'table', tsv: 'table',
  json: 'code', sql: 'code', py: 'code', ts: 'code', tsx: 'code', js: 'code', sh: 'code', yaml: 'code', yml: 'code',
  html: 'code', css: 'code', toml: 'code',
  png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', webp: 'image', svg: 'image', avif: 'image',
  pdf: 'pdf', docx: 'docx', xlsx: 'sheet',
  mp3: 'audio', m4a: 'audio', ogg: 'audio', wav: 'audio', flac: 'audio',
  mp4: 'video', webm: 'video', mov: 'video',
}
export const extOf = (name: string) => (/\.([a-z0-9]+)$/i.exec(name)?.[1] ?? '').toLowerCase()
export const kindOfName = (name: string): Kind => EXT[extOf(name)] ?? 'binary'
export const EDITABLE: Kind[] = ['text', 'table', 'code']
export const isProse = (name: string) => ['md', 'markdown', 'txt', 'log', ''].includes(extOf(name))

/* the display name of an embed: its label (an upload's own filename), else the basename; an upload's stored name is a
   uuid, which is never shown */
const UUID = /^[0-9a-f]{32}\.[a-z0-9]+$/
export function nameOf(path: string, label?: string): string {
  const base = path.split('/').pop() ?? path
  if (label && /\.[a-z0-9]{1,5}$/i.test(label)) return label
  if (UUID.test(base)) return label ? `${label}.${extOf(base)}` : `attachment.${extOf(base)}`
  return base
}

/* ------------------------------------------------------------------------------------------------- open */
let storeUp: boolean | null = null      // learned on the first open; a later success flips it back
const missing = (e: unknown) => { const s = (e as { status?: number }).status ?? 0; return s === 404 || s === 405 || s >= 500 || s === 0 }

/* `art:<id>` opens a STORED artifact by id (the library, a project's files): nothing is re-imported, so a file whose
   source is gone still opens with its whole history */
export const byId = (id: string) => `art:${id}`
export async function openArtifact(path: string, thread: string, author: string, label?: string): Promise<Opened> {
  if (path.startsWith('art:')) {
    const a = await getArtifact(path.slice(4))
    return { ...a, kind: a.kind === 'binary' ? kindOfName(a.name) : a.kind, source: path, store: true }
  }
  const name = nameOf(path, label)
  if (storeUp !== false) {
    try {
      const a = await apiSend<Artifact>('POST', '/ws/artifacts/open', { path, thread, author, label: name })
      storeUp = true
      return { ...a, kind: a.kind === 'binary' ? kindOfName(a.name) : a.kind, source: path, store: true }
    } catch (e) {
      if (!missing(e)) throw e
      storeUp = false
      setTimeout(() => { storeUp = null }, 60_000)     // the backend is being built beside this: look again soon
    }
  }
  return { id: `file:${path}`, thread, name, kind: kindOfName(name), path_in_store: '', size: 0, head: '', versions: [], source: path, store: false }
}

/* ------------------------------------------------------------------------------------------------- content */
/* a version's bytes, cached by (id, rev): a revision is immutable, so a tab switch or a diff never refetches */
const cache = new Map<string, Promise<Blob>>()
export function contentOf(a: Opened, rev?: string): Promise<Blob> {
  const r = rev || a.head
  const key = a.store ? `${a.id}@${r}` : `file:${a.source}`
  let p = cache.get(key)
  if (!p) {
    p = a.store
      ? fetch(`/api/ws/artifacts/${encodeURIComponent(a.id)}/content${r ? `?rev=${encodeURIComponent(r)}` : ''}`, { headers: { 'x-obs-key': obsKey() } })
          .then((res) => { if (!res.ok) throw new Error(`the file did not load (${res.status})`); return res.blob() })
      : fetchFile(a.source).then((res) => res.blob())
    p.catch(() => cache.delete(key!))
    cache.set(key, p)
    if (!a.store) setTimeout(() => cache.delete(key!), 30_000)     // no revision to pin a plain file to
  }
  return p
}
export const textOf = async (a: Opened, rev?: string) => (await contentOf(a, rev)).text()

/* ------------------------------------------------------------------------------------------------- writes */
export const saveArtifact = (id: string, text: string, message?: string) =>
  apiSend<Artifact>('POST', `/ws/artifacts/${encodeURIComponent(id)}/save`, { text, ...(message ? { message } : {}) })
export const restoreArtifact = (id: string, rev: string) =>
  apiSend<Artifact>('POST', `/ws/artifacts/${encodeURIComponent(id)}/restore`, { rev })
export const getArtifact = (id: string) => apiSend<Artifact>('GET', `/ws/artifacts/${encodeURIComponent(id)}`)

/* ------------------------------------------------------------------------------------------------- media */
/* every file in a thread: the server's list when it has one, else the embeds in the rows this page already holds */
export async function loadMedia(thread: string, rows: Msg[]): Promise<MediaItem[]> {
  try {
    const r = await fetch(`/api/ws/media?thread=${encodeURIComponent(thread)}`, { headers: { 'x-obs-key': obsKey() } })
    if (r.ok) return (await r.json() as MediaItem[]).map((m) => ({ ...m, kind: m.kind === 'binary' ? kindOfName(m.name) : m.kind }))
  } catch { /* the store is not up: read the rows */ }
  return mediaOfRows(rows)
}
export function mediaOfRows(rows: Msg[]): MediaItem[] {
  const out: MediaItem[] = []
  for (const m of rows) for (const e of embeds(m.body)) {
    const name = nameOf(e.path, e.label)
    out.push({ path: e.path, label: e.label, name, kind: kindOfName(name), from: m.from, ts: m.ts, msg_id: m.id })
  }
  return out
}
/* one entry per file, at its newest mention (a message sent to three agents is three rows carrying the same embed) */
export function distinctMedia(items: MediaItem[]): MediaItem[] {
  const by = new Map<string, MediaItem>()
  for (const m of items) by.set(m.path, m)
  return [...by.values()].sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts))
}
