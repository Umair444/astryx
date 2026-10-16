# Restoring the org from a backup

A backup is a set of three in `backups/`, sharing a timestamp: `astryx-<ts>.dump` (pg_dump custom format),
`astryx-<ts>.state.tgz` (the gitignored estate the dump can't carry: `triggers/`, `memory/`, `~/.pgpass`, … — see
`scripts/backup.sh`), and `astryx-<ts>.roles.sql` (the cluster's roles: `pg_dumpall --roles-only
--no-role-passwords`, names and attributes, no password material). This is
the path for an EMPTY server: a new disk, a lost data dir, a new host.

## Two seams: the role's password, and the roles themselves

The org's DSN carries no password; every client reads it from `~/.pgpass`. On an empty data dir, the image's initdb
creates `POSTGRES_USER` with `infra/pg/.env`'s `POSTGRES_PASSWORD`, which on an existing org is a deliberate
placeholder (a live value there would sit in `docker inspect genesis-pg`; #5497). So after a restore, the server holds
the placeholder and the restored `~/.pgpass` holds the real value, and every login fails until step 4 reconciles them.

The second seam: a per-database dump carries the GRANTs but not the ROLES they name. On an empty data dir only the
bootstrap role exists, so without the roles file `astryx_resident` and `people_cleared` (the groups the privilege
census and the people gate rest on) are absent, and pg_restore drops every grant to them with `role ... does not
exist`, while the rows still come back. Step 5 restores them first.

## Steps, in order

1. **The server.** Point `ASTRYX_PG_DATA` in `infra/pg/.env` at an empty directory and start the declared server:
   `docker compose -f infra/pg/docker-compose.yml up -d` (the image must be the one `infra/pg` declares;
   `venv/bin/python -m astryx.pg.pg_design` checks it).
2. **The estate.** Unpack the paired `.state.tgz`: its repo paths into the repo, its `$HOME`-relative members
   (`.pgpass`, `.claude/projects/*/memory`) into `$HOME`; `bash scripts/backup.sh --list-state` names which is which.
   Keep `~/.pgpass` at mode 0600 (libpq ignores a looser one).
3. **Prove the seam is there:** `venv/bin/python -m astryx.security.pg_role_sync check` fails with "the server's verifier and
   the pgpass value disagree". (If it passes, the data dir wasn't empty; stop and look.)
4. **The roles.** Apply the paired roles file, minus the bootstrap role's own CREATE (initdb already made it):
   `grep -v '^CREATE ROLE genesis;$' backups/astryx-<ts>.roles.sql | docker exec -i genesis-pg psql -X -U genesis -d postgres`.
   Every role the file names must then be in `pg_roles`. Roles go in BEFORE the reconcile, so step 5 is the last
   writer of the role's password. A roles file made by hand at disaster time must use `--no-role-passwords`:
   pg_dumpall's default carries the SCRAM verifiers, and `grep -E "PASSWORD '|SCRAM-SHA-256"` on it must find
   nothing before you apply it (the drill refuses such a file).
5. **Reconcile:** `venv/bin/python -m astryx.security.pg_role_sync apply`. It sets the role's password FROM `~/.pgpass`, as a
   client-side SCRAM verifier over the container's local socket; the value is never printed or sent as plaintext.
   Then `check` passes.
6. **The data.** `docker exec -i genesis-pg pg_restore --no-owner -U genesis -d astryx < backups/astryx-<ts>.dump`.
   With the roles in place this reports ZERO errors; an error here means the restore is incomplete, whatever the row
   counts say.
7. **Verify:** `bash scripts/restore_verify.sh`, then `./init.sh doctor`.

## How this path is proven

`scripts/restore_drill.sh` rehearses steps 1–6 on a throwaway server every week, inside `restore_verify.sh`: an empty
docker volume, initdb with a placeholder, a temp passfile with a random value, `check` failing first (the premise),
the paired roles file applied with every role present (a file with password material refused), `apply`, `check`
passing, the placeholder refused, and the
newest dump restored with zero error lines and read through the synced role. A dump older than roles capture has no
roles file: the drill says roles NOT VERIFIED (exit 3), and restore_verify fails the run on it. A drill that can't
run (no docker, no image) fails the run; `backups/.last-restore-ok` says OK only when every step,
the drill included, passed. `tests/test_restore_drill.py` drills a small fixture dump on every check.
