import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { obsKey } from './api'
import type { AgentRow, Presence } from './types'

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
export const safeBase = (b: unknown): b is string => typeof b === 'string' && /^\/(o\/[a-z0-9][a-z0-9._-]*\/)?$/i.test(b)

export function chosenOrg(): string | null {
  const m = document.cookie.match(/(?:^|;\s*)astryx_org=([^;]*)/)
  return m ? decodeURIComponent(m[1]) : null
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

const Ctx = createContext<Cog>(NONE)
export const useCog = () => useContext(Ctx)

export function CogProvider({ children }: { children: ReactNode }) {
  const [cog, setCog] = useState<Cog | null>(null)
  useEffect(() => { fetchCog().then(setCog).catch(() => setCog(NONE)) }, [])
  if (!cog) return null                                        // one request: never a flash of 409s
  const pick = chosenOrg()
  if (cog.cog && !cog.orgs.some(o => o.org === pick)) return <CogChooser cog={cog} />
  return <Ctx.Provider value={cog}>{children}</Ctx.Provider>
}

function CogChooser({ cog }: { cog: Cog }) {
  return (
    <div className="min-h-dvh grid place-items-center bg-deck text-ink px-4">
      <div className="w-full max-w-md">
        <div className="text-[13px] text-ink-mute mb-1">a cog of {cog.orgs.length} orgs</div>
        <h1 className="text-xl font-semibold mb-1">Which org do you want to open?</h1>
        <p className="text-[13px] text-ink-dim mb-5">The Floor shows every org at once. The other tabs show the org you open here, and you can switch from the Floor at any time.</p>
        <div className="flex flex-col gap-2">
          {cog.orgs.map(o => (
            <button key={o.name} onClick={() => o.org && chooseOrg(o.org)}
              className="flex items-baseline justify-between rounded-xl border border-line bg-deck-2 px-4 py-3 text-left hover:border-line-2">
              <span className="font-medium">{o.name}</span><span className="font-mono text-[11px] text-ink-mute">{o.org}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
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
