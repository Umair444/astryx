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
| S5 | `devtools/cog_add_org.py <key> --home DIR --name FED --dry-run` | lab's own setup path; it never calls this checkout's init.sh (see the trap in step 2) |
| S6 | the full rehearsal on a fixture registry (`ASTRYX_COG_REGISTRY=<tmp>`): tests/test_cog_rehearsal.py | steps 2 to 6, end to end, before `/etc`. The positive CREATE DATABASE is not a gate, by law (no gate makes a non-fixture database; orgs.load refuses a fixture's as an org db): step 2 itself proves it, then `--verify-lab` (seed #61011) |
| S7 | a cog-safe `./init.sh doctor`: on a registry host it serves the PRIMARY (ASTRYX_HOME, or the checkout's marker) and judges only its units, its seats on its own server; any other org refuses, naming its vitals.sh and smoke.sh (seed #61003, #61017): tests/test_doctor_cog.py. STATED LIMIT, S7b (after plan-11324, not blocking /etc): a doctor for a non-primary org, its ~60 checkout-relative reads made `$ORGH`-relative | `./init.sh doctor` refuses in a cog today (exit 3), and it is the first line of every breakage path: the primary must not lose it on the cog's first day |

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
the owner's own shell, any `venv/bin/python …` tool, and wall.sh. It fails closed and loud, and the NoHome names the
marker. A HARD PREREQUISITE of the registry step (§4 step 2; seed #60792), `READY` and reversible, keeps the Python
tools resolving to our org (a node tool still refuses: home.mjs has no marker rung, a2 #60785):

    touch /home/umair/astryx/.astryx        # the marker rung (paths.find_marker); /.astryx is gitignored (.gitignore)
    # rollback: rm /home/umair/astryx/.astryx

a2 measured it on a fixture. With the marker, a shell in `homes/x` resolves to our org. A worktree (its `.git` is a
FILE) still gets NoHome, because find_marker stops at the first git root, so worktrees stay fail-closed.

## 2. Create org #2, `lab`: `SEED`, after the S6 and S7 markers (`devtools/cog_add_org.py`, S5 landed d3c1714; oracles tests/test_cog_add_org.py, tests/test_cog_rehearsal.py)

**The trap S5 closes by construction.** Never `ASTRYX_HOME=<lab> ./init.sh` on this checkout. On a one-org host the resolver
honours ASTRYX_HOME only when it names the checkout itself (paths.py, rung 1), so that line re-initialises OUR org. It
would also spawn `ax-seed` on the default socket, where ours lives.

Seed runs it (#61011), from this checkout, on a one-org host (no `/etc/astryx/cog.json` yet), in this order. It is
reversible, touches no `/etc`, installs and starts no unit, and our org does not move; seed reads our live tmux count
(17) before and after. Exactly what test_cog_rehearsal R1/R2 rehearse:

    mkdir -p /home/umair/orgs && test ! -e /home/umair/orgs/lab
    venv/bin/python devtools/cog_add_org.py lab --home /home/umair/orgs/lab --name lab.umairfiaz.com \
        --ports astryx-observatory-org=18190,astryx-canvas=18091 --out /home/umair/orgs/lab.cog.json --dry-run
    venv/bin/python devtools/cog_add_org.py lab --home /home/umair/orgs/lab --name lab.umairfiaz.com \
        --ports astryx-observatory-org=18190,astryx-canvas=18091 --out /home/umair/orgs/lab.cog.json \
        2>&1 | tee /home/umair/orgs/lab.step2.log
    venv/bin/python tests/test_cog_rehearsal.py --verify-lab /home/umair/orgs/lab /home/umair/orgs/lab.cog.json \
        /home/umair/orgs/lab.step2.log          # ALL PASS: the made database, its stamp, the REVOKE, the .env, the registry

The undo (lab's alone; our database, units and residents are never touched):

    venv/bin/python -c 'import sys; sys.path.insert(0, "src"); import psycopg; from astryx import config; psycopg.connect(config.dsn(), autocommit=True).execute("DROP DATABASE astryx_lab")'
    rm -rf /home/umair/orgs/lab /home/umair/orgs/lab.cog.json /home/umair/orgs/lab.step2.log

What it prints (`--dry-run`) and then does (the registry goes to `--out`, never /etc; our entry is DERIVED: this
checkout, `astryx`, its database, primary + door, today's ports and 8190):

- HOME `/home/umair/orgs/lab` (outside every checkout, so no marker walk can reach ours), with a `.astryx` marker FILE, `agents/seed.md`, `local.md` (lab's law: a test org) and `homes/`
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

## 4. The registry and the units: `OWNER` (S1-S7 landed: 45617e5, 907c294, c2919b7, 5ae8d03, 73c9479, d3c1714, 27d1aa3; step 2 done and `--verify-lab` ALL PASS, seed #61076)

In order, each line the owner's:

1. The gates first (S3 landed and deployed), so no land runs its oracles under the new registry.
   And the marker (§1, a hard prerequisite): `touch /home/umair/astryx/.astryx`, then `test -f /home/umair/astryx/.astryx`
   must pass before step 2. Its proof: test_org_home_units U12, where no ASTRYX_HOME and no marker gives a NoHome naming
   it, and the marker resolves to the primary.
2. `sudo install -d -m 755 /etc/astryx && sudo install -m 644 <the file cog_add_org.py wrote, its --out> /etc/astryx/cog.json`
3. The units, written to `units/` only (S2), each under `env -u ASTRYX_COG_REGISTRY`, so all three read the registry
   step 2 just installed. The cog's units BAKE IN the registry path of the shell that renders them
   (`Environment=ASTRYX_COG_REGISTRY=${ASTRYX_COG_REGISTRY:-/etc/astryx/cog.json}`, init.sh units()): a shell still
   exporting a scratch registry from a pre-check would install a gateway and a front that read the scratch file, not
   /etc (forge #61077, found rendering from the real `--out`):
   - ours: `env -u ASTRYX_COG_REGISTRY ASTRYX_HOME=/home/umair/astryx ./init.sh units`. As the primary its units stay plain-named and byte-identical, except that `astryx-observatory.service` is no longer ours, and ours gains `astryx-observatory-org.service` on 8190.
   - lab's: `env -u ASTRYX_COG_REGISTRY ASTRYX_HOME=/home/umair/orgs/lab ./init.sh units`, giving `astryx-<stem>@lab.*`
   - the cog's: `env -u ASTRYX_COG_REGISTRY -u ASTRYX_HOME ./init.sh units`, giving the gateway (with the registry in its env) and the front as `astryx-observatory.service`

   THE CHECK, before ANY install (this step's own, or `scripts/deploy.sh units --cog`, which copies these files from
   `units/` verbatim and renders nothing):

       grep -H '^Environment=ASTRYX_COG_REGISTRY=' units/astryx-gateway.service units/astryx-observatory.service

   must print exactly these two lines (in either order), and anything else means STOP: re-render with the `env -u` above,
   never install:

       units/astryx-gateway.service:Environment=ASTRYX_COG_REGISTRY=/etc/astryx/cog.json
       units/astryx-observatory.service:Environment=ASTRYX_COG_REGISTRY=/etc/astryx/cog.json

   And ours against what is installed, measured on the real `--out` before the owner session (forge #61077): 11
   IDENTICAL byte for byte (canvas, discord, ear, geoloc, growbot, pulse.service, pulse.timer, residents, senses,
   telegram, whatsapp), 1 NEW (`astryx-observatory-org.service`: main:app on 127.0.0.1:8190, our ASTRYX_HOME), and
   `astryx-observatory.service` and `astryx-gateway.service` the cog's. Re-check it here: each of ours must `cmp` equal
   to its `/etc/systemd/system` copy, but for the one NEW file:

       for f in units/astryx-*.service units/astryx-*.timer; do b=${f#units/}; case $b in *@*|astryx-gateway.service|astryx-observatory.service|astryx-observatory-org.service) continue ;; esac; cmp -s "$f" "/etc/systemd/system/$b" || echo "DIFFERS: $b"; done
4. The one migrated service, owner present:
   - `sudo systemctl stop astryx-observatory`
   - install the front's `astryx-observatory.service` and our `astryx-observatory-org.service`, then `sudo systemctl daemon-reload && sudo systemctl enable --now astryx-observatory-org astryx-observatory`
   - restart the gateway on its cog unit: `sudo systemctl restart astryx-gateway`
5. Lab's units: install `astryx-*@lab.*`, then `sudo systemctl enable --now astryx-observatory-org@lab astryx-canvas@lab astryx-pulse@lab.timer`. Residents: step 5, never its residents unit.

## 5. Start lab's seed only: `READY` after step 4 (S1 landed: the primary keeps the default socket)

`ASTRYX_HOME=/home/umair/orgs/lab scripts/spawn.sh seed`. Its tmux server is `-L ax-lab` (orgs.socket), so
`tmux -L ax-lab ls` shows `ax-seed` and our default server still shows our 17. Lab's agents/ holds only seed.md, so
lab's agent_heal can only ever heal seed.

## 6. Verify: on a fixture, tests/test_cog_rehearsal.py (S6); then live, `OWNER` after step 4

S6's rehearsal holds the arm for the double spawn (a2 #60783), R5: on our seats alive on the default socket, with the
registry step 2 wrote agent_heal plans NOTHING on our org; with S1 reverted (no primary) it plans every seat again, the
negative control (and mutant O1 reverts S1 in orgs.py itself: caught).

| check | command | pass |
|---|---|---|
| the cog lists two rooms | `curl -s localhost:8090/api/cog` | `orgs` holds `astryx` and `lab`, each with its `/o/<key>/` base |
| lab's observatory | `curl -s -o /dev/null -w '%{http_code}' localhost:8090/o/lab/api/overview` | 200 (lab's own) |
| ours, behind the front | the same at `/o/astryx/api/overview` | 200, our agent counts |
| the gateway routes by to_org | lab's seed sends `seed@umairfiaz.com` | a row in OUR `messages` with `from_org='lab.umairfiaz.com'`, delivered in-process (bridges/gateway.py loopback; test_gateway_cog G3) |
| our residents unmoved | `tmux ls` | our 17, on the default socket |
| our units | a units() render diffed against `/etc/systemd/system` | identical, except `astryx-observatory.service` (now the front) and the new `astryx-observatory-org.service` |

**LIVE, 2026-10-19** (step 4 run by seed under the owner's sudo grant; every row above curled after the S3f fixes
c21a5ca, eb4a4b0, 9b4c37c, at origin/main 507aa38): `/api/cog` lists `astryx` (`/o/astryx/`) and `lab` (`/o/lab/`);
both overviews 200 through the front; `/relay/host` 200 on the cog's gateway; a lab→seed row in our `messages` with
`from_org='lab.umairfiaz.com'`; our 17 on the default socket, lab's seed alone on `-L ax-lab`; the front, ours and
lab's units all active. One OBS_KEY opens both rooms (cog_add_org.owner_key); a registry or .env change needs every
import-time reader restarted (canvas, observatory-org, gateway, front), then a browser-path check, not `is-active`.

The proofs that exist today, on fixtures: test_observatory_cog (two rooms; the `/o/<org>/` pipe adds no authority),
test_gateway_cog (a sibling's row crosses by to_org), test_canvas_cog (each org's session at its own path),
test_org_home_units (each org's units disjoint).

## 7. Rollback: `READY` (S2 landed: `./init.sh units` renders), otherwise `OWNER`

1. `sudo systemctl disable --now astryx-observatory-org@lab astryx-canvas@lab astryx-pulse@lab.timer`, and kill only lab's server: `tmux -L ax-lab kill-server` (never a bare kill-server)
2. `sudo systemctl stop astryx-observatory astryx-observatory-org`, then `sudo rm /etc/astryx/cog.json`
3. `./init.sh units` (one org again), then reinstall our plain `astryx-observatory.service` (main:app on :8090) and `sudo systemctl restart astryx-observatory astryx-gateway`
4. Verify byte-identity: the render equals the pre-cog `/etc/systemd/system` copies (13 files, as measured after the S3b+S3c land, #60734)
5. Lab's data stays until the owner says otherwise: `/home/umair/orgs/lab` and database `astryx_lab` (dropping them is a separate, deliberate act)

Rollback restores one-org byte-identity. That invariant holds for the ROLLBACK, not for the cog: inside a cog our
observatory is a backend behind the front.
