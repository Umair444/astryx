-- plan-11859 U1U2 (D7, D9): the COG's user store. One per cog, in its own database (the registry's `cog` block names
-- the HOME whose .env holds its ASTRYX_DSN), never in an org's: the front is the authority for WHO you are, and each
-- org's own `members` table (schema.sql) is the authority for what you may do there (a2 I1). Idempotent.

-- an account. email is the sign-in name, stored lowercased; pw is an argon2id PHC string (src/astryx/cogauth.py),
-- never a password. There is no public sign-up: a row is written by the host CLI (src/astryx/cogauth.py, D7), or by
-- the front when a person opens an org owner's or admin's one-time invite (`links` below)
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
