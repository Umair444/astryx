/* SIGN-IN (goal 11859 U3, seed #61921; the contract is forge's U1U2): one account, a session the FRONT sets as an
   httpOnly cookie, and the orgs that account belongs to.
     POST /auth/login {email, password} → 200 + the session cookie | 401 {error} | 429
     POST /auth/logout
     GET  /auth/me → {user, orgs: [{org, name, role}]} | 401
   Every call is to the ROOT: the session is the front's (one for the whole cog), never an org's, so nothing here reads
   focusBase(). The org a viewer is in stays the app-set astryx_org cookie (cog.tsx chooseOrg, the walk).

   Behind a build flag until U1U2 lands: LOGIN is false unless the build sets VITE_AUTH_UI=1, and every caller reaches
   this module only under it, so a default build has no /auth request in it at all. */

export const LOGIN = (import.meta as unknown as { env: Record<string, string | undefined> }).env.VITE_AUTH_UI === '1'

export interface AuthOrg { org: string; name: string; role: string }
export interface Me { user: string; orgs: AuthOrg[] }

/* /auth/me: the account, or null when signed out (401). A front without the endpoint (404) or one that doesn't answer
   is `unavailable`: the app then runs exactly as it does without sign-in, never behind a form that can't work. */
export type MeState = { state: 'in'; me: Me } | { state: 'out' } | { state: 'unavailable' }

export async function readMe(): Promise<MeState> {
  let r: Response
  try { r = await fetch('/auth/me', { credentials: 'same-origin' }) } catch { return { state: 'unavailable' } }
  if (r.status === 401) return { state: 'out' }
  if (!r.ok) return { state: 'unavailable' }
  const j = await r.json().catch(() => null)
  if (!j || typeof j.user !== 'string') return { state: 'unavailable' }
  const orgs = (Array.isArray(j.orgs) ? j.orgs : []).filter((o: AuthOrg) =>
    o && typeof o.org === 'string' && typeof o.name === 'string' && typeof o.role === 'string')
  return { state: 'in', me: { user: j.user, orgs } }
}

/* F8 and I9 (plan-11859): a failed sign-in must not say WHICH part failed, or the form tells an outsider who is a
   member. So the outcome is the status ALONE: the 401's body is never read, and every 401 shows the same words whatever
   the server put in it. A rate-limit refusal names itself (it reveals nothing about the account), and so does the
   front's 403 for a page served from an address that isn't the cog's own (front.py: a foreign Origin). */
export type SignIn = 'ok' | 'mismatch' | 'slow-down' | 'origin' | 'unreachable'

