/* Wire shapes — mirror observatory/api/main.py exactly. All read-only. */

export interface Overview {
  org: string
  live: number
  agents: number
  messages_24h: number
  steps_24h: number
  tokens_in_24h: number
  tokens_out_24h: number
  goals_active: number
  goals_done: number
  peers: number
}

export interface AgentRow {
  agent: string
  alive: boolean
  last_seen: string
  last_kind: string | null
  last_content: string | null
  steps: number
  tokens_in: number
  tokens_out: number
}

export interface Msg {
  id: number
  ts: string
  from: string
  from_org: string | null
  to: string | null
  to_org: string | null
  thread: string | null
  intent: string | null
  body: string
  status: string | null
}

export interface ThreadInfo {
  thread: string
  count: number
  first_ts: string
  last_ts: string
  starter: string
  preview: string
}

export type StepKind = 'tool' | 'response' | 'milestone' | 'error' | 'heartbeat'

export interface Step {
  id: number
  ts: string
  agent: string
  kind: StepKind | string
  content: string | null
  goal_id: number | null
  tokens_in: number | null
  tokens_out: number | null
}

export type GoalState = 'proposed' | 'active' | 'hibernated' | 'done' | 'refused'

export interface Goal {
  id: number
  ts: string
  title: string
  owner: string
  state: GoalState | string
  budget_tokens: number | null
  spent_tokens: number
  epoch_hours: number | null
  dead_epochs: number
  last_progress: string | null
  parent_id: number | null
  scope_note: string | null
}

export interface EconDaily {
  day: string
  tokens_in: number
  tokens_out: number
  steps: number
}

export interface EconAgent {
  agent: string
  tokens_in: number
  tokens_out: number
  steps: number
}

export interface EconGoal {
  id: number
  title: string
  owner: string
  state: string
  budget_tokens: number | null
  spent_tokens: number
}

export interface Receipt {
  id: number
  ts: string
  from_party: string
  to_party: string
  amount_tokens: number | null
  amount_money: number
  memo: string | null
}

export interface Economy {
  daily: EconDaily[]
  agents: EconAgent[]
  goals: EconGoal[]
  receipts: Receipt[]
}

export interface Peer {
  org: string
  status: string
  reputation: number
}

/* GET /api/tools — the org's toolbox: servers of tools + composite DAGs */
export interface ToolInfo {
  name: string
  description: string
}

export interface ToolServer {
  server: string
  tools: ToolInfo[]
}

export interface DagNode {
  id: string
  tool: string
  deps: string[]
}

export interface DagDef {
  name: string
  description: string
  args: Record<string, unknown>
  nodes: DagNode[]
}

export interface ToolsResponse {
  servers: ToolServer[]
  total_tools: number
  dags: DagDef[]
}

/* GET /api/dags/runs — recent composite runs */
export type DagRunStatus = 'running' | 'ok' | 'error'

export interface DagRun {
  run_id: number
  dag: string
  status: DagRunStatus | string
  started: string
  finished: string | null
}

export interface DagRunStep {
  node: string
  tool: string
  status: string
  started: string
  finished: string | null
  output: string | null
  error: string | null
}

export interface DagRunDetail {
  run: DagRun
  steps: DagRunStep[]
}

/* SSE {type:'dag'} — a run or one of its nodes changed status */
export interface DagEvent {
  type: 'dag'
  run_id: number
  dag: string
  node?: string
  status: string
}

/* GET /api/whoami — owner unlocks the composer, vega gates the concierge */
export interface WhoAmI {
  owner: boolean
  vega: boolean
}

/* /api/events SSE payloads */
export type WireEvent =
  | ({ type: 'message' } & Msg)
  | { type: 'step'; id: number; agent: string; kind: string }
  | DagEvent
