// The one door to the canvas bridge. The session is an HttpOnly cookie (never readable here);
// every write carries x-astryx so a cross-site form can't forge one.

// served at <host>/canvas/ — every call is relative to that base
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
