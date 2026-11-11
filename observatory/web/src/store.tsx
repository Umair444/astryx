import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api, apiPost, eventsUrl, fetchWhoami, noteServerTime, parseTs } from './api'
import type { AgentRow, DagEvent, Goal, Msg, Overview, Peer, Presence, WhoAmI, WireEvent } from './types'

/* one wire pulse — the network view animates the from→to edge for a moment.
   Orgs ride along so the anonymous map can animate org<->peer boundary edges. */
export interface Flash {
  key: number
  from: string
  to: string | null
  from_org: string | null
  to_org: string | null
  thread?: string | null // the floor pairs a message's two copies in a cog (sender's outbound, receiver's inbound) on these
  body?: string
}

/* the live stream's health (iteration 14, "stamina"): the workspace says it calmly, never a frozen spinner.
   live = connected; reconnecting = lost it, retrying with backoff; offline = the browser says there is no network;
   back = reconnected and caught up (shown a moment, then live). `resync` counts catch-ups: a view that holds its own
   copy of the wire (the chat's open thread) refetches what it missed when it moves. */
export type ConnState = 'connecting' | 'live' | 'reconnecting' | 'offline' | 'back'
export interface Conn { state: ConnState; since: number; resync: number }

/* one merge for every way a row arrives (the initial page, SSE, a backfill after a reconnect, "load older", the
   owner's own send): by id, ascending, never twice — whatever order they come in */
/* …with ONE exception to "the first copy wins": the stream's copy of an agent's row is the INSERT's, turn_id still null
   (the Stop hook back-fills it when the turn ends), and a later read of the same row names its turn. That copy
   replaces the held one in place, or the reply could never be paired with its "Worked … · N tool calls" (11-11). */
export const fillsTurn = (held: Msg | undefined, m: Msg) => !!held && !held.turn_id && !!m.turn_id
export function mergeMsgs(cur: Msg[], add: Msg[]): Msg[] {
  if (!add.length) return cur
  const at = new Map(cur.map((m, i) => [m.id, i]))
  let up: Msg[] | null = null
  for (const m of add) {
    const i = at.get(m.id)
    if (i !== undefined && fillsTurn((up ?? cur)[i], m)) (up ??= [...cur])[i] = m
  }
  if (up) cur = up
  const seen = new Set(at.keys())
  const fresh = add.filter((m) => !seen.has(m.id) && (seen.add(m.id), true))
  if (!fresh.length) return cur
  const last = cur.length ? cur[cur.length - 1].id : -Infinity
  if (fresh.every((m, i) => m.id > (i ? fresh[i - 1].id : last))) return [...cur, ...fresh]   // the common case: new tail
  return [...cur, ...fresh].sort((a, b) => a.id - b.id)
}
/* the org-wide feed is a WINDOW, not a log: a tab left open for days must not keep every row it ever heard. The
   newest FEED_CAP rows stay (the wire view's "load older" raises the floor for as long as the tab lives). */
export const FEED_CAP = 2000
const STEP_FLUSH_MS = 1000         // step events are folded into the roster at most once a second (one render, not N)
const WATCHDOG_MS = 60_000         // the server names a ping every 25 s (and on connect): 60 s of silence = a dead socket
const BACKOFF_MAX_MS = 15_000     // a restarted API is found within ~15 s of coming back

interface Store {
  conn: Conn
  overview: Overview | null
  agents: AgentRow[]
  messages: Msg[] // one org-wide feed, ascending by id
  loadMax: number // max id at initial load (older rows skip the entrance anim)
  goals: Goal[]
  peers: Peer[]
  flash: Flash | null
  presence: Record<string, Presence> // owner-only: where each agent's attention is
  dagEvent: DagEvent | null // latest {type:'dag'} pulse — tools view refetches on it
  loadOlder: () => Promise<number>
  who: WhoAmI // owner unlocks the composer, vega gates the concierge
  whoChecked: boolean // false until the first /whoami answer — gates the lock panels
  recheckWho: () => Promise<WhoAmI>
  send: (to: string, body: string, thread?: string) => Promise<Msg>
  refreshGoals: () => void
}

