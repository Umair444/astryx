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
  /* The agents/ directory tree is the org structure: group_path is the chain of
     composite folder labels from the root down to this agent (empty = a free agent
     on the ring), and rank orders members inside their group (null = a peer, no
     chain arrow). Nested paths render as nested organs. Owner-only in practice. */
  group_path?: string[]
  rank?: number | null
  /* actual model from the agent's latest turn (charter Model: pin as fallback) */
  model?: string | null
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
  turn_id?: number | null // the turn that produced this message (peel-open)
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

/* GET /api/services — host services under observation */
export interface ServiceRow {
  unit: string
  active: boolean
  state: string
  description: string
  since: string | null
}

/* POST /api/services/{unit}/{action} — owner only; row state rides along */
export interface ServiceActionResult extends ServiceRow {
  ok: boolean
  error: string | null
}

/* GET /api/triggers — the org's alarm clock */
export interface TriggerRow {
  agent: string
  name: string
  schedule: string
  kind: 'heartbeat' | 'sql' | 'python' | string
  enabled: boolean
  last_fired: string | null
  next_fire: string | null
  note: string | null
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

/* GET /api/system — host stats for the Monitor tab */
export interface SysInfo {
  specs: { hostname: string; os: string; cpu: string; cores: number; threads: number; ram_total: number; boot_time: number }
  cpu: { percent: number; per_core: number[]; freq_mhz: number | null; load: number[] }
  mem: { total: number; used: number; available: number; percent: number; swap_total: number; swap_used: number; swap_percent: number }
  disks: { mount: string; fstype: string; total: number; used: number; percent: number }[]
  net: { sent: number; recv: number }
  gpu: { name: string; util: number | null; mem_used: number | null; mem_total: number | null; temp: number | null }[]
  wifi: { iface: string | null; quality: number | null; signal_dbm: number | null }
  temps: { label: string; current: number; high: number | null }[]
  uptime: number
  ts: number
}
export interface Proc { pid: number; name: string; user: string; cpu: number; mem: number }

/* SQL workbench (Monitor's DBeaver-like sibling) */
export interface DbList { databases: string[]; current: string }
export interface DbSchema { database: string; schemas: Record<string, { name: string; type: string }[]> }
export type Cell = string | number | boolean | null
export interface QueryResult {
  columns?: string[]
  rows?: Cell[][]
  rowCount?: number
  elapsed_ms?: number
  command?: string
  error?: string
}
export interface SqlNode { name: string; path: string; dir: boolean; children?: SqlNode[] }

/* the Turn atom (plan-2 §5) — one contract for Theatre, Threads, Profiles */
export interface Turn {
  id: number
  agent: string
  started_at: string | null
  ended_at: string
  duration_ms: number | null
  source: string | null
  num_responses: number
  num_tools: number
  num_steps: number
  char_count: number
  tokens_in: number
  tokens_out: number
  model: string | null
  input_msg_id: number | null
  input_prompt: string | null
  response_text: string | null
  output_msg_ids: number[] | null
}

export interface TurnEvent {
  kind: 'response' | 'tool'
  text?: string
  name?: string
  brief?: string
}

export interface TurnDetail {
  id: number
  agent: string
  source: string | null
  started_at: string | null
  ended_at: string
  duration_ms: number | null
  tokens_in: number
  tokens_out: number
  model: string | null
  input_prompt: string | null
  trigger: { id: number; from_agent: string; from_org: string; to_agent: string; thread: string | null; intent: string | null; body: string } | null
  outputs: { id: number; to_agent: string; to_org: string; thread: string | null; intent: string | null; body: string }[]
  events: TurnEvent[]
}

/* GET /api/agents/{name}/profile — the self, parsed from the charter md */
export interface Profile {
  agent: string
  bio: string | null
  sections: { heading: string; body: string }[]
  avatar: boolean
  group_path: string[]
  rank: number | null
  stats: { turns: number; tokens_out: number; messages_sent: number; steps: number; first_seen: string | null }
  history: { hash: string; author: string; date: string; subject: string }[]
}