export async function signIn(email: string, password: string): Promise<SignIn> {
  let r: Response
  try {
    r = await fetch('/auth/login', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
  } catch { return 'unreachable' }
  return r.ok ? 'ok' : r.status === 401 ? 'mismatch' : r.status === 429 ? 'slow-down'
    : r.status === 403 ? 'origin' : 'unreachable'
}

export async function signOut(): Promise<boolean> {
  try { return (await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' })).ok } catch { return false }
}

/* The words, one place. Each failure says what to do next, in the interface's voice. */
export const WORDS: Record<Exclude<SignIn, 'ok'> | 'empty' | 'signout-failed', string> = {
  mismatch: "That email and password don't match. Check both, or ask your org's owner to reset your password.",
  'slow-down': 'Too many attempts. Wait a few minutes, then try again.',
  origin: "Sign-in only works from this org's official address. Open it there and sign in again.",
  unreachable: "Sign-in isn't answering. Check your connection, then try again.",
  empty: 'Enter your email and password.',
  'signout-failed': "Couldn't sign you out. Try again.",
}

export const ROLE: Record<string, string> = { owner: 'Owner', member: 'Member', viewer: 'Viewer' }
export const roleWords = (r: string) => ROLE[r] ?? r.charAt(0).toUpperCase() + r.slice(1)

/* where to come back to after signing in: the hash the viewer was on, only ever a hash route of this app */
export function signInHref(): string {
  const back = location.hash && !location.hash.startsWith('#/sign-in') ? location.hash.slice(1) : ''
  return '#/sign-in' + (back ? `?next=${encodeURIComponent(back)}` : '')
}
export function nextHash(): string {
  const m = location.hash.match(/[?&]next=([^&]*)/)
  let n = ''
  try { n = m ? decodeURIComponent(m[1]) : '' } catch { n = '' }
  return /^\/([a-z][a-z-]*(\/[^?#]*)?)?$/i.test(n) && !n.startsWith('/sign-in') ? '#' + n : '#/'
}

/* THE ADMIN PANEL'S ACCOUNT HALF (cog-rebuild; front.py "the admin panel's ACCOUNT half"). Here, beside the sign-in, so
   this stays the one module that names /auth. The org's own half (its members rows, nodes, activity) is the org's API
   under its base (components/AdminView.tsx). Every call is same-origin with the session cookie; a state change carries
   the page's Origin, which the front requires. */
export interface AdminUser {
  uid: string; email: string | null; created: string | null; last_session: string | null; live_sessions: number
  role: string | null; roles: { node: string; role: string }[]; you: boolean
}
export interface AdminInvite { id: number; role: string; node: string; created: string; expires: string; by: string | null }
export interface AdminUsers {
  org: string; name: string; you: string; uid: string; roles: string[]; tree: boolean; users: AdminUser[]; invites: AdminInvite[]
}
export type AdminResult<T> = { ok: true; data: T } | { ok: false; status: number; why: string }

/* the front's refusals, in the interface's voice, by status (a server's own words never reach the screen) */
export const ADMIN_WORDS: Record<number | 'net', string> = {
  400: "That change isn't possible here. Check the role and where it applies.",
  401: 'Your session has ended. Sign in again.',
  403: "You can't make that change. Only an owner can manage owners, and an account in other orgs needs their admins too.",
  404: 'That person is no longer a member here.',
  409: 'Every org keeps at least one owner. Make someone else an owner first.',
  410: 'This link has expired or was already used.',
  502: "The org isn't answering. Try again in a moment.",
  503: "Accounts aren't answering. Try again in a moment.",
  net: "The observatory isn't answering. Check your connection.",
}
export const adminWords = (status: number) => ADMIN_WORDS[status] ?? ADMIN_WORDS[502]

async function authCall<T>(path: string, body?: unknown): Promise<AdminResult<T>> {
  let r: Response
  try {
    r = await fetch(path, body === undefined ? { credentials: 'same-origin', cache: 'no-store' } : {
      method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
    })
  } catch { return { ok: false, status: 0, why: ADMIN_WORDS.net } }
  if (!r.ok) return { ok: false, status: r.status, why: adminWords(r.status) }
  const j = await r.json().catch(() => null)
  return j ? { ok: true, data: j as T } : { ok: false, status: 502, why: adminWords(502) }
}

export const adminUsers = (org: string) => authCall<AdminUsers>(`/auth/admin/users?org=${encodeURIComponent(org)}`)
export const adminInvite = (org: string, role: string, node: string) =>
  authCall<{ link: string; expires: string }>('/auth/admin/invite', { org, role, node })
export const adminCancelInvite = (org: string, id: number) => authCall<{ ok: boolean }>('/auth/admin/invite/cancel', { org, id })
export const adminReset = (org: string, uid: string) => authCall<{ link: string; expires: string }>('/auth/admin/reset', { org, uid })
export const adminSignOutEverywhere = (org: string, uid: string) =>
  authCall<{ revoked: number }>('/auth/admin/revoke-sessions', { org, uid })

/* A ONE-TIME LINK (#/accept?t=…): what it opens, then using it. The token comes from the hash only. */
export interface LinkInfo { kind: 'invite' | 'reset'; org: string; name: string; role: string | null; node: string; email: string | null }
export function linkToken(): string {
  const m = location.hash.match(/[?&]t=([A-Za-z0-9_-]{20,200})(?:&|$)/)
  return m ? m[1] : ''
}
export async function readLink(t: string): Promise<LinkInfo | 'gone' | 'unavailable'> {
  if (!t) return 'gone'
  let r: Response
  try { r = await fetch(`/auth/link?t=${encodeURIComponent(t)}`, { credentials: 'same-origin', cache: 'no-store' }) }
  catch { return 'unavailable' }
  if (r.status === 410) return 'gone'
  if (!r.ok) return 'unavailable'
  const j = await r.json().catch(() => null)
  return j && (j.kind === 'invite' || j.kind === 'reset') && typeof j.org === 'string' ? j as LinkInfo : 'unavailable'
}
export type Accept = 'ok' | 'mismatch' | 'short' | 'gone' | 'refused' | 'slow-down' | 'origin' | 'unreachable'
export async function acceptLink(token: string, email: string, password: string): Promise<{ out: Accept; org?: string }> {
  let r: Response
  try {
    r = await fetch('/auth/accept', {
      method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ token, email, password }),
    })
  } catch { return { out: 'unreachable' } }
  if (r.ok) {
    const j = await r.json().catch(() => ({}))
    return { out: 'ok', org: typeof j.org === 'string' ? j.org : undefined }
  }
  return { out: r.status === 401 ? 'mismatch' : r.status === 400 ? 'short' : r.status === 410 ? 'gone'
    : r.status === 429 ? 'slow-down' : r.status === 403 ? 'origin' : r.status === 409 ? 'refused' : 'unreachable' }
}
export const ACCEPT_WORDS: Record<Exclude<Accept, 'ok'> | 'empty', string> = {
  mismatch: 'That email already has an account, and that is not its password. Use its password to join.',
  short: 'Use at least 12 characters for your password, and enter your email.',
  gone: 'This link has expired or was already used. Ask for a new one.',
  refused: "This invite can't be used any more: whoever sent it can no longer add people. Ask them for a new one.",
  'slow-down': WORDS['slow-down'],
  origin: WORDS.origin,
  unreachable: WORDS.unreachable,
  empty: 'Enter your email and a password.',
}
