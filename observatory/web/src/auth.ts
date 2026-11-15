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
/* an org this account asked for (public sign-up, cog-rebuild Phase 3): pending until a cog admin decides it */
export interface OrgRequest { id: number; key: string; name: string; state: 'pending' | 'approved' | 'rejected'; created: string | null; note: string | null }
export interface Me { user: string; orgs: AuthOrg[]; requests: OrgRequest[]; cogAdmin: boolean }

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
  const requests = (Array.isArray(j.requests) ? j.requests : []).filter((x: OrgRequest) =>
    x && typeof x.id === 'number' && typeof x.key === 'string' && typeof x.name === 'string' &&
    ['pending', 'approved', 'rejected'].includes(x.state))
  return { state: 'in', me: { user: j.user, orgs, requests, cogAdmin: j.cog_admin === true } }
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
/* AN EMAIL CODE (front.py _prove_email): a NEW account on a cog with a mailbox is made only once the six digits mailed
   to its address come back. The first submit answers 202 `code-sent`; the same submit with the code finishes it, and
   a wrong or spent code is 400 {field: code}, `bad-code`. */
async function codeStep(r: Response): Promise<'code-sent' | 'bad-code' | null> {
  if (r.status === 202) return 'code-sent'
  if (r.status !== 400) return null
  const j = await r.clone().json().catch(() => ({}))
  return j.field === 'code' ? 'bad-code' : null
}
export const CODE_WORDS = {
  sent: (email: string) => `We mailed a 6-digit code to ${email}. Enter it to finish. It lasts 10 minutes.`,
  bad: 'That code is wrong or has expired. Check the latest mail, or leave the box empty and submit for a new one.',
}

export type Accept = 'ok' | 'code-sent' | 'bad-code' | 'mismatch' | 'short' | 'gone' | 'refused' | 'slow-down' | 'origin' | 'unreachable'
export async function acceptLink(token: string, email: string, password: string, code = ''): Promise<{ out: Accept; org?: string }> {
  let r: Response
  try {
    r = await fetch('/auth/accept', {
      method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ token, email, password, ...(code ? { code } : {}) }),
    })
  } catch { return { out: 'unreachable' } }
  const step = await codeStep(r)
  if (step) return { out: step }
  if (r.ok) {
    const j = await r.json().catch(() => ({}))
    return { out: 'ok', org: typeof j.org === 'string' ? j.org : undefined }
  }
  return { out: r.status === 401 ? 'mismatch' : r.status === 400 ? 'short' : r.status === 410 ? 'gone'
    : r.status === 429 ? 'slow-down' : r.status === 403 ? 'origin' : r.status === 409 ? 'refused' : 'unreachable' }
}
export const ACCEPT_WORDS: Record<Exclude<Accept, 'ok' | 'code-sent'> | 'empty', string> = {
  'bad-code': CODE_WORDS.bad,
  mismatch: 'That email already has an account, and that is not its password. Use its password to join.',
  short: 'Use at least 12 characters for your password, and enter your email.',
  gone: 'This link has expired or was already used. Ask for a new one.',
  refused: "This invite can't be used any more: whoever sent it can no longer add people. Ask them for a new one.",
  'slow-down': WORDS['slow-down'],
  origin: WORDS.origin,
  unreachable: WORDS.unreachable,
  empty: 'Enter your email and a password.',
}

/* PUBLIC SIGN-UP (cog-rebuild Phase 3; front.py "PUBLIC SIGN-UP"). Offered only when the cog says so (/api/cog's
   `signup`, the front's ASTRYX_COG_SIGNUP flag, default off). A sign-up makes an account and a PENDING request for an
   org of your own: nothing runs until a cog admin approves it. The key is the org's address (/o/<key>), previewed live
   from the name with the server's own rule (orgs.NAME: lowercase letters, digits and dashes, at most 63). */
export function orgKey(name: string): string {
  return name.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+/, '').slice(0, 63).replace(/-+$/, '')
}
export const ORG_KEY = /^[a-z0-9][a-z0-9-]{0,62}$/

export type SignUp = 'ok' | 'code-sent' | 'bad-code' | 'mismatch' | 'taken' | 'waiting' | 'invalid' | 'slow-down' | 'origin' | 'closed' | 'unreachable'
export async function signUp(email: string, password: string, orgName: string, key: string, code = ''): Promise<{ out: SignUp; field?: string }> {
  let r: Response
  try {
    r = await fetch('/auth/signup', {
      method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ email, password, org_name: orgName, org_key: key, ...(code ? { code } : {}) }),
    })
  } catch { return { out: 'unreachable' } }
  const step = await codeStep(r)
  if (step) return { out: step, field: step === 'bad-code' ? 'code' : undefined }
  if (r.ok) return { out: 'ok' }
  if (r.status === 401) return { out: 'mismatch' }          // an existing account, not its password: the body is never read (F8)
  const j = r.status === 400 || r.status === 409 ? await r.json().catch(() => ({})) : {}
  const field = typeof j.field === 'string' ? j.field : undefined
  if (r.status === 409) return { out: field === 'org_key' ? 'taken' : 'waiting', field }
  return { out: r.status === 400 ? 'invalid' : r.status === 429 ? 'slow-down' : r.status === 403 ? 'origin'
    : r.status === 404 ? 'closed' : 'unreachable', field }
}
export const SIGNUP_WORDS: Record<Exclude<SignUp, 'ok' | 'code-sent'> | 'empty' | 'short' | 'key', string> = {
  'bad-code': CODE_WORDS.bad,
  mismatch: 'That email already has an account, and that is not its password. Use its password to ask for an org.',
  taken: 'That org address is taken. Change the name or the address.',
  waiting: 'This account already has an org waiting for approval.',
  invalid: 'Check your email, a password of at least 12 characters, and the org name.',
  'slow-down': 'Too many sign-ups from here. Try again later.',
  origin: WORDS.origin,
  closed: "This cog isn't taking new orgs right now.",
  unreachable: "Sign-up isn't answering. Check your connection, then try again.",
  empty: 'Enter your email, a password and a name for your org.',
  short: 'Use at least 12 characters for your password.',
  key: 'The address is lowercase letters, digits and dashes.',
}

/* THE COG ADMIN's queue (cog_grants; never an org role): every org request, approve with a token budget, or reject */
export interface CogRequest {
  id: number; key: string; name: string; state: 'pending' | 'approved' | 'rejected'; email: string; created: string
  budget_tokens: number | null; decided_by: string | null; decided_at: string | null; note: string | null
  provision: 'deferred' | 'done' | 'failed' | null; provision_note: string | null
}
export const cogRequests = () => authCall<{ signup: boolean; requests: CogRequest[] }>('/auth/cog/requests')
export const cogApprove = (id: number, budget: number) =>
  authCall<{ state: string; provision: string | null }>(`/auth/cog/requests/${id}/approve`, { budget_tokens: budget })
export const cogReject = (id: number, note: string) => authCall<{ state: string }>(`/auth/cog/requests/${id}/reject`, { note })
