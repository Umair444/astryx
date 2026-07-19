import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api, apiPost, eventsUrl, fetchWhoami } from './api'
import type { AgentRow, DagEvent, Goal, Msg, Overview, Peer, WhoAmI, WireEvent } from './types'

/* one wire pulse — the network view animates the from→to edge for a moment.
   Orgs ride along so the anonymous map can animate org<->peer boundary edges. */
export interface Flash {
  key: number
  from: string
  to: string | null
  from_org: string | null
  to_org: string | null
}

interface Store {
  overview: Overview | null
  agents: AgentRow[]
  messages: Msg[] // one org-wide feed, ascending by id
  loadMax: number // max id at initial load (older rows skip the entrance anim)
  goals: Goal[]
  peers: Peer[]
  flash: Flash | null
  dagEvent: DagEvent | null // latest {type:'dag'} pulse — tools view refetches on it
  loadOlder: () => Promise<number>
  who: WhoAmI // owner unlocks the composer, vega gates the concierge
  whoChecked: boolean // false until the first /whoami answer — gates the lock panels
  recheckWho: () => Promise<WhoAmI>
  send: (to: string, body: string, thread?: string) => Promise<Msg>
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
  const [dagEvent, setDagEvent] = useState<DagEvent | null>(null)
  const [who, setWho] = useState<WhoAmI>({ owner: false, vega: false })
  const [whoChecked, setWhoChecked] = useState(false)

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
    const m = await apiPost<Msg>('/messages', { to, body, thread: thread ?? null })
    setMessages((cur) => (cur.some((x) => x.id === m.id) ? cur : [...cur, m]))
    return m
  }, [])

  const oldestRef = useRef<number | null>(null)
  useEffect(() => {
    oldestRef.current = messages[0]?.id ?? null
  }, [messages])

  const loadOlder = useCallback(async () => {
    const before = oldestRef.current
    if (!before) return 0
    const older = await api<Msg[]>(`/messages?limit=100&before_id=${before}`).catch(() => [] as Msg[])
    if (older.length)
      setMessages((now) => [...older.filter((o) => !now.some((m) => m.id === o.id)), ...now])
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
        setMessages(msgs)
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

  // one SSE pipe: new messages land in the feed, steps freshen the agent roster.
  // Reconnects whenever recheckWho lands (key saved/forgotten) so the ?key= is current.
  useEffect(() => {
    if (!whoChecked) return
    const es = new EventSource(eventsUrl())
    es.onmessage = (ev) => {
      let e: WireEvent
      try {
        e = JSON.parse(ev.data)
      } catch {
        return
      }
      if (e.type === 'message') {
        const { type: _t, ...m } = e
        setMessages((cur) => (cur.some((x) => x.id === m.id) ? cur : [...cur, m as Msg]))
        setFlash({ key: m.id, from: m.from, to: m.to, from_org: m.from_org, to_org: m.to_org })
        return
      }
      if (e.type === 'dag') {
        setDagEvent({ ...e }) // fresh identity every pulse so effects re-fire
        return
      }
      if (e.type === 'step') {
        const { agent, kind } = e
        setAgents((cur) =>
          cur.some((a) => a.agent === agent)
            ? cur.map((a) =>
                a.agent === agent
                  ? { ...a, last_kind: kind, last_seen: new Date().toISOString(), steps: a.steps + 1 }
                  : a,
              )
            : cur,
        )
      }
    }
    return () => es.close()
  }, [whoChecked, who])

  const value = useMemo(
    () => ({ overview, agents, messages, loadMax, goals, peers, flash, dagEvent, loadOlder, who, whoChecked, recheckWho, send }),
    [overview, agents, messages, loadMax, goals, peers, flash, dagEvent, loadOlder, who, whoChecked, recheckWho, send],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
