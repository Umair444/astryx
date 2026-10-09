export interface Me {
  name: string
  wire: string
  owner: boolean
  home: string
  painter: string
  agents: string[]
}

export interface Agent {
  name: string
  blurb: string
  alive: boolean
  last_seen: string | null
}

export interface Msg {
  id: number
  ts: string
  from: string
  from_org: string
  to: string
  thread: string | null
  intent: string
  body: string
  status: string
}

export interface Thread {
  thread: string
  agent: string
  title: string | null
  updated_at: string
  last: string
}

export interface Canvas {
  id: number
  title: string
  agent: string
  user: string
  tier: 'org' | 'personal'
  shared_with: string[]
  crew?: string[]
  version: number
  brief: string | null
  updated_at: string
  archived: boolean
  thread?: string
  versions?: { version: number; author: string; note: string | null; ts: string }[]
}

export interface Presence {
  agent: string
  surface: string | null
  target: string | null
  say: string | null
  state: 'idle' | 'moving' | 'working' | 'done'
  updated_at: string
}

export type Route =
  | { view: 'home'; agent?: string; fresh?: number }
  | { view: 'chat'; thread: string }
  | { view: 'canvas'; id: number }
  | { view: 'people' }
