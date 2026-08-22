-- ASTRYX schema v0 — the wire's truth. Six tables, no more until pain demands them.
-- db: astryx (in genesis-pg). Apply: psql "$ASTRYX_DSN" -f schema.sql

CREATE TABLE IF NOT EXISTS steps (
  id          bigserial PRIMARY KEY,
  ts          timestamptz NOT NULL DEFAULT now(),
  agent       text        NOT NULL,
  kind        text        NOT NULL,          -- tool | tool_done | response | milestone | error | heartbeat
  content     text        NOT NULL,
  goal_id     bigint,
  turn_id     bigint,                         -- FK to turns(id); back-filled by the Stop hook
  tokens_in   integer,
  tokens_out  integer,
  meta        jsonb
);
ALTER TABLE steps ADD COLUMN IF NOT EXISTS turn_id bigint;   -- migration for pre-turns installs
CREATE INDEX IF NOT EXISTS steps_agent_ts ON steps (agent, ts DESC);
CREATE INDEX IF NOT EXISTS steps_goal     ON steps (goal_id) WHERE goal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS steps_turn     ON steps (turn_id) WHERE turn_id IS NOT NULL;

-- turns: one row per prompt (an agent turn). The Stop hook reconstructs the whole
-- turn from the transcript and writes it here — the raw of everything Claude
-- generated for that prompt. steps.turn_id links each tool/response event back.
CREATE TABLE IF NOT EXISTS turns (
  id            bigserial PRIMARY KEY,
  agent         text        NOT NULL,
  session_id    text,
  started_at    timestamptz,                    -- ts of the opening prompt (from transcript)
  ended_at      timestamptz NOT NULL DEFAULT now(),
  duration_ms   integer,
  source        text,                            -- wire | trigger | heartbeat | user
  input_prompt  text,                            -- the raw prompt that opened the turn
  input_msg_id  bigint,                          -- messages.id when it came off the wire
  num_responses integer NOT NULL DEFAULT 0,      -- assistant text generations
  num_tools     integer NOT NULL DEFAULT 0,      -- tool calls in the turn
  num_steps     integer NOT NULL DEFAULT 0,      -- steps rows linked to this turn
  char_count    integer NOT NULL DEFAULT 0,      -- characters of generated text
  tokens_in     bigint  NOT NULL DEFAULT 0,
  tokens_out    bigint  NOT NULL DEFAULT 0,
  tokens_total  bigint  GENERATED ALWAYS AS (tokens_in + tokens_out) STORED,
  model         text,
  stop_reason   text,
  raw_payload   jsonb   NOT NULL DEFAULT '{}'::jsonb,   -- verbatim: {"messages":[...],"usage":{...}}
  messages      jsonb   GENERATED ALWAYS AS (raw_payload -> 'messages') VIRTUAL,  -- not stored
  -- ACCOUNT USAGE SNAPSHOT. The Stop hook calls /api/oauth/usage once per turn (throttled)
  -- and writes the ALLOWLISTED projection here — dollar/spend fields are stripped upstream
  -- (nucleus/usage_refresh.USAGE_ALLOWLIST) because `turns` is wire-readable and local.md
  -- puts finances in the human-personal tier. NULL when throttled/unconfigured/auth-rejected:
  -- a missing snapshot is never a zero reading. Shape: {fetched_at, state, subscription,
  -- rate_limit_tier, data:{five_hour_utilization, seven_day_utilization, ...resets_at, limits[]}}.
  usage_snapshot jsonb,
  usage_state              text    GENERATED ALWAYS AS (usage_snapshot ->> 'state') STORED,
  usage_subscription       text    GENERATED ALWAYS AS (usage_snapshot ->> 'subscription') STORED,
  usage_five_hour_pct      numeric GENERATED ALWAYS AS ((usage_snapshot #>> '{data,five_hour_utilization}')::numeric) STORED,
  usage_seven_day_pct      numeric GENERATED ALWAYS AS ((usage_snapshot #>> '{data,seven_day_utilization}')::numeric) STORED,
  usage_seven_day_opus_pct numeric GENERATED ALWAYS AS ((usage_snapshot #>> '{data,seven_day_opus_utilization}')::numeric) STORED,
  usage_five_hour_reset    text    GENERATED ALWAYS AS (usage_snapshot #>> '{data,five_hour_resets_at}') STORED,
  usage_seven_day_reset    text    GENERATED ALWAYS AS (usage_snapshot #>> '{data,seven_day_resets_at}') STORED,
  -- ECONOMY ATTRIBUTION (2026-08-22): which goal this turn served. Set by the Stop hook
  -- from the opening message's thread (plan-<id>/goal-<id>); the join is the value-flow
  -- edge — verified goal budgets propagate back over exactly these rows.
  goal_id       bigint
);
CREATE INDEX IF NOT EXISTS turns_goal ON turns (goal_id) WHERE goal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS turns_agent_time ON turns (agent, ended_at DESC);
CREATE INDEX IF NOT EXISTS turns_msg        ON turns (input_msg_id) WHERE input_msg_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS turns_raw_gin    ON turns USING gin (raw_payload);

-- steps -> turns FK (steps is defined above turns, so add it post-hoc, idempotent)
DO $$ BEGIN
  ALTER TABLE steps ADD CONSTRAINT steps_turn_fk
    FOREIGN KEY (turn_id) REFERENCES turns(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- turns_v: the "generated but not stored" text — a view, because a generated
-- COLUMN may not aggregate. response_text concatenates every assistant text block
-- of the turn from the verbatim raw_payload; response_texts is one element per block.
CREATE OR REPLACE VIEW turns_v AS
SELECT t.*,
  (SELECT string_agg(c->>'text', E'\n\n' ORDER BY mo, co)
     FROM jsonb_array_elements(t.raw_payload->'messages') WITH ORDINALITY AS m(msg, mo),
          jsonb_array_elements(msg->'message'->'content')  WITH ORDINALITY AS x(c,  co)
    WHERE msg->>'type' = 'assistant' AND c->>'type' = 'text') AS response_text,
  (SELECT array_agg(c->>'text' ORDER BY mo, co)
     FROM jsonb_array_elements(t.raw_payload->'messages') WITH ORDINALITY AS m(msg, mo),
          jsonb_array_elements(msg->'message'->'content')  WITH ORDINALITY AS x(c,  co)
    WHERE msg->>'type' = 'assistant' AND c->>'type' = 'text') AS response_texts
FROM turns t;

CREATE TABLE IF NOT EXISTS messages (
  id          bigserial PRIMARY KEY,
  ts          timestamptz NOT NULL DEFAULT now(),
  from_agent  text NOT NULL,
  from_org    text NOT NULL DEFAULT 'local',
  to_agent    text NOT NULL,
  to_org      text NOT NULL DEFAULT 'local',
  thread      text,
  intent      text NOT NULL DEFAULT 'chat',   -- chat | task | introduce | receipt | ...
  body        text NOT NULL,
  caps_token  text,
  sig         text,
  status      text NOT NULL DEFAULT 'pending', -- pending | delivered | dead
  delivered_at timestamptz,
  delivery    jsonb,                            -- outcome the deliverer wrote back: {ok, handle, message_id, rendered, error}
  turn_id     bigint                            -- the turn that PRODUCED this message (back-filled at Stop)
);
ALTER TABLE messages ADD COLUMN IF NOT EXISTS turn_id bigint;   -- migration for pre-turns installs
ALTER TABLE messages ADD COLUMN IF NOT EXISTS delivery jsonb;   -- migration: awaitable send reads the deliverer's result here
CREATE INDEX IF NOT EXISTS messages_inbox ON messages (to_agent, status, id);
CREATE INDEX IF NOT EXISTS messages_turn  ON messages (turn_id) WHERE turn_id IS NOT NULL;
DO $$ BEGIN
  ALTER TABLE messages ADD CONSTRAINT messages_turn_fk
    FOREIGN KEY (turn_id) REFERENCES turns(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- The full causal graph: messages.turn_id -> the turn that emitted it;
-- turns.input_msg_id -> the message that triggered it (soft link). One message is
-- thus the sender-turn's output and the receiver-turn's input, chaining turns across agents.

CREATE TABLE IF NOT EXISTS subscriptions (
  id       bigserial PRIMARY KEY,
  watcher  text NOT NULL,
  target   text NOT NULL,                    -- agent name or goal:<id>
  filter   text NOT NULL DEFAULT 'milestone,error',  -- csv of step kinds, or 'all'
  active   boolean NOT NULL DEFAULT true,
  UNIQUE (watcher, target)
);

CREATE TABLE IF NOT EXISTS goals (
  id            bigserial PRIMARY KEY,
  ts            timestamptz NOT NULL DEFAULT now(),
  title         text NOT NULL,
  parent_id     bigint REFERENCES goals(id),
  owner         text NOT NULL,
  state         text NOT NULL DEFAULT 'proposed', -- proposed|active|hibernated|done|refused
  scope_note    text,                             -- STEWARD's local.md conformance note
  budget_tokens bigint NOT NULL DEFAULT 0,
  spent_tokens  bigint NOT NULL DEFAULT 0,
  epoch_hours   integer NOT NULL DEFAULT 24,
  last_progress timestamptz,
  dead_epochs   integer NOT NULL DEFAULT 0,
  -- THE BOUNDARY EVENT (2026-08-22): when this goal shipped. Value enters the org economy
  -- at exactly this timestamp (W = Σ budgets of goals with done_at in the window) — set by
  -- the trigger below, never by hand, so the series cannot be backdated.
  done_at       timestamptz
);
CREATE OR REPLACE FUNCTION goals_done_stamp() RETURNS trigger AS $$
BEGIN
  IF NEW.state IN ('shipped','done') AND (OLD.state IS DISTINCT FROM NEW.state)
     AND NEW.done_at IS NULL THEN
    NEW.done_at := now();
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS goals_done_stamp ON goals;
CREATE TRIGGER goals_done_stamp BEFORE UPDATE ON goals
  FOR EACH ROW EXECUTE FUNCTION goals_done_stamp();

-- econ: the daily thermodynamic/economic rollup (one row per day, metrics jsonb).
-- Computed by nucleus/econ.py (the ONE implementation of the equations; the observatory
-- and the steward trigger both call it). Owner-approved table, 2026-08-22.
CREATE TABLE IF NOT EXISTS econ (
  day         date PRIMARY KEY,
  computed_at timestamptz NOT NULL DEFAULT now(),
  metrics     jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS peers (
  org        text PRIMARY KEY,               -- org name (domain when it has one)
  url        text,                           -- gateway base url; null = they poll us
  last_pickup bigint NOT NULL DEFAULT 0,     -- highest message id they collected
  pubkey     text,
  status     text NOT NULL DEFAULT 'stranger', -- stranger|introduced|trusted|revoked
  reputation real NOT NULL DEFAULT 0,
  caps_granted  jsonb NOT NULL DEFAULT '[]',
  caps_received jsonb NOT NULL DEFAULT '[]',
  notes      text
);

CREATE TABLE IF NOT EXISTS receipts (
  id         bigserial PRIMARY KEY,
  ts         timestamptz NOT NULL DEFAULT now(),
  from_party text NOT NULL,                  -- goal:<id> or org domain
  to_party   text NOT NULL,
  amount_tokens bigint NOT NULL DEFAULT 0,
  amount_money  numeric NOT NULL DEFAULT 0,
  memo       text,
  prev_hash  text NOT NULL,
  hash       text NOT NULL,                  -- sha256(prev_hash || canonical row)
  sig_a      text,
  sig_b      text
);

-- Doorbells. Payloads are tiny (ids); the table is the truth, consumers fetch + drain.
CREATE OR REPLACE FUNCTION notify_message() RETURNS trigger AS $$
BEGIN
  IF NEW.to_org = 'local' THEN
    PERFORM pg_notify('astryx_msg_' || NEW.to_agent, NEW.id::text);
  ELSE
    PERFORM pg_notify('astryx_outbound', NEW.id::text);
  END IF;
  PERFORM pg_notify('astryx_wire', NEW.id::text);  -- global doorbell (observatory)
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS messages_notify ON messages;
CREATE TRIGGER messages_notify AFTER INSERT ON messages
  FOR EACH ROW EXECUTE FUNCTION notify_message();

CREATE OR REPLACE FUNCTION notify_step() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('astryx_steps',
    json_build_object('id', NEW.id, 'agent', NEW.agent, 'kind', NEW.kind)::text);
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS steps_notify ON steps;
CREATE TRIGGER steps_notify AFTER INSERT ON steps
  FOR EACH ROW EXECUTE FUNCTION notify_step();

-- DAG traces (mcp/compose runner writes these; doorbell 'astryx_dag' for the observatory)
CREATE TABLE IF NOT EXISTS dag_runs (
  run_id   bigserial PRIMARY KEY,
  dag      text NOT NULL,
  args     jsonb,
  status   text NOT NULL DEFAULT 'running',   -- running | ok | error
  started  timestamptz NOT NULL DEFAULT now(),
  finished timestamptz,
  result   jsonb
);
CREATE TABLE IF NOT EXISTS dag_steps (
  id       bigserial PRIMARY KEY,
  run_id   bigint REFERENCES dag_runs(run_id),
  node     text NOT NULL,
  tool     text NOT NULL,
  status   text NOT NULL DEFAULT 'running',
  started  timestamptz NOT NULL DEFAULT now(),
  finished timestamptz,
  output   jsonb,
  error    text
);
CREATE INDEX IF NOT EXISTS dag_steps_run ON dag_steps (run_id);

-- Triggers: agents author their own wake-ups. The pulse daemon evaluates each
-- schedule and, when a check fires, INSERTs an ordinary wire message to the
-- owning agent. kind: heartbeat (always fires) | sql (fires when the query's
-- result is non-empty AND different from last fire) | python (check(ctx) in
-- triggers/<agent>/<name>.py returns None or the message body).
CREATE TABLE IF NOT EXISTS triggers (
  id         bigserial PRIMARY KEY,
  agent      text NOT NULL,
  name       text NOT NULL,
  schedule   text NOT NULL,               -- cron expression: when to evaluate
  kind       text NOT NULL DEFAULT 'heartbeat',
  check_src  text,                        -- SQL text, or python file path
  state      jsonb NOT NULL DEFAULT '{}',
  enabled    boolean NOT NULL DEFAULT true,
  last_eval  timestamptz,
  last_fired timestamptz,
  next_fire  timestamptz NOT NULL DEFAULT now(),
  note       text,
  -- THE INSURANCE PREMIUM (2026-08-22): tokens/30d someone is willing to pay for this
  -- trigger to exist regardless of its ROI. A guard's value is disasters that did not
  -- happen — structurally invisible to goal attribution — so guards survive by being
  -- FUNDED (steward prices, owner's treasury pays), never by a category exemption.
  -- premium=0 + persistent negative ROI = the market retires the trigger (market_decay).
  premium    bigint NOT NULL DEFAULT 0,
  UNIQUE (agent, name)
);
CREATE INDEX IF NOT EXISTS triggers_due ON triggers (next_fire) WHERE enabled;

-- polls: every WhatsApp poll seen on a routed surface — agent-embedded
-- ([[poll: q | a | b | multi=N]] in any outbound body), CLI-sent, or
-- human-posted. votes refreshes from wacli on every vote event, so the row is
-- always the poll's current truth; agent is the asker (NULL = external).
CREATE TABLE IF NOT EXISTS polls (
  msg_id     text PRIMARY KEY,
  chat       text NOT NULL,
  agent      text,
  question   text NOT NULL,
  options    jsonb NOT NULL DEFAULT '[]',
  multi      int NOT NULL DEFAULT 1,
  votes      jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- signals: the TIER-CROSSING DOORBELL (plan-16 / goal 16). An OPAQUE HANDLE
-- REGISTRY, never a queue. A private-tier event (e.g. canopus's recruiter mail,
-- resolved via its own gmail grant) must wake an agent through the OBSERVABLE
-- substrate where SQL triggers live — WITHOUT the event's semantics landing
-- anywhere the wire or RAG can read. So a row carries a wake + an opaque
-- reference, NOTHING the referent means:
--   priority = coarse wake-urgency ordinal ONLY (1=urgent/act-now, 2=routine).
--     NOT a classification/kind/stage code — CHECK bounds it; a multi-source
--     consumer folds its discriminator into its OWN private state, never here.
--   ref      = opaque bigint in the CONSUMER'S private namespace (a bare int,
--     meaningless to any reader but the holder; best-effort deref token, MAY rot
--     — signals is a LATENCY primitive, never a correctness one; the consumer
--     keeps an out-of-band backstop, e.g. canopus's daily gmail sweep).
-- INVARIANT (schema-enforced, guarded by triggers/canopus/signals_schema_guard.py):
--   ZERO text/jsonb/varchar semantic columns, EVER. The instant a text/enum
--   column is added to disambiguate, the handle registry has become a shared
--   semantic QUEUE — a peer could then read WHICH private category fired.
-- EXPOSURE (named honestly, not hidden): reachable by NO public/RAG endpoint
--   (not in observatory PUBLIC_PATHS; only the owner-gated db workbench reads
--   arbitrary tables) — but a same-uid peer CAN SELECT it, so existence/timing/
--   rate/priority leak by traffic analysis. Tolerable ONLY for a consumer whose
--   wake-signal is tier-ADJACENT, never tier-IDENTICAL (a geofence timestamp IS
--   location history → MUST NOT use this; it must poll within its own grant or
--   wait for uid-isolation, goal #4). Each consumer classifies its own wake-
--   signal sensitivity BEFORE adopting.
CREATE TABLE IF NOT EXISTS signals (
  id         bigserial PRIMARY KEY,
  agent      text        NOT NULL,
  priority   smallint    NOT NULL CHECK (priority BETWEEN 1 AND 2),
  ref        bigint,                                   -- opaque, consumer-private, nullable
  created_at timestamptz NOT NULL DEFAULT now(),
  handled_at timestamptz                               -- consumer stamps when drained
);
-- the wake query: unhandled rows for an agent at a given urgency
CREATE INDEX IF NOT EXISTS signals_wake ON signals (agent, priority, handled_at);

-- ── the social graph (owner ruling 2026-08-14: "postgres for everything") ──────────
-- The network's people, FB-shaped: we record THAT two people are related, never what
-- the relation is (married/cousins is deliberately not representable here — that
-- judgement lives in the owner's curated instruments, and the network layer is
-- structure only). One row per person PER ORG: `org` is the provenance column, so a
-- federation peer's people can replicate in and render locally without a schema
-- change — new joiners copy structure, exactly like the wire copies messages.
-- Identity is a SALTED HASH of the channel id (nucleus/people.py) — no raw JID or
-- number is ever a key here, and `label` is display-masked at write time. The rows
-- are DERIVED (rebuilt from the channels nightly), so the table is disposable per
-- org: DELETE WHERE org='<self>' + rescan is a full recovery.
CREATE TABLE IF NOT EXISTS social_person (
  org        text NOT NULL,                       -- which org observed this person
  id         text NOT NULL,                       -- salted-hash pid (p…) or group gid (g…)
  kind       text NOT NULL DEFAULT 'person'
             CHECK (kind IN ('person','group')),  -- groups are contexts, not people
  label      text NOT NULL DEFAULT 'unknown',     -- masked display name; NEVER a number
  direct     boolean NOT NULL DEFAULT false,      -- has a DM with the org's owner
  relation   text,                                -- model-derived class (close-friend…)
  who        text,                                -- one derived sentence; never a quote
  shape      text,                                -- behavioural summary (persona.py)
  confidence text,
  seen_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org, id)
);
-- Edges: "related at all" — co-membership or a direct thread. Weight = evidence
-- count (shared groups), so a rendering can threshold without the storage lying.
CREATE TABLE IF NOT EXISTS social_edge (
  org    text NOT NULL,
  src    text NOT NULL,
  dst    text NOT NULL,
  rel    text NOT NULL DEFAULT 'member-of',
  weight int  NOT NULL DEFAULT 1,
  PRIMARY KEY (org, src, dst, rel)
);
CREATE INDEX IF NOT EXISTS social_edge_src ON social_edge (org, src);
