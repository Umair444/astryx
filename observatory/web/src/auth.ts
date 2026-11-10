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
   the server put in it. A rate-limit refusal names itself (it reveals nothing about the account). */
export type SignIn = 'ok' | 'mismatch' | 'slow-down' | 'unreachable'

export async function signIn(email: string, password: string): Promise<SignIn> {
  let r: Response
  try {
    r = await fetch('/auth/login', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
  } catch { return 'unreachable' }
  return r.ok ? 'ok' : r.status === 401 ? 'mismatch' : r.status === 429 ? 'slow-down' : 'unreachable'
}

export async function signOut(): Promise<boolean> {
  try { return (await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' })).ok } catch { return false }
}

/* The words, one place. Each failure says what to do next, in the interface's voice. */
export const WORDS: Record<Exclude<SignIn, 'ok'> | 'empty' | 'signout-failed', string> = {
  mismatch: "Email or password didn't match. Check both, or ask your org's owner to reset your password.",
  'slow-down': 'Too many tries. Wait a minute, then try again.',
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
