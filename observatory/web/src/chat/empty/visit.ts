import { useCallback, useEffect, useState } from 'react'
import { loadBriefing, type Briefing } from '../data'

/* THE OWNER'S VISITS (iteration 15). "While you were away" covers what happened since the owner last LOOKED: the
   workspace keeps, per browser, when this visit began (`since`, what the briefing covers) and when the owner was last
   here with the tab open and focused (`seen`, refreshed every minute and on leaving). A return after more than
   VISIT_GAP of not looking is a new visit: it covers from the last `seen`. A reload inside a visit keeps the same
   window (a refresh at 07:02 must not empty the 07:00 briefing). The first visit ever asks the server's default (12 h).
   Stored in localStorage only: a per-browser convenience, never anything the org relies on; unreadable storage just
   means every load is a first visit. */

const KEY = 'ws.visit.v1'
export const VISIT_GAP = 30 * 60_000
const BEAT = 60_000

interface Visit { since: string | null; seen: string }

function read(): Visit | null {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? 'null')
    return v && typeof v.seen === 'string' && !Number.isNaN(Date.parse(v.seen)) ? { since: typeof v.since === 'string' ? v.since : null, seen: v.seen } : null
  } catch { return null }
}
function write(v: Visit) { try { localStorage.setItem(KEY, JSON.stringify(v)) } catch { /* private mode: nothing kept */ } }

/* the visit as of `now`: a continuing one keeps its window; a return after the gap starts one from the last look */
export function visitAt(prev: Visit | null, now: number): Visit {
  if (!prev) return { since: null, seen: new Date(now).toISOString() }
  if (now - Date.parse(prev.seen) > VISIT_GAP) return { since: prev.seen, seen: new Date(now).toISOString() }
  return { since: prev.since, seen: new Date(now).toISOString() }
}

const looking = () => document.visibilityState === 'visible' && document.hasFocus()

export function useVisit(): { since: string | null; markSeen: () => void } {
  const [since, setSince] = useState<string | null>(() => { const v = visitAt(read(), Date.now()); write(v); return v.since })
  useEffect(() => {
    // the owner is here: keep `seen` fresh; coming back after the gap (a tab left open overnight) starts a new visit
    const beat = () => {
      if (!looking()) return
      const v = visitAt(read(), Date.now())
      write(v)
      setSince(v.since)
    }
    const leave = () => { const v = read(); if (v) write({ ...v, seen: new Date().toISOString() }) }
    const i = setInterval(beat, BEAT)
    const vis = () => (document.visibilityState === 'visible' ? beat() : leave())
    addEventListener('focus', beat); addEventListener('blur', leave); document.addEventListener('visibilitychange', vis)
    return () => { clearInterval(i); removeEventListener('focus', beat); removeEventListener('blur', leave); document.removeEventListener('visibilitychange', vis) }
  }, [])
  const markSeen = useCallback(() => {
    const now = new Date().toISOString()
    write({ since: now, seen: now })
    setSince(now)
  }, [])
  return { since, markSeen }
}

/* the briefing for this visit: ONE request, again when the window moves, and quietly every two minutes while shown */
export function useBriefing(since: string | null): { data: Briefing | null; failed: boolean; retry: () => void } {
  const [data, setData] = useState<Briefing | null>(null)
  const [failed, setFailed] = useState(false)
  const [n, setN] = useState(0)
  useEffect(() => {
    let on = true
    const get = () => loadBriefing(since).then((b) => { if (on) { setData(b); setFailed(false) } }, () => { if (on) setFailed(true) })
    void get()
    const i = setInterval(() => { if (document.visibilityState === 'visible') void get() }, 120_000)
    return () => { on = false; clearInterval(i) }
  }, [since, n])
  return { data, failed, retry: useCallback(() => setN((x) => x + 1), []) }
}
