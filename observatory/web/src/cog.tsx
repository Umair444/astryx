import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { obsKey } from './api'
import type { AgentRow, Overview, Presence } from './types'

/* THE COG (owner ruling #60083: several orgs on one install are a cog; forge's API #60437/#60439/#60441).
   One org: /api/cog is the observatory's own answer, {cog: false} with the one entry, and nothing below changes a thing.
   A cog: the front at :8090 lists every org with its /o/<org>/ base, and has NO home org (seed's ruling 3(b)), so the
   root /api/* goes to the org the VIEWER chose, named by the astryx_org cookie that only this app sets. Until a choice is
   made the root answers 409, so the app shows the cog's rooms to choose from instead of a broken page. */

export interface CogOrg { org: string | null; name: string; base: string; badge?: string | null }
export interface Cog { cog: boolean; home: string | null; orgs: CogOrg[]; error?: string }

const COOKIE = 'astryx_org'
const NONE: Cog = { cog: false, home: null, orgs: [] }

/* A base is the server's word, and the owner key rides every read under it: only a same-origin path of the one shape the
   front serves ("/" or "/o/<registry name>/") is ever used, so a base can never carry the key to another host. */
export const safeBase = (b: unknown): b is string => typeof b === 'string' && /^\/(o\/[a-z0-9][a-z0-9._-]*\/)?$/.test(b)

export function chosenOrg(): string | null {
  const m = document.cookie.match(/(?:^|;\s*)astryx_org=([^;]*)/)
  try { return m ? decodeURIComponent(m[1]) : null } catch { return null }   // a malformed cookie is no choice: the chooser shows
}

/* a room switch is a cookie change plus a reload: every tab reads the root store, which now answers for that org */
export function chooseOrg(org: string) {
  document.cookie = `${COOKIE}=${encodeURIComponent(org)}; Path=/; SameSite=Strict; Max-Age=31536000`
  location.reload()
}

/* whoami first, as the store does, so a visitor to one org never fires the owner-only /api/cog (zero 403s): a 409 is a
   cog's front with no org chosen yet (its /api/cog is public), an owner reads /api/cog, and a visitor is one room. */
async function fetchCog(): Promise<Cog> {
  const key = obsKey()
  const headers: Record<string, string> = key ? { 'x-obs-key': key } : {}
  const w = await fetch('/api/whoami', { headers })
  if (w.status !== 409 && !(await w.json().catch(() => ({}))).owner) return NONE
  const r = await fetch('/api/cog', { headers })
  if (r.status === 403 || r.status === 404) return NONE
  const j = await r.json().catch(() => ({}))
  if (!r.ok) return { ...NONE, error: j.error ?? `cog registry unreadable (HTTP ${r.status})` }   // fails closed, and SAYS so
  const orgs = (Array.isArray(j.orgs) ? j.orgs : []).filter((o: CogOrg) => o && typeof o.name === 'string' && safeBase(o.base))
  return { cog: j.cog === true && orgs.length > 0, home: j.home ?? null, orgs }
}

/* Canvas is each org's own in a cog (forge #60765): served at /o/<org>/canvas/ with its session cookie on that Path, so a
   link to the bare /canvas/ goes nowhere there and a relayed one would loop on login. Fixed for the page's life: a room
   switch reloads. One org: /canvas/, as always. */
let CANVAS = '/canvas/'
export const canvasBase = () => CANVAS

const Ctx = createContext<Cog>(NONE)
export const useCog = () => useContext(Ctx)

/* `chooser` is what a cog shows before the viewer has chosen a room (components/CogBuilding.tsx: the building itself,
   every room with its people, so the choice is made looking at them). It is passed in, never imported here, so this
   module stays below every component that reads it. One org never calls it. */
export function CogProvider({ children, chooser }: { children: ReactNode; chooser: (cog: Cog) => ReactNode }) {
  const [cog, setCog] = useState<Cog | null>(null)
  useEffect(() => { fetchCog().then(setCog).catch(() => setCog(NONE)) }, [])
  if (!cog) return null                                        // one request: never a flash of 409s
  const pick = chosenOrg()
  const choosing = cog.cog && !cog.orgs.some(o => o.org === pick)
  const base = cog.cog ? cog.orgs.find(o => o.org === pick)?.base : undefined
  CANVAS = base && safeBase(base) ? `${base}canvas/` : '/canvas/'
  return (
    <Ctx.Provider value={cog}>
      <BuildingProvider cog={cog}>{choosing ? chooser(cog) : children}</BuildingProvider>
    </Ctx.Provider>
  )
}

