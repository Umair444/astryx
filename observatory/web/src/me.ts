/* THE LABEL (owner 11-13: "the username replaces local"). Signed in: who you are and the org you are in, by its name.
   Otherwise (the key door, no sign-in, a build without LOGIN): null, and every caller keeps today's label. One read of
   /auth/me per page, shared by the header and the sidebar. Its own module: auth.ts stays importless (it runs alone
   under node in tests/test_observatory_auth_ui.py). */
import { useEffect, useState } from 'react'
import { LOGIN, readMe } from './auth'
import type { Me, MeState } from './auth'
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

export function whoLabel(me: Me | null, fallback: string): string {
  if (!me) return fallback
  const pick = chosenOrg()
  const o = me.orgs.find((x) => x.org === pick) ?? (me.orgs.length === 1 ? me.orgs[0] : undefined)
  return `${me.user} · ${o?.name ?? fallback}`
}
