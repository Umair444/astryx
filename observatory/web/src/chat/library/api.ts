import { apiSend } from '../../api'
import { kindOfName, nameOf, type Artifact, type Kind, type MediaItem } from '../artifacts/api'

/* THE LIBRARY's data: every artifact the store holds (GET /api/ws/artifacts, no thread: newest first, each with its
   conversation's title and who made it), plus every file embedded in the owner's conversations that nobody has
   opened yet (GET /api/ws/media, no thread). Both become one Item; opening an un-imported one imports it into ITS
   conversation first (the same import a chip click makes), so the library never forks an artifact. */

export interface LibArtifact extends Artifact { title: string; author: string | null; updated: string | null; standard?: boolean; stale?: boolean }
export interface LibMedia extends MediaItem { thread: string; artifact: string | null }

export interface Item {
  key: string
  id: string | null                 // the artifact id; null = not imported yet
  name: string
  kind: Kind
  thread: string
  title: string                     // the conversation's (or project's) name
  author: string                    // who made it (v1's author, or the sender)
  ts: string                        // newest activity
  versions: number                  // 0 = not imported yet
  size: number
  head: string | null
  standard?: boolean                // the org's standard for its file type (agents start from it)
  stale?: boolean                   // its copy for agents doesn't hold the head yet
  source?: { path: string; label?: string; from: string }
}

export const loadArtifacts = () => apiSend<LibArtifact[]>('GET', '/ws/artifacts')
export const loadAllMedia = () => apiSend<LibMedia[]>('GET', '/ws/media')
/* the owner pins (or unpins) a file as the org's standard for its file type; pinning another of that type moves it */
export const setStandard = (id: string, on: boolean) => apiSend<Artifact>('PUT', `/ws/artifacts/${id}/standard`, { on })

export async function loadLibrary(): Promise<Item[]> {
  const [arts, media] = await Promise.all([loadArtifacts(), loadAllMedia().catch(() => [] as LibMedia[])])
  const titles = new Map(arts.map((a) => [a.thread, a.title]))
  const items: Item[] = arts.map((a) => ({
    key: a.id, id: a.id, name: a.name, kind: a.kind === 'binary' ? kindOfName(a.name) : a.kind, thread: a.thread, title: a.title,
    author: a.author ?? 'owner', ts: a.updated ?? '', versions: a.versions.length, size: a.size, head: a.head,
    standard: !!a.standard, stale: !!a.stale,
  }))
  for (const m of media) {
    if (m.artifact) continue
    const name = nameOf(m.path, m.label ?? undefined)
    items.push({
      key: `m:${m.thread}:${m.path}`, id: null, name, kind: m.kind === 'binary' ? kindOfName(name) : m.kind, thread: m.thread,
      title: titles.get(m.thread) ?? '', author: m.from, ts: m.ts, versions: 0, size: 0, head: null,
      source: { path: m.path, label: m.label ?? undefined, from: m.from },
    })
  }
  return items.sort((a, b) => Date.parse(b.ts || '0') - Date.parse(a.ts || '0'))
}

/* an item's artifact id, importing it into its own conversation first when nobody has opened it yet */
export async function ensureImported(it: Item): Promise<string> {
  if (it.id) return it.id
  const s = it.source!
  const a = await apiSend<Artifact>('POST', '/ws/artifacts/open', { path: s.path, thread: it.thread, author: s.from, label: it.name })
  return a.id
}