const Ctx = createContext<Store>(null as unknown as Store)
export const useStore = () => useContext(Ctx)

export function StoreProvider({ children }: { children: ReactNode }) {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [agents, setAgents] = useState<AgentRow[]>([])
  const [messages, setMessages] = useState<Msg[]>([])
  const [loadMax, setLoadMax] = useState(0)
  const [goals, setGoals] = useState<Goal[]>([])
  const [peers, setPeers] = useState<Peer[]>([])
  const [flash, setFlash] = useState<Flash | null>(null)
  const [presence, setPresence] = useState<Record<string, Presence>>({})
  const [dagEvent, setDagEvent] = useState<DagEvent | null>(null)
  const [who, setWho] = useState<WhoAmI>({ owner: false, vega: false })
  const [whoChecked, setWhoChecked] = useState(false)
  const [conn, setConn] = useState<Conn>({ state: 'connecting', since: Date.now(), resync: 0 })
  const capRef = useRef(FEED_CAP)
  const capped = (xs: Msg[]) => (xs.length > capRef.current ? xs.slice(xs.length - capRef.current) : xs)

  // whoami FIRST — every data effect below waits on it so an anonymous
  // visitor never fires an owner-only fetch (zero 403 console spam)
  const recheckWho = useCallback(async () => {
    const w = await fetchWhoami().catch(() => ({ owner: false, vega: false }))
    setWho(w) // fresh identity every check — data + SSE effects re-fire on key change
    setWhoChecked(true)
    return w
  }, [])
  useEffect(() => {
    recheckWho()
  }, [recheckWho])

  // owner composer — optimistic append; SSE delivers the same row, dedupe by id
  const send = useCallback(async (to: string, body: string, thread?: string) => {
    const t0 = Date.now()
    const m = await apiPost<Msg>('/messages', { to, body, thread: thread ?? null })
    noteServerTime(parseTs(m.ts), 0, t0, Date.now())   // the row's stamp: the server's clock to the microsecond (api.ts)
    setMessages((cur) => capped(mergeMsgs(cur, [m])))
    return m
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const oldestRef = useRef<number | null>(null)
  useEffect(() => {
    oldestRef.current = messages[0]?.id ?? null
  }, [messages])

  const loadOlder = useCallback(async () => {
    const before = oldestRef.current
    if (!before) return 0
    const older = await api<Msg[]>(`/messages?limit=100&before_id=${before}`).catch(() => [] as Msg[])
    if (older.length)
      setMessages((now) => {
        const next = mergeMsgs(now, older)
        capRef.current = Math.max(capRef.current, next.length + 200)   // what the reader asked for stays
        return next
      })
    return older.length
  }, [])

  // initial load + slow refresh of the aggregates — waits for whoami; the
  // agent/goal endpoints are owner-only and must never fire for anonymous
  useEffect(() => {
    if (!whoChecked) return
    const owner = who.owner
    if (!owner) {
      setAgents([]) // key forgotten → drop private data immediately
      setGoals([])
    }
    const refresh = () => {
      api<Overview>('/overview').then(setOverview).catch(() => {})
      if (owner) api<AgentRow[]>('/agents').then(setAgents).catch(() => {})
    }
    const slow = () => {
      if (owner) api<Goal[]>('/goals').then(setGoals).catch(() => {})
      api<Peer[]>('/peers').then(setPeers).catch(() => {})
    }
    refresh()
    slow()
    api<Msg[]>('/messages?limit=150') // public: server returns only cross-org rows for anonymous
      .then((msgs) => {
        // the owner keeps a row the stream already delivered (once); a reader who is NOT the owner (a key forgotten)
        // gets exactly this page: every private row held before is dropped, never merged forward
        setMessages((cur) => (owner ? capped(mergeMsgs(msgs, cur)) : msgs))
        setLoadMax(msgs.length ? Math.max(...msgs.map((m) => m.id)) : 0)
      })
      .catch(() => {})
    const t1 = setInterval(refresh, 30_000)
    const t2 = setInterval(slow, 60_000)
    return () => {
      clearInterval(t1)
      clearInterval(t2)
    }
  }, [whoChecked, who])

  const refreshGoals = useCallback(() => {
    if (who.owner) api<Goal[]>('/goals').then(setGoals).catch(() => {})
  }, [who.owner])

  useEffect(() => {
    if (who.owner) api<Presence[]>('/presence').then(rows => setPresence(Object.fromEntries(rows.map(r => [r.agent, r])))).catch(() => {})
  }, [who.owner])

  // the newest id this tab holds: where a backfill starts after the stream was lost
  const maxIdRef = useRef(0)
  useEffect(() => {
    const last = messages.length ? messages[messages.length - 1].id : 0
    if (last > maxIdRef.current) maxIdRef.current = last
  }, [messages])

  // one SSE pipe: new messages land in the feed, steps freshen the agent roster.
  // Reconnects whenever recheckWho lands (key saved/forgotten) so the ?key= is current.
  // STAMINA (iteration 14): the tab is left open all day on a laptop that sleeps and changes networks. EventSource's own
  // retry is not enough: an HTTP error (a proxy's 502 while the API restarts) closes it FOR GOOD, a slept laptop's socket
  // can half-die and stay "open" in silence, and nothing it missed ever comes back. So this effect owns the connection:
  // backoff with jitter (1 s → 15 s), a watchdog on the server's named ping, a reconnect on `online` and on the tab's
  // return after a long hide, and on every reconnect a BACKFILL (GET /api/messages?after_id=<newest held>, paged) plus a
  // refresh of the roster, presence and overview; `conn.resync` tells views holding their own copy to catch up too.
  useEffect(() => {
    if (!whoChecked) return
    let es: EventSource | null = null
    let dead = false
    let attempt = 0
    let retry: ReturnType<typeof setTimeout> | undefined
    let backT: ReturnType<typeof setTimeout> | undefined
    let heard = Date.now()
    let pinged = false             // this server names its pings (an older one sends comments: no watchdog then)
    let lost = false               // the stream dropped since the last good open: the next open backfills
    let hiddenAt = document.hidden ? Date.now() : 0
    const owner = who.owner
    const state = (st: ConnState) => setConn((c) => (c.state === st ? c : { ...c, state: st, since: Date.now() }))

    // steps, folded: an agent at work emits several a second; the roster (and everything reading it) renders once a second
    let stepBuf = new Map<string, { kind: string; n: number }>()
    let stepT: ReturnType<typeof setTimeout> | undefined
    const flushSteps = () => {
      stepT = undefined
      const buf = stepBuf
      stepBuf = new Map()
      const seen = new Date().toISOString()
      setAgents((cur) =>
        cur.some((a) => buf.has(a.agent))
          ? cur.map((a) => { const b = buf.get(a.agent); return b ? { ...a, last_kind: b.kind, last_seen: seen, steps: a.steps + b.n } : a })
          : cur,
      )
    }

    const backfill = async () => {
      let after = maxIdRef.current
      const got: Msg[] = []
      for (let page = 0; page < 20 && after > 0; page++) {               // ≤ 10,000 rows; past that the window is full anyway
        const rows = await api<Msg[]>(`/messages?after_id=${after}&limit=500`).catch(() => null)
        if (!rows) break
        got.push(...rows)
        if (rows.length < 500) break
        after = rows[rows.length - 1].id
      }
      if (got.length) setMessages((cur) => capped(mergeMsgs(cur, got)))
      api<Overview>('/overview').then(setOverview).catch(() => {})
      if (owner) {
        api<AgentRow[]>('/agents').then(setAgents).catch(() => {})
        api<Presence[]>('/presence').then((rows) => setPresence(Object.fromEntries(rows.map((r) => [r.agent, r])))).catch(() => {})
      }
      setConn((c) => ({ ...c, resync: c.resync + 1 }))
    }

    const onMsg = (ev: MessageEvent) => {
      heard = Date.now()
      let e: WireEvent
      try {
        e = JSON.parse(ev.data)
      } catch {
        return
      }
      // the Room (ui/room.tsx) and anything else that wants the raw stream listens here: one connection, many ears
      window.dispatchEvent(new CustomEvent('ax:event', { detail: e }))
      if (e.type === 'message') {
        const { type: _t, ...m } = e
        setMessages((cur) => capped(mergeMsgs(cur, [m as Msg])))
        setFlash({ key: m.id, from: m.from, to: m.to, from_org: m.from_org, to_org: m.to_org, thread: m.thread, body: m.body })
        return
      }
      if (e.type === 'presence') {
        const { type: _t, ...p } = e
        setPresence((cur) => ({ ...cur, [p.agent]: p as Presence }))
        return
      }
      if (e.type === 'resync') {          // the server's LISTEN tap was down: rows inserted meanwhile never came
        void backfill()
        return
      }
      if (e.type === 'dag') {
        setDagEvent({ ...e }) // fresh identity every pulse so effects re-fire
        return
      }
      if (e.type === 'step') {
        const b = stepBuf.get(e.agent)
        stepBuf.set(e.agent, { kind: e.kind, n: (b?.n ?? 0) + 1 })
        stepT ??= setTimeout(flushSteps, STEP_FLUSH_MS)
      }
    }

    const drop = () => {
      es?.close()
      es = null
    }
    const schedule = (now = false) => {
      clearTimeout(retry)
      if (dead) return
      const base = Math.min(BACKOFF_MAX_MS, 1000 * 2 ** attempt)
      attempt = Math.min(attempt + 1, 10)
      retry = setTimeout(connect, now ? 0 : base * (0.75 + Math.random() * 0.5))
    }
    const connect = () => {
      clearTimeout(retry)
      if (dead) return
      drop()
      const s = new EventSource(eventsUrl())
      es = s
      s.onopen = () => {
        if (es !== s) return
        attempt = 0
        heard = Date.now()
        if (lost) {
          lost = false
          state('back')
          void backfill()
          clearTimeout(backT)
          backT = setTimeout(() => state('live'), 2500)
        } else state('live')
      }
      s.onmessage = onMsg
      s.addEventListener('ping', () => { heard = Date.now(); pinged = true })
      // ANY error: close it ourselves and retry on our own backoff (the browser's retry stops for good on an HTTP error)
      s.onerror = () => {
        if (es !== s) return
        drop()
        lost = true
        state(navigator.onLine === false ? 'offline' : 'reconnecting')
        schedule()
      }
    }
    const resume = () => {               // the network is back, or the tab is: reconnect now if the stream is in doubt
      if (dead) return
      if (!es || es.readyState !== EventSource.OPEN || Date.now() - heard > WATCHDOG_MS) {
        lost = true
        attempt = 0
        schedule(true)
      }
    }
    const onOnline = () => { lost = true; attempt = 0; schedule(true) }     // a changed network: the old socket is suspect
    const onOffline = () => state('offline')
    const onVis = () => {
      if (document.hidden) { hiddenAt = Date.now(); return }
      const away = hiddenAt ? Date.now() - hiddenAt : 0
      hiddenAt = 0
      // back after a hide: the browser may have throttled or frozen the tab; catch up whatever the stream says (one
      // after_id read when nothing was missed; the open thread refetches its own tail on the resync)
      if (away > 5_000) { void backfill(); resume() }
    }
    const watch = setInterval(() => {
      if (dead || !es || !pinged) return
      if (es.readyState === EventSource.OPEN && Date.now() - heard > WATCHDOG_MS) {
        drop()
        lost = true
        state('reconnecting')
        schedule(true)
      }
    }, 10_000)
    addEventListener('online', onOnline)
    addEventListener('offline', onOffline)
    document.addEventListener('visibilitychange', onVis)
    connect()
    return () => {
      dead = true
      drop()
      clearTimeout(retry)
      clearTimeout(backT)
      clearTimeout(stepT)
      clearInterval(watch)
      removeEventListener('online', onOnline)
      removeEventListener('offline', onOffline)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [whoChecked, who]) // eslint-disable-line react-hooks/exhaustive-deps

  const value = useMemo(
    () => ({ conn, overview, agents, messages, loadMax, goals, peers, flash, presence, dagEvent, loadOlder, who, whoChecked, recheckWho, send, refreshGoals }),
    [conn, overview, agents, messages, loadMax, goals, peers, flash, presence, dagEvent, loadOlder, who, whoChecked, recheckWho, send, refreshGoals],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
