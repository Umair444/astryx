import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api, apiPost, fetchWhoami } from './api'
import type { AgentRow, Goal, Msg, Overview, Peer, WhoAmI, WireEvent } from './types'

/* one wire pulse — the network view animates the from→to edge for a moment */
export interface Flash {
  key: number
  from: string
  to: string | null
}

interface Store {
  overview: Overview | null
  agents: AgentRow[]
  messages: Msg[] // one org-wide feed, ascending by id
  loadMax: number // max id at initial load (older rows skip the entrance anim)
  goals: Goal[]
  peers: Peer[]
  flash: Flash | null
  loadOlder: () => Promise<number>
  who: WhoAmI // owner unlocks the composer, vega gates the concierge
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
  const [who, setWho] = useState<WhoAmI>({ owner: false, vega: false })

  const recheckWho = useCallback(async () => {
    const w = await fetchWhoami().catch(() => ({ owner: false, vega: false }))
    setWho(w)
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

  // initial load + slow refresh of the aggregates
  useEffect(() => {
    const refresh = () => {
      api<Overview>('/overview').then(setOverview).catch(() => {})
      api<AgentRow[]>('/agents').then(setAgents).catch(() => {})
    }
    const slow = () => {
      api<Goal[]>('/goals').then(setGoals).catch(() => {})
      api<Peer[]>('/peers').then(setPeers).catch(() => {})
    }
    refresh()
    slow()
    api<Msg[]>('/messages?limit=150')
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
  }, [])

  // one SSE pipe: new messages land in the feed, steps freshen the agent roster
  useEffect(() => {
    const es = new EventSource('/api/events')
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
        setFlash({ key: m.id, from: m.from, to: m.to })
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
  }, [])

  const value = useMemo(
    () => ({ overview, agents, messages, loadMax, goals, peers, flash, loadOlder, who, recheckWho, send }),
    [overview, agents, messages, loadMax, goals, peers, flash, loadOlder, who, recheckWho, send],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
