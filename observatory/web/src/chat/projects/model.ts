import { useCallback, useEffect, useRef, useState } from 'react'
import { loadProjects, saveProjects, slug, type Project, type Projects } from '../model'

/* PROJECTS (iteration 5): what claude.ai and ChatGPT call a project — instructions, knowledge files and the
   conversations held under it — plus what only astryx has: a TEAM of agents. The list is ONE file server-side
   (GET/PUT /api/chat/projects, If-Match single writer); this hook is its only client writer.

   Every change is a MUTATION (list -> list), applied optimistically, then written through a serial queue so two
   quick edits (a rename while the instructions autosave) never race each other's etag. A 409 (another tab wrote)
   re-applies the same mutation to the fresh list once, so an edit survives a concurrent one instead of clobbering it. */

export type Mutation = (list: Project[]) => Project[]

export function useProjects(onError: (msg: string) => void) {
  const [state, setState] = useState<Projects & { loaded: boolean }>({ etag: '', projects: [], loaded: false })
  const server = useRef<Projects>({ etag: '', projects: [] })       // the last list the server confirmed
  const queue = useRef<Promise<unknown>>(Promise.resolve())
  const pending = useRef<Mutation[]>([])                            // queued, not yet confirmed: still shown
  const errRef = useRef(onError)
  errRef.current = onError

  const reload = useCallback(() => loadProjects().then((p) => { server.current = p; setState({ ...p, loaded: true }) })
    .catch(() => setState((s) => ({ ...s, loaded: true }))), [])
  useEffect(() => { void reload() }, [reload])

  const mutate = useCallback((f: Mutation): Promise<boolean> => {
    pending.current.push(f)
    setState((s) => ({ ...s, projects: f(s.projects) }))
    const show = () => setState({ ...server.current, projects: pending.current.reduce((l, g) => g(l), server.current.projects), loaded: true })
    const run = async () => {
      for (let attempt = 0; attempt < 2; attempt++) {
        const base = server.current
        try {
          const saved = await saveProjects(base.etag, f(base.projects))
          server.current = saved
          pending.current = pending.current.filter((g) => g !== f)
          show()
          return true
        } catch (e) {
          const fresh = (e as { fresh?: Projects }).fresh
          if (fresh && attempt === 0) { server.current = fresh; continue }
          pending.current = pending.current.filter((g) => g !== f)
          show()                                                          // the optimistic edit rolls back
          errRef.current(fresh ? 'Projects changed somewhere else; reloaded them. Try again.' : String((e as Error).message))
          return false
        }
      }
      return false
    }
    const p = queue.current.then(run, run)
    queue.current = p
    return p
  }, [])

  return { ...state, reload, mutate }
}

/* ------------------------------------------------------------------------------------------------- pure helpers */
export const COLORS = ['violet', 'blue', 'teal', 'green', 'amber', 'orange', 'rose', 'slate'] as const
export type Color = typeof COLORS[number]
const HUE: Record<Color, number | null> = { violet: 262, blue: 218, teal: 176, green: 146, amber: 40, orange: 22, rose: 346, slate: null }
/* a project's colour as CSS, at the theme's own hue lightness (index.css --hue-l), so it reads on light and dark */
export function colorCss(c: string | null | undefined): string {
  const h = HUE[(c ?? 'violet') as Color]
  if (h === undefined) return 'var(--t-accent)'
  return h === null ? 'color-mix(in srgb, var(--t-mute) 85%, var(--t-fg))' : `hsl(${h} 62% var(--hue-l))`
}
/* a new project's colour: the least used, so a fresh one stands apart in the sidebar */
export function nextColor(list: Project[]): Color {
  const used = new Map<string, number>()
  for (const p of list) used.set(p.color ?? '', (used.get(p.color ?? '') ?? 0) + 1)
  return [...COLORS].sort((a, b) => (used.get(a) ?? 0) - (used.get(b) ?? 0))[0]
}

export function uniqueId(name: string, list: Project[]): string {
  const base = slug(name).slice(0, 36)
  const taken = new Set(list.map((p) => p.id))
  if (!taken.has(base)) return base
  for (let i = 2; ; i++) if (!taken.has(`${base}-${i}`)) return `${base}-${i}`
}

export function blank(name: string, list: Project[], seed: Partial<Project> = {}): Project {
  return { id: uniqueId(name, list), name: name.trim(), instructions: '', agents: [], threads: [], files: [], color: nextColor(list), emoji: null, ...seed }
}

export const projectOf = (thread: string, list: Project[]) => (thread ? list.find((p) => p.threads.includes(thread)) ?? null : null)

/* the mutations the workspace makes */
export const upsert = (p: Project): Mutation => (list) => (list.some((x) => x.id === p.id) ? list.map((x) => (x.id === p.id ? p : x)) : [...list, p])
export const patchOne = (id: string, f: (p: Project) => Project): Mutation => (list) => list.map((x) => (x.id === id ? f(x) : x))
export const removeOne = (id: string): Mutation => (list) => list.filter((x) => x.id !== id)
/* a conversation sits in at most one project (the server refuses two): moving it takes it out of any other */
export const moveThread = (thread: string, to: string | null): Mutation => (list) => list.map((p) => {
  const has = p.threads.includes(thread)
  if (p.id === to) return has ? p : { ...p, threads: [thread, ...p.threads] }
  return has ? { ...p, threads: p.threads.filter((t) => t !== thread) } : p
})
