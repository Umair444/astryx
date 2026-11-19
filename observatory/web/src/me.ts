/* THE LABEL (owner 11-13: "the username replaces local"). Signed in: who you are and the org you are in, by its name.
   Otherwise (the key door, no sign-in, a build without LOGIN): null, and every caller keeps today's label. One read of
   /auth/me per page, shared by the header and the sidebar. Its own module: auth.ts stays importless (it runs alone
   under node in tests/test_observatory_auth_ui.py). */
import { useEffect, useState } from 'react'
import { LOGIN, readMe } from './auth'
import type { AuthOrg, Me, MeState } from './auth'
import { chosenOrg } from './cog'

let mePromise: Promise<MeState> | null = null

export function useMe(): Me | null {
  const [me, setMe] = useState<Me | null>(null)
  useEffect(() => {
    if (!LOGIN) return
    let live = true
    ;(mePromise ??= readMe()).then((m) => { if (live && m.state === 'in') setMe(m.me) })
    return () => { live = false }
  }, [])
  return me
}

/* the org you are in, as your membership names it: the chosen one, else your only one */
export function hereOrg(me: Me | null): AuthOrg | undefined {
  if (!me) return undefined
  const pick = chosenOrg()
  return me.orgs.find((x) => x.org === pick) ?? (me.orgs.length === 1 ? me.orgs[0] : undefined)
}

export function whoLabel(me: Me | null, fallback: string): string {
  if (!me) return fallback
  return `${me.user} · ${hereOrg(me)?.name ?? fallback}`
}

/* THE ADMIN PANE's door: signed in as the owner or an admin of the org you are in (its backend's own answer, via
   /auth/me). The owner key alone opens no account panel: accounts are the front's, and a key is no account. */
export const canAdmin = (me: Me | null) => ['owner', 'admin'].includes(hereOrg(me)?.role ?? '')

/* the OWNER's own acts (the org's standards): signed in as its owner, or the key door (no account: only the owner holds the key) */
export const isOwnerHere = (me: Me | null) => !me || hereOrg(me)?.role === 'owner'
