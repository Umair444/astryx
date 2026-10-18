# Adding a second org to this host (plan-11324, the live cog)

Seed asked for this runbook (#60778). Forge wrote it after reading the substrate (#60779), under seed's ruling #60780:
**the primary org moves as little as possible when a cog forms**. Every step carries a status:

- `READY`: the command exists and is proven (an oracle, or a measurement on this host, cited).
- `BLOCKED(Sn)`: it waits on slice Sn below. Its command is written here as it WILL run, never as something to type now.
- `OWNER`: a sudo line, run by the owner in their own terminal (never from a resident's pane: residents are the org being changed).

Nothing here touches `/etc` until the fixture rehearsal (S6) is green.

## The slices this waits on (seed #60780, in order)

| | slice | why |
|---|---|---|
| S1 | `primary: true` in the registry (orgs.py, home.mjs, parity cases): at most one; it keeps the DEFAULT tmux socket, PLAIN unit names and today's ports; `door`, if set, must be the primary | without it, every tmux caller moves to `-L ax-<key>` the moment the registry has two entries (orgs.tmux). agent_heal.bodies reads "no server running" as the EMPTY set, the cold-boot answer, and agent_heal spawns every missing seat: all 17 of our agents would start a SECOND time on `-L ax-astryx` while the originals live on the default socket, two residents per name on one wire (a2 #60783 A-2). So the registry waits for S1 DEPLOYED (agent_heal runs on the live pulse), never merely landed |
| S2 | a cog-safe `init.sh units` (writes `units/`, nothing else) | init.sh exits 3 at its top in a cog (its `# >>> org-home guard` block); only the oracle's extracted `units_fx.sh` runs units() there today |
| S3 | check.sh pins a missing registry for the gates | `/etc/astryx/cog.json` is a host FILE: every gate would run under multi, and pushed_tree_check's env scrub can't remove it |
| S4 | deploy.sh, pause.sh, refresh.sh, smoke.sh, vitals.sh learn `@<key>` names for NON-primary orgs; the primary keeps today's verbs | each refuses in a cog today ("one-org only, refusing") |
| S5 | `devtools/cog_add_org.sh <key> --dry-run` | lab's own setup path; it never calls this checkout's init.sh (see the trap in step 2) |
| S6 | the full rehearsal on a fixture registry (`ASTRYX_COG_REGISTRY=<tmp>`) | steps 2 to 6, end to end, before `/etc` |

## 1. Does our estate move? `READY`: no

Nothing refuses the checkout as a registered HOME. `paths._resolve_multi` takes any HOME that `orgs.org_of` finds, and
orgenv, spawn.sh and config hold no other check. The registry names `/home/umair/astryx` as `astryx`'s home:

- key `astryx` (registry keys are `[a-z0-9][a-z0-9-]{0,62}`, so the federation name `umairfiaz.com` can't be one; `/o/<key>/`, sockets and unit instances use the KEY)
- `db`: `astryx` (`orgs.db_of` on our `.env` DSN; `config.dsn` checks that pair in a cog)
- `primary: true` (S1), `door: true`

No file moves, no link changes. Every unit already carries `Environment=ASTRYX_HOME=/home/umair/astryx` (12 of 12
installed, a2 #60783) and every resident's channel server carries it too (spawn.sh's channel config), so the env rung
resolves them unchanged.

What does change (a2 #60783 A-3): anything run INSIDE the checkout WITHOUT ASTRYX_HOME gets NoHome in a cog. That covers
the owner's own shell, any `venv/bin/python …` tool, and wall.sh. It fails closed and loud. The `READY`, reversible step
that keeps them resolving to our org, done before the registry:

    touch /home/umair/astryx/.astryx        # the marker rung (paths.find_marker); /.astryx is gitignored (.gitignore)
    # rollback: rm /home/umair/astryx/.astryx

a2 measured it on a fixture. With the marker, a shell in `homes/x` resolves to our org. A worktree (its `.git` is a
FILE) still gets NoHome, because find_marker stops at the first git root, so worktrees stay fail-closed.

## 2. Create org #2, `lab`: `BLOCKED(S5)`

**The trap S5 closes by construction.** Never `ASTRYX_HOME=<lab> ./init.sh` on this checkout. On a one-org host the resolver
honours ASTRYX_HOME only when it names the checkout itself (paths.py, rung 1), so that line re-initialises OUR org. It
would also spawn `ax-seed` on the default socket, where ours lives.

What `cog_add_org.sh lab --dry-run` will print, and then do without `--dry-run`:

- HOME `/home/umair/astryx-orgs/lab` (outside every checkout, so no marker walk can reach ours), with a `.astryx` marker FILE, `agents/seed.md`, `local.md` (lab's law: a test org) and `homes/`
- its database `astryx_lab` on genesis-pg, created by our DSN's role (R1: one owner, one superuser), then:
  - schema.sql applied and stamped exactly as init.sh's `_act_schema` does (`schema_applied`)
  - `REVOKE CONNECT ON DATABASE astryx_lab FROM PUBLIC` (init.sh's harden)
- its `.env`, mode 600:
  - `ASTRYX_ORG=lab.umairfiaz.com`
  - `ASTRYX_DSN` naming `astryx_lab`
  - a fresh `ASTRYX_SECRET_KEY` (Ed25519 seed) and a fresh `OBS_KEY`
  - `ASTRYX_URL=` empty: it is reached through our cog gateway
  - no channel lines (no routes-*.json, so no bridge unit is ever wanted)
- its registry entry: `{"home": ".../lab", "db": "astryx_lab", "ports": {...}}`, no `primary`, no `door`

The script prints every secret's NAME, never its value.

## 3. The ports: `READY` (measured on this host, 2026-10-19 01:20)

Listening now: 8090 8091 8092 8460 8477 8478 8479 8766 8845 (plus non-astryx: 22 53 139 445 631 5432 8096 8767 9091 11434 …).
COG-scoped, no org may take one: 8090 (the front), 8845 (the gateway).

| stem | astryx (primary: today's) | lab |
|---|---|---|
| astryx-observatory-org | 8190 (new: our backend behind the front) | 18190 |
| astryx-canvas | 8091 | 18091 |
| astryx-whatsapp | 8477 | (none: no routes) |
| astryx-telegram | 8478 | |
| astryx-discord | 8479 | |
| astryx-senses | 8460 | |
| astryx-geoloc | 8766 | |
| astryx-ear | 8092 | |
| astryx-growbot | 8470 (declared, installed off) | |

8190, 18190 and 18091 were free at the measurement. Re-check just before writing the registry:
`ss -ltnH '( sport = :8190 or sport = :18190 or sport = :18091 )'` must print nothing.

## 4. The registry and the units: `BLOCKED(S1, S2, S3, S4)`, then `OWNER`

In order, each line the owner's:

1. The gates first (S3 landed and deployed), so no land runs its oracles under the new registry.
2. `sudo install -d -m 755 /etc/astryx && sudo install -m 644 <the file cog_add_org.sh printed> /etc/astryx/cog.json`
3. The units, written to `units/` only (S2):
   - ours: `ASTRYX_HOME=/home/umair/astryx ./init.sh units`. As the primary its units stay plain-named and byte-identical, except that `astryx-observatory.service` is no longer ours, and ours gains `astryx-observatory-org.service` on 8190.
   - lab's: `ASTRYX_HOME=/home/umair/astryx-orgs/lab ./init.sh units`, giving `astryx-<stem>@lab.*`
   - the cog's: `env -u ASTRYX_HOME ./init.sh units`, giving the gateway (with the registry in its env) and the front as `astryx-observatory.service`
4. The one migrated service, owner present:
   - `sudo systemctl stop astryx-observatory`
   - install the front's `astryx-observatory.service` and our `astryx-observatory-org.service`, then `sudo systemctl daemon-reload && sudo systemctl enable --now astryx-observatory-org astryx-observatory`
   - restart the gateway on its cog unit: `sudo systemctl restart astryx-gateway`
5. Lab's units: install `astryx-*@lab.*`, then `sudo systemctl enable --now astryx-observatory-org@lab astryx-canvas@lab astryx-pulse@lab.timer`. Residents: step 5, never its residents unit.

## 5. Start lab's seed only: `BLOCKED(S1)`

`ASTRYX_HOME=/home/umair/astryx-orgs/lab scripts/spawn.sh seed`. Its tmux server is `-L ax-lab` (orgs.socket), so
`tmux -L ax-lab ls` shows `ax-seed` and our default server still shows our 17. Lab's agents/ holds only seed.md, so
lab's agent_heal can only ever heal seed.

## 6. Verify: `BLOCKED(S6)` on a fixture first, then live

S6's rehearsal holds an arm for the double spawn (a2 #60783): with the registry at two entries and S1 reverted, the
rehearsal must SEE agent_heal plan to spawn our org's seats; with S1, agent_heal spawns nothing on our org.

| check | command | pass |
|---|---|---|
| the cog lists two rooms | `curl -s localhost:8090/api/cog` | `orgs` holds `astryx` and `lab`, each with its `/o/<key>/` base |
| lab's observatory | `curl -s -o /dev/null -w '%{http_code}' localhost:8090/o/lab/api/overview` | 200 (lab's own) |
| ours, behind the front | the same at `/o/astryx/api/overview` | 200, our agent counts |
| the gateway routes by to_org | lab's seed sends `seed@umairfiaz.com` | a row in OUR `messages` with `from_org='lab.umairfiaz.com'`, delivered in-process (bridges/gateway.py loopback; test_gateway_cog G3) |
| our residents unmoved | `tmux ls` | our 17, on the default socket |
| our units | a units() render diffed against `/etc/systemd/system` | identical, except `astryx-observatory.service` (now the front) and the new `astryx-observatory-org.service` |

The proofs that exist today, on fixtures: test_observatory_cog (two rooms; the `/o/<org>/` pipe adds no authority),
test_gateway_cog (a sibling's row crosses by to_org), test_canvas_cog (each org's session at its own path),
test_org_home_units (each org's units disjoint).

## 7. Rollback: `BLOCKED(S2)` for the render, otherwise `OWNER`

1. `sudo systemctl disable --now astryx-observatory-org@lab astryx-canvas@lab astryx-pulse@lab.timer`, and kill only lab's server: `tmux -L ax-lab kill-server` (never a bare kill-server)
2. `sudo systemctl stop astryx-observatory astryx-observatory-org`, then `sudo rm /etc/astryx/cog.json`
3. `./init.sh units` (one org again), then reinstall our plain `astryx-observatory.service` (main:app on :8090) and `sudo systemctl restart astryx-observatory astryx-gateway`
4. Verify byte-identity: the render equals the pre-cog `/etc/systemd/system` copies (13 files, as measured after the S3b+S3c land, #60734)
5. Lab's data stays until the owner says otherwise: `/home/umair/astryx-orgs/lab` and database `astryx_lab` (dropping them is a separate, deliberate act)

Rollback restores one-org byte-identity. That invariant holds for the ROLLBACK, not for the cog: inside a cog our
observatory is a backend behind the front.
