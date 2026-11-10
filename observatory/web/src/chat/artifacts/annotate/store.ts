import { useCallback, useEffect, useRef, useState } from 'react'
import { obsKey } from '../../../api'
import type { Ann } from './types'

/* An artifact's annotations: GET /api/ws/artifacts/{id}/annotations once, then every change is an OPERATION (a
   function of the list) applied optimistically and PUT with If-Match. Operations queue, so two quick highlights never
   race each other's etag. A 412 (someone else wrote: another tab, an agent) refetches, re-applies the same operation to
   the fresh list, and retries once; a failure after that rolls back to the server's list and says so. */

export type Op = (items: Ann[]) => Ann[]
const url = (id: string) => `/api/ws/artifacts/${encodeURIComponent(id)}/annotations`

async function fetchAnns(id: string): Promise<{ etag: string; items: Ann[] }> {
  const r = await fetch(url(id), { headers: { 'x-obs-key': obsKey() } })
  if (!r.ok) throw Object.assign(new Error(`annotations did not load (${r.status})`), { status: r.status })
  return r.json()
}
async function putAnns(id: string, etag: string, items: Ann[]): Promise<{ etag: string; items: Ann[] }> {
  const r = await fetch(url(id), {
    method: 'PUT', body: JSON.stringify(items),
    headers: { 'content-type': 'application/json', 'if-match': `"${etag}"`, 'x-obs-key': obsKey() },
  })
  if (!r.ok) {
    const j = await r.json().catch(() => ({}))
    throw Object.assign(new Error(j.error || `not saved (${r.status})`), { status: r.status })
  }
  return r.json()
}

export function useAnnotations(id: string | null) {
  const [items, setItems] = useState<Ann[]>([])
  const [loaded, setLoaded] = useState(false)
  const [err, setErr] = useState('')
  const server = useRef<{ etag: string; items: Ann[] }>({ etag: '', items: [] })
  const queue = useRef<Promise<void>>(Promise.resolve())
  const pending = useRef(0)

  useEffect(() => {
    let live = true
    setItems([]); setLoaded(false); setErr('')
    server.current = { etag: '', items: [] }
    if (!id) return
    fetchAnns(id).then((s) => {
      if (!live) return
      server.current = s; setItems(s.items); setLoaded(true)
    }).catch((e) => live && setErr(String((e as Error).message)))
    return () => { live = false }
  }, [id])

  const apply = useCallback((op: Op): Promise<void> => {
    if (!id) return Promise.resolve()
    setItems((cur) => op(cur))                    // optimistic
    pending.current++
    const run = async () => {
      try {
        try {
          server.current = await putAnns(id, server.current.etag, op(server.current.items))
        } catch (e) {
          if ((e as { status?: number }).status !== 412) throw e
          const fresh = await fetchAnns(id)       // someone else wrote: merge by re-applying this op to theirs
          server.current = await putAnns(id, fresh.etag, op(fresh.items))
        }
        setErr('')
      } catch (e) {
        setErr(`Annotations not saved: ${(e as Error).message}`)
        try { server.current = await fetchAnns(id) } catch { /* keep the last known */ }
      } finally {
        // once the queue drains, the server's list is the truth (it carries other writers' changes too)
        if (--pending.current === 0) setItems(server.current.items)
      }
    }
    const p = queue.current.then(run)
    queue.current = p
    return p
  }, [id])

  return { items, loaded, err, apply, clearErr: () => setErr('') }
}
