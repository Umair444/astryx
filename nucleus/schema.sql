-- ASTRYX schema v0 — the wire's truth. Six tables, no more until pain demands them.
-- OPTIONAL EXTENSIONS, activated when the server image carries them (stock postgres:17
-- does not; pgvector/postgis/apache-age images do). Absence is fine — nothing in the core
-- schema depends on them; they are the substrate for the memory RAG / geo / graph organs.
DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS vector;  EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'pgvector unavailable (ok)'; END $$;
DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS postgis; EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'postgis unavailable (ok)'; END $$;
DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS age;     EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'age unavailable (ok)'; END $$;

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
  -- (a VIRTUAL generated `messages` column lived here briefly — PG18-only syntax that
  --  broke every fresh PG17 install, caught by an outside reader. raw_payload->'messages'
  --  and turns_v serve every consumer; STORED generated columns below are PG12+.)
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
-- DROP-then-CREATE, never OR REPLACE: the view snapshots t.* at creation, so any new
-- turns column makes OR REPLACE fail with "cannot change name of view column".
-- (Also migrate away the short-lived PG18-only VIRTUAL `messages` column, view first —
--  the view depends on it.)
DROP VIEW IF EXISTS turns_v;
ALTER TABLE turns DROP COLUMN IF EXISTS messages;
CREATE VIEW turns_v AS
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