/* THE BUILDING (the owner's ask 10-19: "make the cog well integrated in observatory"): every room of the cog, read
   through its OWN base (its backend checks its OWN key), shared by the header's room chips and the building sheet so
   one read serves both. A room is `reading` until its first answer, then `open`, `locked` (its people are private to
   this key) or `down` (its observatory didn't answer: the next read retries). One org: nothing is read, ever. */
export type RoomState = 'reading' | 'open' | 'locked' | 'down'
export interface RoomLive extends RoomData { org: string; name: string; base: string; state: RoomState; overview: Overview | null; at: number | null }
interface Building { rooms: RoomLive[]; refresh: () => void }
const BuildingCtx = createContext<Building>({ rooms: [], refresh: () => {} })
export const useBuilding = () => useContext(BuildingCtx)
const READ_MS = 30_000                                         // the store's and the Floor's cadence

export async function readLive(o: CogOrg): Promise<RoomLive> {
  const [room, ov] = await Promise.allSettled([readRoom(o.base), roomGet<Overview>(o.base, '/overview')])
  const data = room.status === 'fulfilled' ? room.value : { agents: [], presence: {}, badge: null, locked: true }
  // /overview is public on every backend: no answer at all, or the front's 502, is a room whose observatory is down
  const st = ov.status === 'rejected' ? (ov.reason as { status?: number }).status : 200
  const state: RoomState = ov.status === 'rejected' && (st === undefined || st >= 500) ? 'down' : data.locked ? 'locked' : 'open'
  return { org: o.org ?? '', name: o.name, base: o.base, ...data, state,
           overview: ov.status === 'fulfilled' ? ov.value : null, at: Date.now() }
}

function BuildingProvider({ cog, children }: { cog: Cog; children: ReactNode }) {
  const orgs = cog.cog ? cog.orgs.filter(o => o.org && safeBase(o.base)) : []
  const key = orgs.map(o => o.org + o.base).join('|')
  const [rooms, setRooms] = useState<RoomLive[]>(() => orgs.map(o => ({
    org: o.org!, name: o.name, base: o.base, state: 'reading', overview: null, at: null,
    agents: [], presence: {}, badge: o.badge ?? null, locked: false })))
  const [tick, setTick] = useState(0)
  const refresh = useCallback(() => setTick(t => t + 1), [])
  useEffect(() => {
    if (!orgs.length) return
    let live = true
    const read = () => orgs.forEach(o => readLive(o).then(r => live && setRooms(cur => cur.map(x => (x.org === r.org ? r : x)))))
    read()
    const t = setInterval(read, READ_MS)
    return () => { live = false; clearInterval(t) }
  }, [key, tick])
  if (!cog.cog) return <>{children}</>
  return <BuildingCtx.Provider value={{ rooms, refresh }}>{children}</BuildingCtx.Provider>
}

/* one sibling room's people, read through its own base; its backend checks its OWN key, so a key that isn't valid there
   leaves the room's people unknown (locked), never borrowed from another org */
export interface RoomData { agents: AgentRow[]; presence: Record<string, Presence>; badge: string | null; locked: boolean }

export async function roomGet<T>(base: string, path: string): Promise<T> {
  if (!safeBase(base)) throw new Error('unsafe base')
  const key = obsKey()
  const r = await fetch(`${base}api${path}`, { headers: key ? { 'x-obs-key': key } : {} })
  if (!r.ok) throw Object.assign(new Error(`${base}api${path}: ${r.status}`), { status: r.status })
  return r.json()
}

export async function readRoom(base: string): Promise<RoomData> {
  const [agents, presence, me] = await Promise.allSettled([
    roomGet<AgentRow[]>(base, '/agents'), roomGet<Presence[]>(base, '/presence'), roomGet<Cog>(base, '/cog')])
  return {
    agents: agents.status === 'fulfilled' && Array.isArray(agents.value) ? agents.value : [],
    presence: presence.status === 'fulfilled' && Array.isArray(presence.value) ? Object.fromEntries(presence.value.map(p => [p.agent, p])) : {},
    badge: me.status === 'fulfilled' ? me.value.orgs?.[0]?.badge ?? null : null,
    locked: agents.status === 'rejected',
  }
}

/* the merged stream: every backend's /api/events tagged with its org; the key goes to each, which applies its own view */
export function cogStreamUrl(): string {
  const key = obsKey()
  return '/api/cog/stream' + (key ? `?key=${encodeURIComponent(key)}` : '')
}
