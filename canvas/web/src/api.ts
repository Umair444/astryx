// The one door to the canvas bridge. The session is an HttpOnly cookie (never readable here);
// every write carries x-astryx so a cross-site form can't forge one.

// served at <host>/canvas/ (one org) or <host>/o/<org>/canvas/ (a cog): BASE is './', so every call is relative to
// the page, which the hash router never moves
export const BASE = import.meta.env.BASE_URL

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function call<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const init: RequestInit = { method, credentials: 'same-origin', headers: { ...headers } }
  if (method !== 'GET') (init.headers as Record<string, string>)['x-astryx'] = '1'
  if (body instanceof Blob) init.body = body
  else if (body !== undefined) {
    ;(init.headers as Record<string, string>)['content-type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  const r = await fetch(BASE + 'api' + path, init)
  if (!r.ok) {
    let msg = `${r.status}`
    try { msg = (await r.json()).error ?? msg } catch { /* not json */ }
    throw new ApiError(r.status, msg)
  }
  return r.json()
}

export const get = <T>(p: string) => call<T>('GET', p)
export const post = <T>(p: string, b?: unknown, h?: Record<string, string>) => call<T>('POST', p, b ?? {}, h)
export const del = <T>(p: string) => call<T>('DELETE', p)

/* ONE SIGN-IN with the workspace (owner 11-17: canvas "require obs key seperately"; "should seem like a part of whole
   astryx"): the workspace keeps the owner key in this origin's storage (observatory/web/src/api.ts obsKey, 'obs_key');
   canvas is served on the same origin, so a page that has it signs in with it instead of asking again. Painted pages
   can't read it: they render in the opaque-origin sandbox (CanvasView SANDBOX: no allow-same-origin). Signing out of
   canvas holds it off for this tab. */
const SIGNED_OUT = 'cv.signedout'
export function workspaceKey(): string {
  try { return sessionStorage.getItem(SIGNED_OUT) ? '' : localStorage.getItem('obs_key') ?? '' } catch { return '' }
}
export function signedOut() { try { sessionStorage.setItem(SIGNED_OUT, '1') } catch { /* private mode */ } }

/* the org's members, by account, as the org knows them: the front's /auth/people for the org this page sits under
   (/o/<org>/canvas/); [] where there is no front sign-in */
export async function peopleHere(): Promise<{ uid: string; name: string }[]> {
  const org = /^\/o\/([^/]+)\//.exec(location.pathname)?.[1]
  if (!org) return []
  try {
    const r = await fetch(`/auth/people?org=${encodeURIComponent(org)}`, { credentials: 'same-origin', cache: 'no-store' })
    return r.ok ? ((await r.json())?.people ?? []) : []
  } catch { return [] }
}
