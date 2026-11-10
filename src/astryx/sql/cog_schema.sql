-- plan-11859 U1U2 (D7, D9): the COG's user store. One per cog, in its own database (the registry's `cog` block names
-- the HOME whose .env holds its ASTRYX_DSN), never in an org's: the front is the authority for WHO you are, and each
-- org's own `members` table (schema.sql) is the authority for what you may do there (a2 I1). Idempotent.

-- an account. email is the sign-in name, stored lowercased; pw is an argon2id PHC string (src/astryx/cogauth.py),
-- never a password. There is no public sign-up: a row is written by the host CLI only (src/astryx/cogauth.py, D7)
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
