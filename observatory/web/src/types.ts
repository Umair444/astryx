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
  /* agent kind from the charter tree: resident | stationed | worker | envoy */
  type?: string
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

export interface EconDay {
  day: string
  bill: number // billable-equivalent tokens (real cost), NOT raw
  out: number
  turns: number
}

export interface EconAgent {
  agent: string
  bill: number
  out: number
  turns: number
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

/* live usage %, authoritative from the /usage API — captured on each agent turn */
export interface EconAuthoritative {
  measured_at: string
  measured_by: string
  subscription: string | null
  five_hour_pct: number | null
  seven_day_pct: number | null
  seven_day_opus_pct: number | null
  five_hour_reset: string | null // ISO8601
  seven_day_reset: string | null // ISO8601
  five_hour_eta_100: string | null // ISO, or null if not rising
  five_hour_rate_pp_h: number // percentage-points per hour
  seven_day_eta_100: string | null
  seven_day_rate_pp_h: number
}

export interface EconSeriesPoint {
  t: string
  five: number | null
  seven: number | null
}

export interface EconHeatCell {
  day: string // 'YYYY-MM-DD'
  bill: number // billable-equivalent tokens
  out: number
  turns: number
}

export interface EconBurn {
  bill_per_min: number
  bill_24h: number
}

export interface EconModel {
  model: string
  turns: number
}

export interface EconSummary {
  bill_24h: number
  out_24h: number
  turns_24h: number
  agents_24h: number
}

/* ── the dissipative-system layer (nucleus/econ.py) — served under the `econ` key ──
   The org as a measured dissipative structure. One law: G = W / (Φ·K).
   Φ = billable flux, W = budgets of goals VERIFIED in window (value enters only at
   the boundary), K = compressed self-description bytes, Q = heat = flux that
   produced no boundary value. First law: Φ = W-attributable + Q. */

/* one day of the daily series — ≤90 days ascending; MISSING DAYS ARE GAPS
   (the org was dark) — render gaps, never zero-fill */
export interface EconDissipativeDay {
  day: string
  phi: number | null
  W: number | null
  eta: number | null
  G: number | null // ×1e9 scale (per-GB·tok)
  heat_frac: number | null
  attributed_frac: number | null
  K: number | null // compressed self-description bytes
  theil: number | null
  turns: number | null
}

export interface EconThermo {
  phi: number
  turns: number
  phi_goal_attributed: number
  W: number
  goals_shipped: number
  heat_instant_turns: number
  heat_instant_phi: number
  heat_instant_frac: number | null
  eta: number | null
}

/* live today-so-far reading — the day is still open */
export interface EconToday extends EconThermo {
  day: string
}

export interface EconPnlRow {
  agent: string
  burned: number
  turns: number
  value_earned: number
  net: number
}

export interface EconTriggerTfp {
  trigger: string
  day: string
  cost_per_fire: number
  fires: number
}

export interface EconSenseRow {
  sense: string
  calls: number
  first_call: string
  saved_est: number | null // calls × median_wake_cost, tokens
}

export interface EconProductivity {
  window_days: number
  median_wake_cost: number | null
  trigger_tfp: EconTriggerTfp[]
  senses: EconSenseRow[]
}

/* the Goodhart detectors */
export interface EconIntegrity {
  budget_cpi: number | null
  verify_latency_h_median: number | null
  milestone_rate: number | null // fraction 0..1
  unattributed_spend_note: string
}

export interface EconLatest {
  day: string
  G: number | null // ×1e9 scale (per-GB·tok)
  K: { raw: number; compressed: number } // bytes
  thermo: EconThermo
  final_heat: { final_heat_phi: number }
  pnl: EconPnlRow[]
  trigger_roi?: { agent: string; trigger: string; fires: number; cost: number; value_reached: number; roi: number }[]
  theil_burn: number | null
  productivity: EconProductivity
  integrity: EconIntegrity
}

export interface EconDissipative {
  series: EconDissipativeDay[]
  latest: EconLatest | null
  today: EconToday | null
}

export interface Economy {
  authoritative: EconAuthoritative | null
  econ: EconDissipative
  series: EconSeriesPoint[]
  heatmap: EconHeatCell[]
  daily: EconDay[]
  agents: EconAgent[]
  models: EconModel[]
  summary: EconSummary
  burn: EconBurn
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

/* a sense — one afferent endpoint (sensors/<agent>/<name>.py, served on :8460) */
export interface Sense {
  agent: string
  name: string
  path: string
  description: string
}

export interface ToolsResponse {
  servers: ToolServer[]
  total_tools: number
  senses?: Sense[]
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

/* GET /api/services — every astryx unit (filesystem-derived from units/) */
export interface ServiceRow {
  unit: string
  active: boolean
  state: string
  enabled?: boolean // enabled/static = survives reboot; false = won't come back
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
  events?: TurnEvent[] // present when the list is fetched with events=1 (Theatre)
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

/* GET/PUT /api/wire/routes — a channel's inbound map (bridges/routes-<ch>.json).
   Extra keys (a discord webhook) ride the index signature and are preserved. */
export interface WireRoute {
  chat: string
  agent: string
  enabled?: boolean
  open?: boolean
  live_steps?: boolean
  note?: string
  webhook?: string
  trusted_jids?: string[]
  trusted_ids?: number[]
  [k: string]: unknown
}

export interface ChannelRoutes {
  channel: string
  routes: WireRoute[]
  trusted_key: 'trusted_jids' | 'trusted_ids'
}

/* GET /api/wire/contacts — every match for a name, so the owner resolves conflicts */
export interface ContactMatch {
  channel: string
  label: string
  number: string | null
  handle: string
  native: string // the platform chat id (handle minus the channel: prefix)
}

/* GET /api/agents/{name}/profile — an agent AS A PERSON (main.py agent_profile).
   Distinct from the older charter-parse Profile below, which a different view uses. */
export interface AgentProfile {
  name: string
  exists: boolean
  status: 'live' | 'dormant' | 'retired'
  live: boolean
  retired: boolean
  group_path: string[]
  department: string | null
  rank: number | null
  model: string | null
  perspective: string
  has_charter: boolean
  stats: { steps: number; turns: number; billable_tokens: number; last_seen: string | null }
  relations: { agent: string; messages: number }[]
  peers: string[]
}

/* POST /api/agents — bring an agent into the world */
export interface AgentCreateResult {
  ok: boolean
  name: string
  charter_path: string
  spawn_rc: number
  spawn_out: string
  live: boolean
}

/* POST /api/agents/{name}/retire */
export interface AgentRetireResult {
  ok: boolean
  name: string
  retired: boolean
  body_stopped: boolean
}

/* POST /api/agents/{name}/spawn — respawn / revive */
export interface AgentSpawnResult {
  ok: boolean
  name: string
  rc: number
  out: string
  live: boolean
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
