# Restoring the org from a backup

A backup is a pair in `backups/`: `astryx-<ts>.dump` (pg_dump custom format) and `astryx-<ts>.state.tgz` (the
gitignored estate the dump can't carry: `triggers/`, `memory/`, `~/.pgpass`, … — see `nucleus/backup.sh`). This is
the path for an EMPTY server: a new disk, a lost data dir, a new host.

## The one seam: the role's password

The org's DSN carries no password; every client reads it from `~/.pgpass`. On an empty data dir, the image's initdb
creates `POSTGRES_USER` with `infra/pg/.env`'s `POSTGRES_PASSWORD`, which on an existing org is a deliberate
placeholder (a live value there would sit in `docker inspect genesis-pg`; #5497). So after a restore, the server holds
the placeholder and the restored `~/.pgpass` holds the real value, and every login fails until step 4 reconciles them.

## Steps, in order

1. **The server.** Point `ASTRYX_PG_DATA` in `infra/pg/.env` at an empty directory and start the declared server:
   `docker compose -f infra/pg/docker-compose.yml up -d` (the image must be the one `infra/pg` declares;
   `venv/bin/python -m nucleus.pg_design` checks it).
2. **The estate.** Unpack the paired `.state.tgz`: its repo paths into the repo, its `$HOME`-relative members
   (`.pgpass`, `.claude/projects/*/memory`) into `$HOME`; `bash nucleus/backup.sh --list-state` names which is which.
   Keep `~/.pgpass` at mode 0600 (libpq ignores a looser one).
3. **Prove the seam is there:** `venv/bin/python -m nucleus.pg_role_sync check` fails with "the server's verifier and
   the pgpass value disagree". (If it passes, the data dir wasn't empty; stop and look.)
4. **Reconcile:** `venv/bin/python -m nucleus.pg_role_sync apply`. It sets the role's password FROM `~/.pgpass`, as a
   client-side SCRAM verifier over the container's local socket; the value is never printed or sent as plaintext.
   Then `check` passes.
5. **The data.** `docker exec -i genesis-pg pg_restore --no-owner -U genesis -d astryx < backups/astryx-<ts>.dump`.
   pg_restore can warn on ignorable items; the row counts are the gate.
6. **Verify:** `bash nucleus/restore_verify.sh`, then `./init.sh doctor`.

## How this path is proven

`nucleus/restore_drill.sh` rehearses steps 1–5 on a throwaway server every week, inside `restore_verify.sh`: an empty
docker volume, initdb with a placeholder, a temp passfile with a random value, `check` failing first (the premise),
`apply`, `check` passing, the placeholder refused, and the newest dump restored and read through the synced role. A
drill that can't run (no docker, no image) fails the run; `backups/.last-restore-ok` says OK only when every step,
the drill included, passed. `tests/test_restore_drill.py` drills a small fixture dump on every check.