-- >>> usage-authority (goal #3833) ─────────────────────────────────────────────────────
-- ONE FETCH, ONE EXTRACT, ONE SERVE for the account-usage gauge. Before this, five readers
-- each hand-copied `turns WHERE usage_state='fresh' ORDER BY ended_at DESC LIMIT 1` — the
-- same fact re-derived five ways (drift class). And the gauge went STALE when the org was
-- idle: the Stop hook writes a snapshot per TURN (activity-driven), so a quiet stretch left
-- every reader on a stale number. This unifies the readers behind one authority and adds a
-- second WRITER (triggers/seed/usage_poll.py, an idle-fallback poll) under the same freshness
-- floor — activity drives cadence when active, the poll fills idle gaps only.
--
-- usage_polls: the idle-fallback poll's own history. Written ONLY via usage_refresh.snapshot()
-- (the single credential reader + fail-closed allowlist — dollars/spend stripped upstream);
-- this table is wire-readable, so a raw API body must never land here. Every attempt is
-- recorded (fresh OR error) for observability; the authority GOOD-filters below.
CREATE TABLE IF NOT EXISTS usage_polls (
  id         bigserial   PRIMARY KEY,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  state      text,                             -- fresh | auth_rejected | unavailable
  snapshot   jsonb       NOT NULL              -- verbatim snapshot() output (allowlisted)
);
CREATE INDEX IF NOT EXISTS usage_polls_fetched ON usage_polls (fetched_at DESC);

-- usage_readings: the ONE EXTRACT. Every account-usage attempt from BOTH writers — turns
-- (activity-driven) ∪ usage_polls (idle-fallback) — projected identically FROM THE snapshot
-- jsonb (turns' own generated usage_* columns go vestigial for these readers; the extraction
-- now lives here, in one place, so the two arms can never drift). state carries fresh/error;
-- fetched_at is the snapshot's own measurement time, uniform across arms.
DROP VIEW IF EXISTS current_usage;
DROP VIEW IF EXISTS usage_readings;
CREATE VIEW usage_readings AS
  SELECT (usage_snapshot ->> 'fetched_at')::timestamptz         AS fetched_at,
         'turns'::text                                          AS src,
         agent                                                  AS measured_by,
         usage_snapshot ->> 'state'                             AS state,
         usage_snapshot ->> 'subscription'                      AS subscription,
         (usage_snapshot #>> '{data,five_hour_utilization}')::numeric      AS five_hour_pct,
         (usage_snapshot #>> '{data,seven_day_utilization}')::numeric      AS seven_day_pct,
         (usage_snapshot #>> '{data,seven_day_opus_utilization}')::numeric AS seven_day_opus_pct,
         usage_snapshot #>> '{data,five_hour_resets_at}'        AS five_hour_reset,
         usage_snapshot #>> '{data,seven_day_resets_at}'        AS seven_day_reset,
         usage_snapshot                                         AS snapshot
    FROM turns WHERE usage_snapshot IS NOT NULL
  UNION ALL
  SELECT (snapshot ->> 'fetched_at')::timestamptz,
         'polls'::text,
         'usage-poll'::text,
         snapshot ->> 'state',
         snapshot ->> 'subscription',
         (snapshot #>> '{data,five_hour_utilization}')::numeric,
         (snapshot #>> '{data,seven_day_utilization}')::numeric,
         (snapshot #>> '{data,seven_day_opus_utilization}')::numeric,
         snapshot #>> '{data,five_hour_resets_at}',
         snapshot #>> '{data,seven_day_resets_at}',
         snapshot
    FROM usage_polls;

-- current_usage: the ONE SERVE. The newest GOOD (state='fresh') reading across both arms,
-- plus its age — so an error/None attempt can NEVER advance the clock (fail-toward-fetch:
-- the poll gate reads age_seconds; a stale/absent authority → it fetches) and readers render
-- honest staleness ("updated Xh ago") instead of a fake-fresh number. Empty ⇒ no reader ever
-- shows a stale value as current; they get null. Deterministic tiebreak (src DESC) keeps the
-- view a function on equal timestamps.
CREATE VIEW current_usage AS
  SELECT *, EXTRACT(EPOCH FROM (now() - fetched_at))::numeric AS age_seconds
    FROM usage_readings
   WHERE state = 'fresh'
   ORDER BY fetched_at DESC, src DESC
   LIMIT 1;
-- <<< usage-authority ────────────────────────────────────────────────────────────────────

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
  -- at exactly this timestamp (W = Σ budgets of goals with done_at in the window). The
  -- trigger below auto-stamps it on the shipped/done transition — but this is ATTRIBUTION-
  -- GRADE, NOT tamper-proof: a direct `UPDATE goals SET done_at=now()` or any genesis-
  -- superuser write forges it, untouched by the trigger. Prevention needs the NOSUPERUSER
  -- write perimeter (deferred); see goal 3499. funded_by (below) NAMES the mint's funder.
  done_at       timestamptz
);
-- 3499 economy-integrity (ATTRIBUTION, not prevention): funded_by NAMES the funder that
-- authorized this goal's budget. Attribution-grade — a genesis superuser sets it to anything;
-- it records and labels the funding boundary, it does not enforce it (prevention = the
-- deferred NOSUPERUSER perimeter). NULL below the migration watermark = LEGACY (pre-feature,
-- honestly unknown); NULL above it = a new goal not yet attributed; '(unfunded)' = shipped
-- with no funder (named at W-birth by the trigger); '<agent>' = an attributed funder.
ALTER TABLE goals ADD COLUMN IF NOT EXISTS funded_by text;
-- the legacy watermark: the highest goal id that existed when funded_by was introduced.
-- Captured ONCE (the WHERE-NOT-EXISTS guard) so re-running schema.sql never moves it; on a
-- fresh clone (empty goals) it is 0 and nothing is legacy.
-- single-row table: the singleton PRIMARY KEY makes a second watermark row structurally
-- impossible, so a schema.sql re-run (or any stray insert) can never move or duplicate it —
-- an aggregate SELECT always returns a row, so a WHERE/NOT-EXISTS guard would NOT stop it.
CREATE TABLE IF NOT EXISTS funded_by_watermark (
  singleton     boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  legacy_max_id bigint NOT NULL
);
INSERT INTO funded_by_watermark (legacy_max_id)
  SELECT COALESCE(max(id), 0) FROM goals
  ON CONFLICT (singleton) DO NOTHING;
CREATE OR REPLACE FUNCTION goals_done_stamp() RETURNS trigger AS $$
BEGIN
  IF NEW.state IN ('shipped','done') AND (OLD.state IS DISTINCT FROM NEW.state) THEN
    -- W-birth: stamp the boundary (UNCHANGED — this is the mint moment, and it runs FIRST so
    -- the funder-naming below can never interfere with it).
    IF NEW.done_at IS NULL THEN
      NEW.done_at := now();
    END IF;
    -- (goal 4227 S3: the 3499 funder-NAMING that followed here — funded_by := '(unfunded)' for
    -- a new goal closed with no funder — is RETIRED with budgets. funded_by is frozen below;
    -- the rows it already named keep their names as v1 history.)
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS goals_done_stamp ON goals;
CREATE TRIGGER goals_done_stamp BEFORE UPDATE ON goals
  FOR EACH ROW EXECUTE FUNCTION goals_done_stamp();

-- goal 4227 S3 (owner law 2026-09-29: NO budgets, ever): the budget columns are DEPRECATED and
-- READ-ONLY — kept, never dropped, because v1's frozen econ rows and the goals that carry a
-- budget or a funder are history. An insert may not set them; an update may not change them.
-- triggers.premium is NOT covered: it is the survival flag pulse.shed reads, not a budget.
-- AN AFTER TRIGGER, deliberately (a2 #23159): BEFORE ROW triggers fire in NAME order and a later
-- one's NEW is never re-checked, so a BEFORE freeze is a gate any later-sorting BEFORE trigger
-- (goals_done_stamp is that shape) writes through. AFTER sees the final row; the RAISE rolls the
-- statement back.
-- GRADE: ACCIDENT-PROOF, NOT ACTOR-PROOF. It stops the honest writer who did not know. Every
-- agent's psql connects as the superuser that owns goals, so ALTER TABLE ... DISABLE TRIGGER or
-- session_replication_role=replica bypasses it and nothing records that — not even detection
-- against a same-uid actor.
CREATE OR REPLACE FUNCTION goals_budget_frozen() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.budget_tokens <> 0 OR NEW.spent_tokens <> 0 OR NEW.funded_by IS NOT NULL THEN
      RAISE EXCEPTION 'goals budget columns are read-only since goal 4227 (no budgets): '
        'budget_tokens=%, spent_tokens=%, funded_by=% on insert', NEW.budget_tokens,
        NEW.spent_tokens, NEW.funded_by;
    END IF;
  ELSIF NEW.budget_tokens IS DISTINCT FROM OLD.budget_tokens
     OR NEW.spent_tokens IS DISTINCT FROM OLD.spent_tokens
     OR NEW.funded_by IS DISTINCT FROM OLD.funded_by THEN
    RAISE EXCEPTION 'goals budget columns are read-only since goal 4227 (no budgets): '
      'goal % may not change budget_tokens/spent_tokens/funded_by', OLD.id;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS goals_budget_frozen ON goals;
CREATE TRIGGER goals_budget_frozen AFTER INSERT OR UPDATE ON goals
  FOR EACH ROW EXECUTE FUNCTION goals_budget_frozen();
COMMENT ON COLUMN goals.budget_tokens IS 'DEPRECATED read-only (goal 4227 S3): v1 price, history only';
COMMENT ON COLUMN goals.spent_tokens IS 'DEPRECATED read-only (goal 4227 S3): never written';
COMMENT ON COLUMN goals.funded_by IS 'DEPRECATED read-only (goal 4227 S3): v1 mint funder, history only';

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
  -- Since goal 4227 (2026-09-29, no trigger killing) nothing retires on ROI: market_decay
  -- REPORTS premium=0 + negative ROI as rent, and premium is the SURVIVAL FLAG pulse.shed
  -- reads under quota scarcity. Not a budget: excluded from the S3 budget deprecation.
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
-- The DETAILS of a relation (people library, seed #35894): what it IS, who the person is to the owner, the
-- behavioural evidence, how sure we are. NOT network layer: readable only by people_cleared (nucleus/people_gate.py,
-- which holds the grants and states the grade: ACCIDENT-GRADE while residents can read the superuser credential).
-- Moved out of social_person's relation/who/shape/confidence (kind/context/evidence/confidence) by
-- nucleus/people_move.py. Not rebuilt nightly: social_person's DELETE+INSERT never touches it.
CREATE TABLE IF NOT EXISTS social_relation (
  org        text NOT NULL,
  pid        text NOT NULL,                       -- social_person.id
  kind       text,                                -- model-derived class (close-friend…), was social_person.relation
  closeness  text,                                -- no writer yet
  context    text,                                -- one derived sentence, was social_person.who; never a quote
  confidence text,
  evidence   text,                                -- behavioural summary (persona.py), was social_person.shape
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org, pid)
);
REVOKE ALL ON social_relation FROM PUBLIC;
-- memory's people essences (a2 #38791 B2: the content lives behind the people gate, not in files).
-- memory/essence.py is the only writer; all three are DERIVED, never a quote.
ALTER TABLE social_relation
  ADD COLUMN IF NOT EXISTS essence   text,          -- ≤60 words: who this person is to the owner
  ADD COLUMN IF NOT EXISTS now_state text,          -- ≤30 words: the latest state + open loops, with direction
  ADD COLUMN IF NOT EXISTS through   timestamptz;   -- the last WhatsApp message folded in (the delta watermark)

-- CLASSIFICATIONS (goal 4227, S4): one LABEL per prompt from the pluggable classifier, which
-- the nudge hook (hooks/nudge.py) reads for RECURRENCE of a task family. It holds labels ONLY.
-- There is no column for prompt text, and the CHECKs refuse a label shaped like one: the
-- classifier is an external service whose output is untrusted, and one that echoed the prompt
-- back as its "family" would otherwise persist it (I5). turn_id is claimed at Stop by
-- hooks/step.py, the same way steps are. No metric reads this table (the nudge takes no metric
-- input, and no economy number is computed from a label).
CREATE TABLE IF NOT EXISTS classifications (
  id          bigserial PRIMARY KEY,
  ts          timestamptz NOT NULL DEFAULT now(),
  agent       text NOT NULL,
  session_id  text,
  turn_id     bigint REFERENCES turns(id) ON DELETE SET NULL,
  family      text NOT NULL CHECK (family ~ '^[a-z0-9][a-z0-9_.-]{0,47}$'),
  tier        text NOT NULL CHECK (tier IN ('trivial','simple','complex')),
  classifier  text CHECK (classifier IS NULL OR classifier ~ '^[A-Za-z0-9_.:/@+-]{1,64}$'),
  nudged      boolean NOT NULL DEFAULT false   -- this label produced a nudge (the cooldown's record)
);
ALTER TABLE classifications ADD COLUMN IF NOT EXISTS nudged boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS classifications_recur ON classifications (agent, family, ts DESC);

-- SQLGUARD STATE (goal 4243): what the meta-guard has to remember ACROSS runs, as a row (org law), not a file.
-- kind 'ns_site' = a site NOT SEARCHED since first_seen (the per-site clock); 'fx_db' = a foreign astryx_fx_*
-- database seen by the leak arm. Postgres records no creation time for a database, so first-seen IS the clock.
-- Losing this table only DELAYS a RED (the clock restarts); it never silences one.
CREATE TABLE IF NOT EXISTS sqlguard_seen (
  kind        text NOT NULL,
  key         text NOT NULL,
  first_seen  timestamptz NOT NULL DEFAULT now(),
  last_seen   timestamptz NOT NULL DEFAULT now(),
  runs        int NOT NULL DEFAULT 1,
  PRIMARY KEY (kind, key)
);

-- held_wakes (goal 4227 S1c): wakes a trigger raised while the 5h quota was >=85% and the trigger
-- carries no survival flag (premium=0). The pulse is the ONLY writer of trigger wakes: checks call
-- ctx.say(), the pulse delivers after evaluation or holds here, and releases on the first tick the
-- gauge reads <85% (or is missing: unknown pressure delivers). A held wake is PERSISTED, never
-- rewound: the check's state commits as usual, so nothing re-detects and nothing floods.
-- APPEND by default (distinct news is never merged away); a byte-identical body under the same key
-- only bumps n; supersede=true is opt-in, per insert site, for report-style wakes whose later body
-- contains the earlier one. Past K per key the oldest are marked elided (kept, readable, pruned 7d
-- after their marker is released) and released as one visible marker, never silently dropped.
CREATE TABLE IF NOT EXISTS held_wakes (
  id          bigserial   PRIMARY KEY,
  agent       text        NOT NULL,              -- the trigger's owner
  trigger     text        NOT NULL,              -- the trigger's name
  from_agent  text        NOT NULL,
  from_org    text        NOT NULL DEFAULT 'local',
  to_agent    text        NOT NULL,
  to_org      text        NOT NULL DEFAULT 'local',
  thread      text,
  intent      text        NOT NULL DEFAULT 'trigger',
  body        text        NOT NULL,
  supersede   boolean     NOT NULL DEFAULT false,
  n           integer     NOT NULL DEFAULT 1,    -- times this exact wake was raised while held
  raised_at   timestamptz NOT NULL DEFAULT now(),
  elided      boolean     NOT NULL DEFAULT false,
  released_at timestamptz                        -- set on elided rows when their marker is delivered
);
CREATE INDEX IF NOT EXISTS held_wakes_key
  ON held_wakes (agent, trigger, to_agent, coalesce(thread, ''));

-- wire_emitted (goal 4227 S1c, C1.5): "has this been EMITTED?" — messages plus held wakes, elided
-- rows included (they were emitted and are retrievable). A check asking whether it or anyone already
-- announced something reads this; a check asking whether a wake was DELIVERED or ACTED ON reads
-- messages, so a held nudge never reads as delivered-and-ignored.
DROP VIEW IF EXISTS wire_emitted;
CREATE VIEW wire_emitted AS
  SELECT from_agent, from_org, to_agent, to_org, thread, intent, body, ts, 'messages'::text AS src
    FROM messages
  UNION ALL
  SELECT from_agent, from_org, to_agent, to_org, thread, intent, body, raised_at, 'held'::text
    FROM held_wakes;

-- ── CANVAS (owner-directed 2026-10-09): the front door — chat with agents + live agent-authored
-- canvases. bridges/canvas.py is the surface; nucleus/canvas.py is the agents' write path.
-- Threads 'cv:<id>' are canvas conversations; a canvas's own thread is 'cv:canvas-<id>'.
-- Identities: the owner logs in with OBS_KEY and speaks as 'owner'; an invitee is 'cv-<name>'
-- (untrusted, reaches only the agents the owner granted); anything originating INSIDE a canvas
-- iframe is 'canvas-<id>' from_org 'canvas' — never the viewer (a1 #35009, confused deputy).
CREATE TABLE IF NOT EXISTS canvas_users (
  name        text PRIMARY KEY,                 -- wire identity is cv-<name>; 'owner' is the owner
  token_hash  text UNIQUE,                      -- sha256 of the invite token; NULL for owner
  agents      text[] NOT NULL DEFAULT '{}',     -- agents this invitee may talk to (owner grant)
  created_at  timestamptz NOT NULL DEFAULT now(),
  last_seen   timestamptz,
  revoked     boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS canvas_sessions (
  token_hash  text PRIMARY KEY,                 -- sha256 of the HttpOnly cookie value
  user_name   text NOT NULL,                    -- 'owner' or a canvas_users.name
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL DEFAULT now() + interval '30 days'
);
CREATE TABLE IF NOT EXISTS canvas_threads (
  thread      text PRIMARY KEY,                 -- 'cv:<id>' (or a foreign thread an agent opened to a canvas user)
  user_name   text NOT NULL,
  agent       text NOT NULL,
  title       text,
  canvas_id   bigint,                           -- set when this is a canvas's own thread
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  archived    boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS canvas_threads_user ON canvas_threads (user_name, updated_at DESC);
CREATE TABLE IF NOT EXISTS canvases (
  id          bigserial PRIMARY KEY,
  title       text NOT NULL,
  agent       text NOT NULL,                    -- the canvas's author/keeper (publishes, answers ask())
  user_name   text NOT NULL DEFAULT 'owner',    -- whose canvas it is
  tier        text NOT NULL DEFAULT 'org',      -- org | personal (personal is never shareable)
  shared_with text[] NOT NULL DEFAULT '{}',     -- invitees who may view it (owner act; never for personal)
  version     integer NOT NULL DEFAULT 0,       -- 0 = not yet painted
  brief       text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  archived    boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS canvas_versions (     -- immutable; publish = a new row, rollback = re-publish an old one
  canvas_id   bigint NOT NULL REFERENCES canvases(id),
  version     integer NOT NULL,
  html        text NOT NULL,                    -- BODY html only; the bridge owns the shell (CSP, shim)
  author      text NOT NULL,
  note        text,
  ts          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (canvas_id, version)
);
CREATE TABLE IF NOT EXISTS canvas_data (         -- live documents a canvas renders from
  canvas_id   bigint NOT NULL REFERENCES canvases(id),
  key         text NOT NULL,
  value       jsonb NOT NULL,
  updated_by  text NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (canvas_id, key)
);
-- Doorbell: ids only (NOTIFY caps at 8000 bytes); consumers fetch the row. Namespaced channel.
CREATE OR REPLACE FUNCTION notify_canvas() RETURNS trigger AS $$
BEGIN
  IF TG_TABLE_NAME = 'canvas_data' THEN
    PERFORM pg_notify('astryx_canvas', json_build_object('kind','data','canvas',NEW.canvas_id,'key',NEW.key)::text);
  ELSE
    PERFORM pg_notify('astryx_canvas', json_build_object('kind','canvas','canvas',NEW.id,'ver',NEW.version)::text);
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS canvases_notify ON canvases;
CREATE TRIGGER canvases_notify AFTER INSERT OR UPDATE ON canvases
  FOR EACH ROW EXECUTE FUNCTION notify_canvas();
DROP TRIGGER IF EXISTS canvas_data_notify ON canvas_data;
CREATE TRIGGER canvas_data_notify AFTER INSERT OR UPDATE ON canvas_data
  FOR EACH ROW EXECUTE FUNCTION notify_canvas();

-- ── CANVAS VOICE (owner-directed 2026-10-09): the always-ready realtime voice runs on OpenAI
-- gpt-realtime — EXTERNAL spend the owner signed for, capped per day (CANVAS_VOICE_DAILY_MINUTES).
-- One row per minted ephemeral session; the client reports cumulative connected seconds. An
-- unreported session is billed a floor minute by bridges/canvas_voice.py.
CREATE TABLE IF NOT EXISTS canvas_voice_usage (
  id          bigserial PRIMARY KEY,
  user_name   text NOT NULL,                    -- 'owner' or a canvas_users.name
  model       text NOT NULL,
  minted_at   timestamptz NOT NULL DEFAULT now(),
  seconds     integer NOT NULL DEFAULT 0,       -- client-reported, monotonic (greatest)
  reported    boolean NOT NULL DEFAULT false,
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS canvas_voice_usage_day ON canvas_voice_usage (minted_at);

-- ── PRESENCE (2026-10-09): where each agent's attention IS, right now. One row per agent, so it is
-- a state, not a log (steps is the log). General on purpose: `surface` names any place the org can
-- show an agent — canvas:<id>, thread:<thread>, goal:<id> — and `target` is that surface's own
-- locator (a canvas: a CSS selector). CANVAS renders it as agents moving over the page they work on;
-- any other surface may read it the same way. Writers: nucleus/presence.py (agents), the canvas
-- bridge (a summon), nucleus/canvas.publish (a finished stroke).
CREATE TABLE IF NOT EXISTS presence (
  agent      text PRIMARY KEY,
  surface    text,                                  -- NULL = idle
  target     text,
  say        text,                                  -- one short line beside the avatar
  state      text NOT NULL DEFAULT 'idle',          -- idle | moving | working | done
  updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE canvases ADD COLUMN IF NOT EXISTS crew text[] NOT NULL DEFAULT '{}';  -- agents summoned to work on it
CREATE OR REPLACE FUNCTION notify_presence() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('astryx_presence', json_build_object('agent', NEW.agent)::text);
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS presence_notify ON presence;
CREATE TRIGGER presence_notify AFTER INSERT OR UPDATE ON presence
  FOR EACH ROW EXECUTE FUNCTION notify_presence();

-- DM edges (2026-10-09, memory's people build 2): owner → person, rel='dm', weight = messages in the
-- direct chat; first/last message time and how many were the owner's own (mine) are the frequency and
-- recency evidence relation guesses need. These are PRIVATE, org-specific signals: a federation
-- projection carries nodes and "knows" edges only, never rel='dm'. scanned_at drives the incremental
-- nightly refresh (nucleus/people.py dm_refresh).
ALTER TABLE social_edge ADD COLUMN IF NOT EXISTS first_ts   timestamptz;
ALTER TABLE social_edge ADD COLUMN IF NOT EXISTS last_ts    timestamptz;
ALTER TABLE social_edge ADD COLUMN IF NOT EXISTS mine       int;
ALTER TABLE social_edge ADD COLUMN IF NOT EXISTS scanned_at timestamptz;

-- HANDS LEASES (plan-7862 S1). One row per browser lease; nucleus/hands.py is the ONLY writer.
-- The per-lease proxy's allow-list is GENERATED from `allow`, so the row is the authority on
-- what the lease's browser may reach. A lease dies at its STEP cap or its WALL-TIME cap,
-- whichever comes first (seed #38260), or when it's killed, and its end_reason says which.
CREATE TABLE IF NOT EXISTS hands_leases (
  id          bigserial PRIMARY KEY,
  created_at  timestamptz NOT NULL DEFAULT now(),
  agent       text NOT NULL,                     -- who asked for the lease
  allow       text[] NOT NULL,                   -- hosts the browser may reach (exact names)
  step_cap    int NOT NULL CHECK (step_cap BETWEEN 1 AND 1000),
  wall_cap_s  int NOT NULL CHECK (wall_cap_s BETWEEN 1 AND 86400),
  deadline    timestamptz NOT NULL,
  steps_used  int NOT NULL DEFAULT 0,
  state       text NOT NULL DEFAULT 'live' CHECK (state IN ('live','dead')),
  ended_at    timestamptz,
  end_reason  text CHECK (end_reason IS NULL OR end_reason IN ('killed','step_cap','wall_cap','error'))
);

-- LEASES (plan-8674 D4, hearing S1): ONE small lease seam. One row per RESOURCE ('ear:<room>' = one ear per
-- room); nucleus/ear_lease.py is the ONLY writer. Claim is an atomic UPDATE … WHERE state='free' RETURNING; the
-- indicator is DERIVED from the row and its heartbeat age (a past-TTL hold reads stale, never "listening").
-- MUTED is the only held state with no TTL: it ends only when the owner unmutes. No text ever lives here
-- (the transcript is `utterances`, below). Deliberately NOT hands_leases (owner, 2026-10-10).
CREATE TABLE IF NOT EXISTS leases (
  resource     text PRIMARY KEY,
  holder       text,                                  -- NULL iff free
  state        text NOT NULL DEFAULT 'free' CHECK (state IN ('free','EAR','MUTED','FOCAL','HELD')),
  granted_at   timestamptz,
  expires_at   timestamptz,                           -- the TTL; NULL for free and MUTED only
  heartbeat_at timestamptz,
  budget       jsonb,                                 -- S4's FOCAL cap rides here; NULL in S1
  CHECK ((state = 'free') = (holder IS NULL)),
  CHECK ((state IN ('EAR','FOCAL','HELD')) = (expires_at IS NOT NULL))
);
-- HELD (plan-8675 C4): a plain one-holder hold with a TTL, for resources that aren't a microphone: 'vm-slot'
-- (which VM may be resident in RAM: the Android emulator or the Windows VM, measured not to fit together) and
-- 'android:<avd>' (one agent drives a phone at a time). Widened in place on an existing table, idempotently:
-- the two checks are dropped by their generated names and re-added with HELD.
DO $$ BEGIN
  ALTER TABLE leases DROP CONSTRAINT IF EXISTS leases_state_check;
  ALTER TABLE leases ADD CONSTRAINT leases_state_check
    CHECK (state IN ('free','EAR','MUTED','FOCAL','HELD'));
  ALTER TABLE leases DROP CONSTRAINT IF EXISTS leases_check1;
  ALTER TABLE leases ADD CONSTRAINT leases_check1
    CHECK ((state IN ('EAR','FOCAL','HELD')) = (expires_at IS NOT NULL));
END $$;

-- UTTERANCES (plan-8674 S1, hearing): the raw room transcript, one row per VAD speech segment the ear transcribed.
-- In the ONE org database like every table (owner ruling 2026-10-10, seed #42311: information in astryx is shared
-- and usable by every agent). bridges/ear.py is the ONLY writer; it never puts a transcript on the WIRE
-- (messages) or in a log. Partitioned by UTC DAY: day partitions are created ahead and an expired day is DROPPED
-- whole by nucleus/ear_store.maintain (short TTL, EAR_TTL_DAYS, default 3), never DELETEd row by row. No DEFAULT
-- partition: a row with no day to land in is refused, and the writer makes the day and retries.
CREATE TABLE IF NOT EXISTS utterances (
  id      bigint GENERATED ALWAYS AS IDENTITY,
  ts      timestamptz NOT NULL DEFAULT now(),
  text    text NOT NULL,
  speaker text NOT NULL DEFAULT 'unknown',             -- ROUGH attribution, labelled as such; never authority
  view    text,                                        -- the observatory view the mic was on
  dur_ms  int,
  stt_ms  int,
  backend text,                                        -- which STT backend heard it (cpu/cuda faster-whisper, ...)
  PRIMARY KEY (ts, id)
) PARTITION BY RANGE (ts);

-- HEARINGS (plan-8674 S2, a4 #42048 D5): an agent's hear() caught its name in an utterance. This row is the POINTER
-- the agent is woken with, and it carries NO TEXT by design (no text column exists): the words stay in `utterances`,
-- reachable only through nucleus/ear_fetch.py as the addressed span (≤30 words from the name), fenced. When the
-- utterance's day partition drops, the pointer outlives it and a fetch says the hearing expired.
-- speaker_verified is TYPED provenance: nothing verifies a voice yet, so it is false and the CHECK keeps it false
-- until a verifier ships and changes the CHECK on purpose.
CREATE TABLE IF NOT EXISTS hearings (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts               timestamptz NOT NULL DEFAULT now(),
  agent            text NOT NULL,
  utterance_ts     timestamptz NOT NULL,
  utterance_id     bigint NOT NULL,
  matched_name     text NOT NULL,
  mode             text NOT NULL DEFAULT 'focus' CHECK (mode IN ('focus')),
  span_start       int NOT NULL CHECK (span_start >= 0),
  span_end         int NOT NULL CHECK (span_end > span_start AND span_end - span_start <= 30),
  speaker_verified boolean NOT NULL DEFAULT false CHECK (NOT speaker_verified),
  woke             boolean NOT NULL DEFAULT false,      -- false: over the agent's wake cap (counted, visible)
  msg_id           bigint,                              -- the wake's messages row
  fetched_at       timestamptz                          -- the last ear_fetch.py read (door 2 is counted, never silent)
);
CREATE INDEX IF NOT EXISTS hearings_agent_ts ON hearings (agent, ts DESC);
