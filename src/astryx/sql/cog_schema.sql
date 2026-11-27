-- plan-11859 U1U2 (D7, D9): the COG's user store. One per cog, in its own database (the registry's `cog` block names
-- the HOME whose .env holds its ASTRYX_DSN), never in an org's: the front is the authority for WHO you are, and each
-- org's own `members` table (schema.sql) is the authority for what you may do there (a2 I1). Idempotent.

-- an account. email is the sign-in name, stored lowercased; pw is an argon2id PHC string (src/astryx/cogauth.py),
-- never a password. A row is written by the host CLI (src/astryx/cogauth.py, D7), by the front when a person opens an
-- org owner's or admin's one-time invite (`links` below), or by the front's public sign-up, which exists only while
-- the cog .env's ASTRYX_COG_SIGNUP is on (default off) and makes an account plus a PENDING `org_requests` row
CREATE TABLE IF NOT EXISTS users (
  id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email    text NOT NULL UNIQUE CHECK (email = lower(email) AND email <> ''),
  pw       text NOT NULL,
  created  timestamptz NOT NULL DEFAULT now()
);

-- a session is a SERVER row, so signing out (or a password reset) revokes it for real (D7). The cookie carries a
-- random token; only its sha256 is stored, so a read of this table can't sign anyone in
CREATE TABLE IF NOT EXISTS sessions (
  digest   bytea PRIMARY KEY,
  uid      bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  created  timestamptz NOT NULL DEFAULT now(),
  expires  timestamptz NOT NULL,
  revoked  timestamptz
);
CREATE INDEX IF NOT EXISTS sessions_uid ON sessions (uid);

-- cog-rebuild (the admin panel): a ONE-TIME LINK an org's owner or admin hands to a person, since this host has no mail.
-- kind 'invite' brings an account (new, or an existing one proving its password) into `org` with `role` on `node` (a
-- path in that org's agents/ tree, '' = the whole org); the grant is made AS by_uid, so the org's backend judges it at
-- use. kind 'reset' sets a new password for `uid` and revokes its sessions. Only the token's sha256 is stored; `used`
-- is set by the one conditional UPDATE that claims it, and a link past `expires` opens nothing. role/node are the
-- org's to judge (its members CHECK), never this store's: a role here is only what was offered.
CREATE TABLE IF NOT EXISTS links (
  id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  digest   bytea NOT NULL UNIQUE,
  kind     text NOT NULL CHECK (kind IN ('invite', 'reset')),
  org      text NOT NULL,
  role     text,
  node     text NOT NULL DEFAULT '',
  uid      bigint REFERENCES users (id) ON DELETE CASCADE,
  by_uid   bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  created  timestamptz NOT NULL DEFAULT now(),
  expires  timestamptz NOT NULL,
  used     timestamptz,
  CONSTRAINT links_kind_shape CHECK ((kind = 'invite' AND role IS NOT NULL AND uid IS NULL)
                                     OR (kind = 'reset' AND uid IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS links_org_open ON links (org) WHERE used IS NULL;

-- cog-rebuild Phase 3 (public sign-up, owner 11-13): a person may ask for an org of their OWN. The ask is a ROW here,
-- never an org: no database, role, HOME, registry entry or agent exists until a COG ADMIN approves it with a token
-- budget (a self-serve org's agents would otherwise run on, and spend, the host owner's login). The front writes a
-- `pending` row at sign-up (observatory/front.py /auth/signup, only while the cog .env's ASTRYX_COG_SIGNUP is on) and a
-- cog admin decides it (/auth/cog/requests). `key` is the org's registry name to be (orgs.NAME); one live claim per
-- key (pending or approved) and one pending ask per account are the DATABASE's rules (the partial unique indexes),
-- so two racing sign-ups can't both hold a name. `provision` is what became of src/astryx/cog_provision.py's
-- provision_org at approval: NULL not tried, 'deferred' (the provisioner is not built yet: feat/cog-rls2), 'done',
-- 'failed'; `provision_note` says why, never a secret.
CREATE TABLE IF NOT EXISTS org_requests (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  uid             bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  key             text NOT NULL CHECK (key ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
  name            text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
  state           text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'approved', 'rejected')),
  allowance_tokens bigint CHECK (allowance_tokens IS NULL OR allowance_tokens > 0),
  created         timestamptz NOT NULL DEFAULT now(),
  decided_by      bigint REFERENCES users (id) ON DELETE SET NULL,
  decided_at      timestamptz,
  note            text,
  provision       text CHECK (provision IN ('deferred', 'done', 'failed')),
  provision_note  text,
  CONSTRAINT org_requests_decided CHECK ((state = 'pending') = (decided_at IS NULL)),
  CONSTRAINT org_requests_budget CHECK (state <> 'approved' OR allowance_tokens IS NOT NULL)
);
-- the column was budget_tokens until 11-15: an org's token ALLOWANCE, renamed so it can't read as a goal's budget (the
-- economy's own column, schema.sql goals). Idempotent: a store made before then is renamed once
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'org_requests'
             AND column_name = 'budget_tokens') THEN
    ALTER TABLE org_requests RENAME COLUMN budget_tokens TO allowance_tokens;
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS org_requests_key_live ON org_requests (key) WHERE state IN ('pending', 'approved');
CREATE UNIQUE INDEX IF NOT EXISTS org_requests_one_pending ON org_requests (uid) WHERE state = 'pending';
CREATE INDEX IF NOT EXISTS org_requests_created ON org_requests (created);

-- the COG's own roles (not an org's: those are each org's `members`). One today: cog_admin, who decides org requests.
-- Written only by the host CLI (src/astryx/cogauth.py cog-admin EMAIL); the bootstrap is the primary org's owner.
CREATE TABLE IF NOT EXISTS cog_grants (
  uid      bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  role     text NOT NULL CHECK (role IN ('cog_admin')),
  granted  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (uid, role)
);

-- an EMAIL CODE (owner 11-15: "an email otp so people don't sign themselves up with wrong emails"): the proof that
-- whoever makes a NEW account reads that address. Six digits mailed by the front (src/astryx/mail.py, the cog .env's
-- MAIL_*); only their digest is kept, with an expiry and a count of tries; one live code per address, used once. A cog
-- with no mailbox asks for no code.
CREATE TABLE IF NOT EXISTS email_codes (
  email    text PRIMARY KEY CHECK (email = lower(email) AND email <> ''),
  digest   bytea NOT NULL,
  sent     timestamptz NOT NULL DEFAULT now(),
  expires  timestamptz NOT NULL,
  tries    int NOT NULL DEFAULT 0
);
