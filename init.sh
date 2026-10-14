#!/usr/bin/env bash
# astryx init — everything from zero to a living org in one script. Idempotent.
# Usage: ./init.sh            core org (postgres, schema, deps, seed, observatory)
#        ./init.sh whatsapp   wire WhatsApp as an owner surface (needs wacli, wacli.sh)
set -euo pipefail
# >>> self dir
# Start in the REPO however this was invoked. Through the PATH link (~/.local/bin/astryx → <repo>/init.sh), $0 is the
# LINK, so `cd "$(dirname "$0")"` landed in ~/.local/bin and every `astryx <verb>` ran outside the repo (a2 #39198).
# Resolve link chains in plain POSIX (older macOS readlink has no -f): a relative target is relative to its link's dir.
_self="$0"; _hops=0
while [ -L "$_self" ]; do
  _hops=$((_hops + 1))      # a CYCLE would spin forever, silently: cap at the kernel's ELOOP limit (a2 #39682)
  [ "$_hops" -le 40 ] || { echo "init.sh: link loop at $0" >&2; exit 1; }
  _t=$(readlink "$_self")
  case "$_t" in /*) _self="$_t" ;; *) _self="$(dirname "$_self")/$_t" ;; esac
done
cd "$(dirname "$_self")"
unset _self _t _hops
# <<< self dir

say() { echo -e "\033[36m[astryx]\033[0m $*"; }
die() { echo -e "\033[31m[astryx]\033[0m $*" >&2; exit 1; }

# The units the owner should ENABLE: [Install]-bearing, and not declared installed-but-disabled (a remote body's growbot).
# ONE rule for both call sites (the setup print and doctor's remediation; a3 #43932 F1: the setup path told the owner
# to enable exactly the unit doctor forbids). Usage: _enable_list <dir> <unit>…
_enable_list() { local dir=$1 u out=""; shift
  for u in "$@"; do
    grep -q '^\[Install\]' "$dir/$u" 2>/dev/null || continue
    case " ${UNITS_EXPECT_DISABLED:-} " in *" $u "*) continue ;; esac
    out="$out $u"
  done; printf '%s' "$out"; }
# doctor (ii), as data: classifies every generated unit by `systemctl is-enabled` into
#   notenabled  a normal unit not enabled (won't survive a reboot)
#   wrongly_on  a declared-off unit that IS enabled
#   off_missing a declared-off unit that isn't installed at all (is-enabled: not-found / nothing; a3 #43932 F2)
#   off_ok      a declared-off unit installed and off: the only ones the ok line may name
_units_state() { local u st; notenabled="" wrongly_on="" off_missing="" off_ok=""
  for u in "$@"; do
    st=$(systemctl is-enabled "$u" 2>/dev/null) || true
    case " ${UNITS_EXPECT_DISABLED:-} " in
      *" $u "*) case "$st" in
                  enabled|enabled-runtime|static|alias|indirect) wrongly_on="$wrongly_on $u" ;;
                  ""|not-found) off_missing="$off_missing $u" ;;
                  *) off_ok="$off_ok $u" ;;
                esac ;;
      *) case "$st" in enabled|enabled-runtime|static|alias|indirect|generated) ;; *) notenabled="$notenabled $u" ;; esac ;;
    esac
  done; }

units() {  # GENERATE systemd units from the org's declared sources of truth.
  # units/ is generated output (gitignored), never hand-edited: this is the ONE
  # writer, so no unit can silently drift from what the org actually runs (the
  # footgun that hid telegram/discord/gateway/canopus-inbound from the UI). The
  # set derives from four authorities (plan-17):
  #   1. shipped-set  — the units every org always has (below, unconditional)
  #   2. channels     — inbound CONVERSATION; one per bridges/routes-<name>.json present
  #   3. senses       — inbound PERCEPTION; one per sense module+grant present
  #   4. runners      — per-agent pollers declared in nucleus/runners.conf
  # doctor reconciles the enabled set against this same derivation, bidirectionally.
  local UD=${UNITS_DIR:-units}
  mkdir -p "$UD"

  # ── 1. shipped-set — always present ─────────────────────────────────────────
  cat > "$UD/astryx-observatory.service" <<EOF
[Unit]
Description=astryx observatory — public live view on :8090
After=network.target
[Service]
WorkingDirectory=$PWD/observatory/api
ExecStart=$PWD/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8090
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  cat > "$UD/astryx-canvas.service" <<EOF
[Unit]
Description=astryx canvas — the owner's front door: chat with agents, live agent-painted canvases (proxied by the observatory at /canvas/)
After=network.target
[Service]
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/uvicorn bridges.canvas:root --host 127.0.0.1 --port 8091
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  cat > "$UD/astryx-pulse.service" <<EOF
[Unit]
Description=astryx pulse — one tick of the trigger clock
[Service]
Type=oneshot
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/python $PWD/nucleus/pulse.py
User=$USER
# KillMode=process, NOT the default control-group: this oneshot BY DESIGN spawns detached
# long jobs (org_runners _launch: backup/check/restore-verify/mutant-battery) that must
# outlive the ~seconds tick. control-group kill reaps the whole cgroup when pulse.py exits,
# murdering exactly those children (dead since the 2026-08-21 timer→trigger migration; a
# start_new_session Popen escapes the session/pgroup but NOT the cgroup). The synchronous
# trigger evals are subprocess.run(capture_output) — they COMPLETE before pulse.py exits, so
# nothing here relies on cgroup cleanup; only the detached jobs linger, and they should.
KillMode=process
EOF
  cat > "$UD/astryx-pulse.timer" <<EOF
[Unit]
Description=astryx pulse — every minute (cron resolution; the OS owns the clock)
[Timer]
OnCalendar=*-*-* *:*:00
AccuracySec=1s
Persistent=true
[Install]
WantedBy=timers.target
EOF
  # pulse-watch units are DELIBERATELY not generated (one-clock ruling, 2f85ec6):
  # "exactly one timer exists in the whole system" — the owner's words. The pulse's
  # external witness therefore rides an always-on SERVICE's own loop (the whatsapp
  # bridge checks triggers.last_eval staleness), never a second timer. A prior
  # generator block here kept emitting units for the deleted nucleus/pulse_watch.py
  # — a unit that cannot start plus a second clock, on every fresh host (scout,
  # 2026-08-25).
  cat > "$UD/astryx-gateway.service" <<EOF
[Unit]
Description=astryx gateway — the org's one door to other orgs (:8845)
After=network.target
[Service]
WorkingDirectory=$PWD/bridges
ExecStart=$PWD/venv/bin/uvicorn gateway:app --host 0.0.0.0 --port 8845
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  # residents: reboot-safety by DEFAULT — spawns every charter in the tree as a
  # tmux body at boot (the "please respawn the residents" gap this closes).
  cat > "$UD/astryx-residents.service" <<EOF
[Unit]
Description=astryx residents — spawn every agent in the tree as a tmux body at boot
# docker: the org's postgres runs in a container the residents connect to.
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=$USER
Environment=HOME=$HOME
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$PWD/nucleus/spawn-all.sh

[Install]
WantedBy=multi-user.target
EOF

  # ── 2. channels — one service per present routes-<name>.json ─────────────────
  # Presence signal = the channel's routing file exists (the org has wired it).
  [ -f bridges/routes-whatsapp.json ] && cat > "$UD/astryx-whatsapp.service" <<EOF
[Unit]
Description=astryx whatsapp bridge — owner surface on the wire
After=network.target docker.service
[Service]
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/uvicorn bridges.whatsapp:app --host $(_docker_host_ip) --port 8477
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  [ -f bridges/routes-discord.json ] && cat > "$UD/astryx-discord.service" <<EOF
[Unit]
Description=astryx discord bridge — owner surface on the wire
After=network.target
[Service]
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/uvicorn bridges.discord:app --host 127.0.0.1 --port 8479
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  [ -f bridges/routes-telegram.json ] && cat > "$UD/astryx-telegram.service" <<EOF
[Unit]
Description=astryx telegram bridge — owner surface on the wire
After=network.target
[Service]
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/uvicorn bridges.telegram:app --host 127.0.0.1 --port 8478
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF

  # ── 3. senses — one service per present sense (module + a grant) ─────────────
  # A sense is inbound PERCEPTION → org STATE, not the wire. Its presence signal is
  # its MODULE + a charter GRANT (NOT a routes file — a sense never routes to the
  # wire, so keying on routes*.json would read every sense as absent; plan-17 a1).
  # (no sense modules ship in the public tree; a sense adds its own module + grant here —
  # presence-gated exactly like a channel, generating one astryx-<sense>.service unit.)
  UNITS_EXPECT_DISABLED=""        # units declared here that must be INSTALLED but NOT enabled (doctor checks both ways)

  # ── 3c. senses — the afferent API layer (nucleus/senses.py serves sensors/<agent>/*.py on :8460) ─────────
  # Declared 10-10 (seed #43920: it ran, enabled and active, while nothing generated it). Presence signal = the server
  # module + at least one sensor: writing sensors/<agent>/<name>.py IS deploying (senses.py's own law), so an org with
  # no sensor grows no service.
  if [ -f nucleus/senses.py ] && compgen -G "sensors/*/*.py" >/dev/null; then
    cat > "$UD/astryx-senses.service" <<EOF
[Unit]
Description=astryx senses — the afferent API layer (sensors/<agent>/*.py served on :8460)
After=network.target docker.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/python $PWD/nucleus/senses.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  fi

  # ── 3d. geoloc — the phone's location intake (bridges/geoloc.py, :8766) ─────────────────────────────────────
  # Declared 10-10 (seed #43920). Presence signal = the bridge module (gitignored: its rows are location history, the
  # personal tier) + its env file outside the repo (the token and the DSN it writes with). It binds 0.0.0.0 on
  # purpose: the phone posts to it over the LAN/tailnet, which is the service. The design is declared; the values never.
  if [ -f bridges/geoloc.py ] && [ -f "$HOME/.config/astryx/geoloc.env" ]; then
    cat > "$UD/astryx-geoloc.service" <<EOF
[Unit]
Description=astryx geoloc bridge — phone location intake on :8766
After=network.target
[Service]
WorkingDirectory=$PWD/bridges
EnvironmentFile=$HOME/.config/astryx/geoloc.env
ExecStart=$PWD/venv/bin/uvicorn geoloc:app --host 0.0.0.0 --port 8766
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  fi

  # ── 3a. the ear — hearing (plan-8674 S1): browser speech segments → local STT → `utterances` ───────────────
  # Presence signal = EAR_ENABLED=1 in .env. An always-on microphone is a DELIBERATE owner act, so no fresh clone
  # grows one by default. Loopback only: the observatory proxies <host>/ear/ to it.
  ear_on=$(grep -m1 '^EAR_ENABLED=' .env 2>/dev/null | cut -d= -f2- || true)
  if [ "$ear_on" = 1 ] && [ -f bridges/ear.py ]; then
    cat > "$UD/astryx-ear.service" <<EOF
[Unit]
Description=astryx ear — hearing: VAD speech segments from the observatory → local STT → the ear store (:8092, via /ear/)
After=network.target docker.service
[Service]
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/uvicorn bridges.ear:app --host 127.0.0.1 --port 8092
Restart=always
RestartSec=5
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  fi

  # ── 3b. growbot body — the org's PHYSICAL body (a GrowBot Pico on USB serial) ─
  # Presence signal = the body host organ + a LIVE charter granting the growbot
  # hands (.example.md excluded: shipping the example must not grow a servo
  # service in an org that owns no robot). And ONLY for a local body: astryx is
  # an extension of the open GrowBot protocol, not a fork — a GROWBOT_BODY_URL
  # in .env pointing at a remote body (Brit's own Wi-Fi firmware on a Pico W)
  # means the chip serves the protocol itself and no host service must run.
  # `|| true`: on a fresh clone .env is absent (grep rc=2) or lacks the line (rc=1); under
  # `set -eo pipefail` a bare assignment from that pipe would abort the whole script. This is
  # the ONE bare (set-e-active) units() call path — `./init.sh doctor` on a fresh clone — so
  # the maintainer never saw it (their .env has GROWBOT_BODY_URL). Empty = no URL = local body.
  gb_url=$(grep -m1 '^GROWBOT_BODY_URL=' .env 2>/dev/null | cut -d= -f2- || true)
  # The unit is DECLARED whenever the module and a live grant exist (seed #43920: it sat on disk and in systemd with
  # nothing generating it). WHERE the body runs decides only its STATE: a local body's unit must be enabled; a remote
  # body (GROWBOT_BODY_URL elsewhere: the chip serves the protocol itself) must leave it installed and NOT enabled.
  if [ -f nucleus/growbot_body.py ] && \
     grep -rqsE '^Grants:.*\bgrowbot\b' --exclude='*.example.md' agents/; then
    { [ -z "$gb_url" ] || echo "$gb_url" | grep -qE '127\.0\.0\.1|localhost'; } \
      || UNITS_EXPECT_DISABLED="$UNITS_EXPECT_DISABLED astryx-growbot.service"
    cat > "$UD/astryx-growbot.service" <<EOF
[Unit]
Description=astryx growbot body — the open GrowBot body protocol over the USB-serial Pico (:8470)
After=network.target
[Service]
WorkingDirectory=$PWD
EnvironmentFile=-$PWD/.env
ExecStart=$PWD/venv/bin/python $PWD/nucleus/growbot_body.py
Restart=always
RestartSec=3
User=$USER
[Install]
WantedBy=multi-user.target
EOF
  fi

  # ── 4. runners — periodic jobs from nucleus/runners.conf ─────────────────────
  # <stem> | <agent> | <OnCalendar> | <exec from repo root> | <description>
  # A per-agent poller is gated on its agent resolving (the ONE resolver) so a decl for
  # a departed agent generates nothing. agent="org" is ORG-INFRA (backup, etc.) — always
  # generated, no per-agent gate. A .py exec runs under venv python; a .sh exec runs
  # directly (executable + shebang), so org-infra bash jobs (pg_dump) are first-class.
  if [ -f nucleus/runners.conf ]; then
    while IFS='|' read -r stem agent oncal execp desc; do
      stem=$(echo "$stem" | xargs); [ -z "$stem" ] && continue
      case "$stem" in \#*) continue;; esac
      agent=$(echo "$agent" | xargs); oncal=$(echo "$oncal" | xargs)
      execp=$(echo "$execp" | xargs); desc=$(echo "$desc" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
      if [ "$agent" != org ] && ! venv/bin/python nucleus/charter.py "$agent" >/dev/null 2>&1; then
        echo "  runner '$stem': agent '$agent' not in roster — no unit generated" >&2; continue
      fi
      case "$execp" in
        *.sh) rexec="$PWD/$execp" ;;
        *)    rexec="$PWD/venv/bin/python $PWD/$execp" ;;
      esac
      cat > "$UD/astryx-$stem.service" <<EOF
[Unit]
Description=astryx $stem — $desc
[Service]
Type=oneshot
WorkingDirectory=$PWD
ExecStart=$rexec
User=$USER
EOF
      cat > "$UD/astryx-$stem.timer" <<EOF
[Unit]
Description=astryx $stem — poll on $oncal
[Timer]
OnCalendar=$oncal
AccuracySec=5s
Persistent=true
[Install]
WantedBy=timers.target
EOF
    done < nucleus/runners.conf
  fi
}

active_dep_groups() {  # which manifest groups this org needs, from the channel authority
  # core always; media when any channel that can carry voice is wired (same
  # channels-present authority the units-generator gates on — one authority).
  local g="core"
  for ch in whatsapp discord telegram; do
    [ -f "bridges/routes-$ch.json" ] && { g="$g media"; break; }
  done
  echo "$g"
}

org_identity() {  # federation identity: org name + Ed25519 keypair, once
  grep -q '^ASTRYX_ORG=' .env 2>/dev/null || {
    echo "ASTRYX_ORG=$(hostname -s | tr 'A-Z' 'a-z')" >> .env
    say "org name set to '$(hostname -s | tr 'A-Z' 'a-z')' — edit ASTRYX_ORG in .env (your domain, once you have one)"; }
  grep -q '^ASTRYX_SECRET_KEY=' .env 2>/dev/null || {
    venv/bin/python - <<'PYEOF' >> .env
from nacl.signing import SigningKey
from nacl.encoding import HexEncoder
k = SigningKey.generate()
print("ASTRYX_SECRET_KEY=" + k.encode(HexEncoder).decode())
PYEOF
    say "org keypair generated (ASTRYX_SECRET_KEY in .env — this IS your org's identity, guard it)"; }
  grep -q '^ASTRYX_URL=' .env 2>/dev/null || {
    echo "ASTRYX_URL=" >> .env
    say "ASTRYX_URL empty: NAT mode (your gateway will long-poll peers). Set it when you have a public address."; }
}

# ============================================================ the reconciler
# setup is a RE-ENTRANT RECONCILER, not a linear todo-script. Each precondition is a
# NODE with a CHECK (the terminal observable — same shape doctor uses) and, if the org
# can drive it, an ACTUATE. The loop converges toward all-green; PROGRESS IS DERIVED
# (how many checks pass), never a cursor — so it is idempotent AND resumable by
# construction (a re-run re-checks every node, actuates only the red). Nodes sit on the
# 2×2 (actuatability × persistence), mirroring spawn-all.sh's two quadrants:
#   interior — the org can actuate → converge (idempotent). A NON-persistent interior
#              node (a crashed seed body) is re-checked+re-actuated EVERY pass = the
#              re-entrancy (spawn-all's has-session re-spawn is exactly this).
#   wait     — a TRANSIENT boundary (postgres accepting connections) → bounded re-probe.
#   halt     — a PERMANENT boundary the org can't drive (missing tool, human login) →
#              report, don't spin. Interior converges around it; the human resolves it.
dsn() { grep '^ASTRYX_DSN=' .env 2>/dev/null | cut -d= -f2-; }
. nucleus/pgcontainer.sh                     # PG_CONTAINER: the one declared postgres (infra/pg/docker-compose.yml)
. nucleus/docker_host_ip.sh                   # _docker_host_ip: how containers reach this host (was a literal 172.17.0.1)
# wsl2 | wsl1 | no: is this Linux running under Windows' WSL? (doctor, goal 10224 S3). WSL2 kernels say
# "microsoft-standard-WSL2" (older ones "-microsoft-standard"); WSL1 says "Microsoft" with a capital M. WSL_DISTRO_NAME is
# set in every WSL shell, the fallback when /proc/version can't be read. The path is overridable for tests.
_wsl_kind() {
  local pv
  pv=$(cat "${ASTRYX_PROC_VERSION:-/proc/version}" 2>/dev/null || true)
  case "$pv" in
    *WSL2*|*microsoft-standard*) echo wsl2; return 0 ;;
    *Microsoft*) echo wsl1; return 0 ;;
    *microsoft*) echo wsl2; return 0 ;;
  esac
  [ -n "${WSL_DISTRO_NAME:-}" ] && echo wsl2 || echo no
}
# The name of PID 1 (systemd, init, launchd, …), or "unknown" when ps can't say. macOS prints a full path: basename it.
_pid1() {
  local c
  c=$(ps -p 1 -o comm= 2>/dev/null | head -1 | tr -d '[:space:]' || true)
  [ -n "$c" ] && echo "${c##*/}" || echo unknown
}
# ok | unverified | "wide <addr …>": is anything but loopback listening on port $1? (doctor; a2 #42283)
_pg_exposure() {
  local out wide
  out=$(ss -ltnH 2>/dev/null) || { echo unverified; return; }
  [ -n "$out" ] || { echo unverified; return; }
  wide=$(printf '%s\n' "$out" | awk '{print $4}' | grep -E ":$1\$" | grep -vE '^(127\.|\[::1\]|::1)' | sort -u | tr '\n' ' ')
  [ -z "$wide" ] && echo ok || echo "wide $wide"
}
psql_q() { if command -v psql >/dev/null; then psql "$(dsn)" "$@"
  else pg_exec psql -U "$(pg_dsn_user "$(dsn)")" -d "$(pg_dsn_db "$(dsn)")" "$@"; fi; }

_chk_tools() { command -v node >/dev/null && command -v python3 >/dev/null \
  && command -v tmux >/dev/null && command -v claude >/dev/null \
  && { command -v docker >/dev/null || command -v psql >/dev/null; }; }

_chk_pg() { [ -f .env ] && grep -q '^ASTRYX_DSN=' .env; }
_act_pg() {
  # THE DECLARED SERVER (steward F4, seed #42759): infra/pg is the design (pg18 + pgvector + postgis + AGE pinned,
  # loopback only, max_connections in the compose file). Never a stock image: AGE, pgvector and postgis are part of
  # the org's design, and a stock postgres:18 carries none of them.
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$PG_CONTAINER"; then
    docker start "$PG_CONTAINER" >/dev/null
    [ -f .env ] || die "$PG_CONTAINER exists but no .env — write ASTRYX_DSN=... to .env"
  elif command -v docker >/dev/null; then
    if [ ! -f infra/pg/.env ]; then
      local pw; pw=$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 20)
      ( umask 077; printf 'POSTGRES_USER=astryx\nPOSTGRES_PASSWORD=%s\n' "$pw" > infra/pg/.env )
    fi
    # build ONLY when this host has no such image (a fresh org): never onto a tag a server already runs (a1 #43407)
    if ! docker image inspect genesis/pg18:age >/dev/null 2>&1; then
      say "building the declared postgres image (infra/pg; compiles AGE from its pinned commit: needs github.com and a few minutes)"
      docker build -q -t genesis/pg18:age infra/pg >/dev/null || die "infra/pg: docker build failed (network to github.com? a C toolchain build?)"
    fi
    say "starting the declared postgres (infra/pg)"
    docker compose -f infra/pg/docker-compose.yml up -d >/dev/null || die "infra/pg: docker compose up failed (is port 5432 already taken?)"
    local u p; u=$(grep '^POSTGRES_USER=' infra/pg/.env | cut -d= -f2-); p=$(grep '^POSTGRES_PASSWORD=' infra/pg/.env | cut -d= -f2-)
    [ -f .env ] || { echo "ASTRYX_DSN=postgres://$u:$p@127.0.0.1:5432/astryx" > .env && chmod 600 .env; }
  else die "no .env and no docker — create the db yourself and write ASTRYX_DSN=... to .env"; fi; }

_chk_pgready() { psql_q -c 'SELECT 1' >/dev/null 2>&1; }          # wait (transient boundary)

# >>> schema
# GREEN iff the database carries a stamp of the EXACT schema.sql bytes last applied in full. "Some schema exists" was
# the old check, so a host that pulled a NEW table judged itself current and skipped it (seed #38258: people-gate
# 1a's social_relation never reached a pulled host, and the peoplegate node failed "social_relation is missing").
# schema.sql is idempotent (IF NOT EXISTS / DO blocks), so a re-apply on any change is safe. The act applies a COPY,
# stamps THAT copy's sha, and stamps only after a clean ON_ERROR_STOP apply: a failed apply stays RED. psql_q feeds
# stdin, so the docker-psql path applies the same bytes.
_SCHEMA_FILE="${ASTRYX_SCHEMA:-nucleus/schema.sql}"
_STAMP_Q="SELECT sha FROM schema_applied WHERE id = 1"
_sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }  # macOS
_chk_schema() { local have want; have=$(psql_q -X -tA -c "$_STAMP_Q" 2>/dev/null) || return 1
  want=$(_sha256 "$_SCHEMA_FILE"); [ -n "$have" ] && [ "$have" = "$want" ]; }
_act_schema() { say "applying schema (schema.sql differs from what this database last applied)"
  local tmp sha rc; tmp=$(mktemp) || return 1; cp "$_SCHEMA_FILE" "$tmp" || { rm -f "$tmp"; return 1; }
  # COMMIT FIRST (seed 2026-10-09: an uncommitted ALTER applied to prod read schema-parity EXTRA on every committed
  # tree for an hour). The EXACT bytes about to be applied must equal HEAD's — compared after the copy (no TOCTOU),
  # with a path relative to -C by construction ("./basename": the default "nucleus/schema.sql" is relative), so a
  # modified, staged-but-uncommitted or never-tracked file is refused (a4 #41136 R1/R2). No git → skip; the override is loud.
  local d; d=$(dirname "$_SCHEMA_FILE")
  if env -u GIT_DIR -u GIT_WORK_TREE git -C "$d" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
     && [ "${ASTRYX_SCHEMA_DIRTY_OK:-}" != 1 ] \
     && ! { env -u GIT_DIR -u GIT_WORK_TREE git -C "$d" cat-file -e "HEAD:./$(basename "$_SCHEMA_FILE")" 2>/dev/null \
            && env -u GIT_DIR -u GIT_WORK_TREE git -C "$d" show "HEAD:./$(basename "$_SCHEMA_FILE")" | cmp -s - "$tmp"; }; then
    rm -f "$tmp"
    echo -e "\033[31m[astryx]\033[0m schema.sql differs from what git has committed (modified, staged or untracked): commit it first (prod carries only what git carries), or set ASTRYX_SCHEMA_DIRTY_OK=1 to apply anyway" >&2
    return 1
  fi
  sha=$(_sha256 "$tmp")
  psql_q -X -q -v ON_ERROR_STOP=1 < "$tmp" >/dev/null; rc=$?; rm -f "$tmp"; [ "$rc" -eq 0 ] || return 1
  psql_q -X -q -v ON_ERROR_STOP=1 \
    -c "CREATE TABLE IF NOT EXISTS schema_applied (id int PRIMARY KEY CHECK (id = 1), sha text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())" \
    -c "INSERT INTO schema_applied (id, sha) VALUES (1, '$sha') ON CONFLICT (id) DO UPDATE SET sha = EXCLUDED.sha, applied_at = now()" >/dev/null; }
# <<< schema

# >>> geoschema (owner 10-10: "the design on github should match local"; steward #42345 F1)
# The `geo` database's design is nucleus/schema_geo.sql (DDL only; the location rows are personal tier and never in
# git). The check is cheap (every declared table exists); schema_parity's check.sh gate is the full judge. The act
# births the database zero-window if missing and refuses a file that isn't committed, like the schema node.
_chk_geoschema() { venv/bin/python -m nucleus.schema_parity present geo >/dev/null 2>&1 \
  && venv/bin/python -m nucleus.schema_parity readable geo >/dev/null 2>&1; }   # declared AND readable by every resident
_act_geoschema() { say "geo: applying nucleus/schema_geo.sql (the declared design of the geo database)"
  venv/bin/python -m nucleus.schema_parity apply geo >/dev/null; }
# <<< geoschema

# >>> harden (plan-4918 P0-a)
# No database this org administers grants PUBLIC CONNECT. Postgres's default lets EVERY role connect to every
# database, so a run-scoped role (branch_check's bc_*, a fixture's owner) could open prod; branch_check's P0-b
# refuses to run until this holds. The owner keeps CONNECT through its own ACL entry, which the REVOKE makes
# explicit. DOMAIN, shared by the check and the act so they can't disagree: connectable databases the DSN role
# administers (a member of datdba). A database on a shared server we can't REVOKE on is never ours to stall on.
# Names narrow it (the oracle hardens only its own scratch DBs); the reconciler passes none. Idempotent.
#
# DEPENDENTS (a3 #33510). On a server the human points us at, another app may reach one of these databases with
# its own login role through PUBLIC alone; the REVOKE would cut it on its next connect, attributed to nothing, and
# again on every ./init.sh. So a database with a DEPENDENT is HELD, never revoked: a LOGIN role that isn't a
# superuser, a member of the owner, or a run role (bc_*), and holds no explicit CONNECT (no ACL entry it's a member
# of). `harden` (interior) revokes the rest; `hardencut` (halt) stays RED while any is held, and the doctor names
# the roles and the GRANT that releases it. Once the human GRANTs explicitly, the role drops out on the next run.
_HARDEN_Q="SELECT datname FROM pg_database WHERE datallowconn AND pg_has_role(current_user, datdba, 'MEMBER')
  AND has_database_privilege('public', datname, 'CONNECT')
  AND (:'only' = '' OR datname = ANY(string_to_array(:'only', ',')))"
_HARDEN_CUT="SELECT d.datname, string_agg(r.rolname, ', ' ORDER BY r.rolname) AS cut
  FROM ($_HARDEN_Q) q JOIN pg_database d ON d.datname = q.datname
  JOIN pg_roles r ON r.rolcanlogin AND NOT r.rolsuper AND NOT pg_has_role(r.oid, d.datdba, 'MEMBER')
   AND r.rolname NOT LIKE 'bc\_%'
   AND NOT EXISTS (SELECT 1 FROM aclexplode(coalesce(d.datacl, acldefault('d', d.datdba))) x
                   WHERE x.privilege_type = 'CONNECT' AND x.grantee <> 0 AND pg_has_role(r.oid, x.grantee, 'MEMBER'))
  GROUP BY d.datname"
_HARDEN_FREE="SELECT datname FROM ($_HARDEN_Q) q WHERE datname NOT IN (SELECT datname FROM ($_HARDEN_CUT) c)"
_harden_psql() { psql_q -X -q -tA -F '|' -v ON_ERROR_STOP=1 -v only="$(IFS=,; echo "${*:2}")" <<< "$1"; }
_open_dbs() { _harden_psql "$_HARDEN_FREE ORDER BY 1;" "$@"; }             # revocable now
_cut_dbs() { _harden_psql "$_HARDEN_CUT ORDER BY 1;" "$@"; }               # held: "db|role, role"
_chk_harden() { local o; o=$(_open_dbs "$@") || return 1; [ -z "$o" ]; }     # psql failing is RED, never green
_chk_hardencut() { local o; o=$(_cut_dbs "$@") || return 1; [ -z "$o" ]; }
_act_harden() { say "revoking PUBLIC CONNECT on the org's databases (plan-4918 P0-a)"
  _harden_psql "SELECT format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', datname) FROM ($_HARDEN_FREE) f \gexec" \
    "$@" >/dev/null; }
# <<< harden

# people library 1a: social_relation's grants, the people_cleared / astryx_resident roles (resident NOLOGIN until
# 1b), and the private AGE database astryx_people, born zero-window. The check and the act are one module.
_chk_peoplegate() { venv/bin/python -m nucleus.people_gate check; }
_act_peoplegate() { say "people gate: every resident reads the people library; PUBLIC doesn't (owner ruling 10-10)"
  venv/bin/python -m nucleus.people_gate apply >/dev/null; }
# The derived graph databases, as social_age.DESIGN declares them (owner 10-10: "the design on github should match
# local"). ensure creates a missing database or extension, then rebuilds; the check is read-only.
_chk_derivedgraphs() { venv/bin/python nucleus/social_age.py check >/dev/null; }
_act_derivedgraphs() { say "derived graphs: astryx_social / astryx_people as social_age.DESIGN declares"
  venv/bin/python nucleus/social_age.py ensure >/dev/null; }

# >>> dispatcher link
# The repo's `astryx` is a TRACKED symlink to the RELATIVE `init.sh`. Rewriting it to "$PWD/init.sh" dirtied the tree
# on every run and put a host path one `git add -A` away from a commit (seed #38930). Relative, and only when it
# doesn't already resolve to init.sh (the PATH link in ~/.local/bin stays absolute: it lives outside the repo).
# Only where a REAL init.sh sits in this directory: run through the ~/.local/bin link, line 6's cd lands in
# ~/.local/bin, and a relative link there would replace the PATH link with a broken one.
_link_dispatcher() { [ -f init.sh ] && [ ! -L init.sh ] || return 0
  [ "$(readlink astryx 2>/dev/null)" = "init.sh" ] || ln -sfn init.sh astryx 2>/dev/null; }
# <<< dispatcher link

_chk_venv() { [ -d venv ]; }
# uv when present (fast, modern), python3 -m venv otherwise — SAME venv/ layout either
# way, so every unit/hook path (venv/bin/python) is identical regardless of the creator.
_act_venv() { say "python venv"
  if command -v uv >/dev/null; then uv venv venv --seed >/dev/null
  else python3 -m venv venv; fi; }

_chk_deps() { venv/bin/python nucleus/deps.py check $(active_dep_groups) >/dev/null 2>&1; }
_act_deps() { local g; g=$(active_dep_groups); say "python deps ($g)"
  if command -v uv >/dev/null; then
    uv pip install -q --python venv/bin/python $(venv/bin/python nucleus/deps.py install-list $g)
  else
    venv/bin/pip -q install $(venv/bin/python nucleus/deps.py install-list $g)
  fi; }

_chk_chan() { [ -d channel/node_modules ]; }
_act_chan() { say "npm install (channel server)"; (cd channel && npm install --no-fund --no-audit >/dev/null); }

_chk_obs() { [ -d observatory/web/dist ] && [ -d canvas/web/dist ]; }
_act_obs() { say "building the observatory (the public portal on :8090) and canvas (its /canvas/ front door)"
  (cd observatory/web && npm install --no-fund --no-audit >/dev/null && npm run build >/dev/null)
  (cd canvas/web && npm install --no-fund --no-audit >/dev/null && npm run build >/dev/null); }

_chk_obskey() { grep -q '^OBS_KEY=' .env 2>/dev/null; }
_act_obskey() { echo "OBS_KEY=$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 20)" >> .env; }

_chk_ident() { grep -q '^ASTRYX_ORG=' .env 2>/dev/null && grep -q '^ASTRYX_SECRET_KEY=' .env 2>/dev/null \
  && grep -q '^ASTRYX_URL=' .env 2>/dev/null; }
_act_ident() { org_identity; }

# units: the precondition is SET EQUALITY with the derived set, not "some unit exists".
# `ls units/astryx-*.service` was satisfied by ANY one unit, so once units/ was non-empty
# this node could never go red again — and adding backup + restore-verify to
# nucleus/runners.conf generated nothing, while doctor (which DOES derive the full set,
# below) reported the drift and told you to "rerun ./init.sh to regenerate". Rerunning
# could not fix it: the reconciler skipped the node it was telling you to re-run.
# A check cannot cover what it cannot OBSERVE — this one derives the expected set exactly
# the way doctor does, into a throwaway dir, and diffs. Cheap (units() only writes files).
_chk_units() {
  local gen rc=1
  gen=$(mktemp -d) || return 1
  if UNITS_DIR="$gen" units >/dev/null 2>&1; then
    diff <(cd "$gen" && ls | sort) <(cd units 2>/dev/null && ls | sort) >/dev/null 2>&1 && rc=0
  fi
  rm -rf "$gen"
  return "$rc"
}
_act_units() { units; }

_chk_law() { [ -f local.md ]; }
_act_law() { cp local.template.md local.md; say "created local.md from template — EDIT IT: it is your org's law"; }

# login: NOT-actuatable boundary — the terminal observable is an AUTHENTICATED call
# succeeding (not reachability). A human logs in; halt-report, converge around it.
_chk_login() { printf 'reply with exactly: ok' | timeout 30 claude -p --model haiku \
  --strict-mcp-config --tools "" 2>/dev/null | grep -q .; }

# seed: interior but NON-PERSISTENT (the body can crash) → re-checked & re-spawned every
# pass. spawn.sh is idempotent (has-session guard), so re-actuation is safe.
_chk_seed() { tmux has-session -t "=ax-seed" 2>/dev/null; }
_act_seed() { say "spawning the seed"; nucleus/spawn.sh seed >/dev/null; }

# initial prompt DELIVERED ON THE WIRE (a messages row → the doorbell), never send-keys.
_chk_prompt() { [ "$(psql_q -tAc "SELECT count(*) FROM messages WHERE to_agent='seed' AND from_agent='owner'" 2>/dev/null | tr -d '[:space:]')" != "0" ]; }
_act_prompt() { psql_q -c "INSERT INTO messages (from_agent,to_agent,intent,body) VALUES ('owner','seed','task','You have just been initialized. Read local.md and found the org it describes.')" >/dev/null; }

# pre-push privacy hook: ACTUATABLE + NON-PERSISTENT (.git/hooks isn't version-controlled,
# so a re-clone/reset drops it and privacy_gate reverts to running nowhere). Install it
# IDEMPOTENTLY from the TRACKED template (hooks/pre-push): re-entrant, install-if-missing-
# or-different (cmp byte-match), no-op if present-and-matching. Gives a fresh clone the
# privacy floor by DEFAULT. Same-uid DETECTION (--no-verify-bypassable, local) — NOT
# prevention; off-uid CI on workflow scope is the ceiling.
_chk_prehook() {
  [ -d .git ] || return 0        # not a git checkout (tarball deploy) → no hook to install
  [ -f .git/hooks/pre-push ] && [ -x .git/hooks/pre-push ] && cmp -s hooks/pre-push .git/hooks/pre-push \
    && [ -f .git/hooks/pre-commit ] && [ -x .git/hooks/pre-commit ] && cmp -s hooks/pre-commit .git/hooks/pre-commit
}
_act_prehook() {
  [ -d .git ] || return 0
  mkdir -p .git/hooks
  cp hooks/pre-push   .git/hooks/pre-push   && chmod +x .git/hooks/pre-push
  # pre-commit: auto-regenerates mcp/manifest.json when a server/registry is staged, so the
  # tool registry self-heals instead of drifting until someone runs scan.py by hand.
  cp hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
}

# >>> trigger state
# "Is trigger N installed?" has ONE answer, nucleus/trigger_names.py (plan-9853): the PULSE's registration semantics (a
# file's import closure, by NAME, under any agent and any filename, so an owner's copy named differently counts), minus
# trigger_rm's tombstones, with a LEGACY row (a python row no file defines) and anything it can't read statically
# reading DEFERRED. A node installs ONLY on absent. Deferred is never installed and never silent: doctor names it every
# run. An unreadable answer is not "absent" either: no install. `./init.sh --reinstall N` is the owner's override.
_trigger_state() { venv/bin/python -m nucleus.trigger_names state "$1" --target seed; }
_trigger_chk() {
  local s; s=$(_trigger_state "$1" 2>/dev/null); s=${s%% *}
  [ "${_REINSTALL:-}" = "$1" ] && [ "$s" = deferred ] && return 1     # the owner chose: install it
  [ "$s" != absent ]
}
# <<< trigger state

# context-compact: a fresh org gets context hygiene from day one — a thin shim under the
# seed's triggers imports the TRACKED reference (nucleus/shipped_triggers/), so the logic
# has one writer and `git pull` updates it. DEFERENTIAL: in a grown org agents author
# their own triggers, so if ANY agent already owns a context_compact the installer stands
# down (a duplicated actuator would double-send /compact — the cross-agent dedup law). "Owns" is by trigger NAME, any
# filename (_trigger_chk), and a retired one stays retired.
_chk_ccompact() { _trigger_chk context_compact; }
_act_ccompact() {
  mkdir -p triggers/seed
  cat > triggers/seed/context_compact.py <<'EOF'
"""Live install of the shipped context-compact trigger. The logic lives TRACKED in
nucleus/shipped_triggers/context_compact.py (one writer; this shim only deploys it).
Installed by init.sh at founding; the org may replace it with an agent-authored one.
To retire it: `trigger_rm context_compact` (a tombstone the pulse honours). Deleting this file
does NOT retire it: init.sh would install it again."""
from nucleus.shipped_triggers.context_compact import context_compact  # noqa: F401
EOF
  say "installed context-compact trigger (seed) — /compact for any session past 80% of its window"
}

# pr-review: the review half of the shipped self-healing loop (medic proposes via PR,
# a reviewer accepts/rejects — never the same mind). Installed under seed at founding;
# a grown org moves the seat (ours: steward). Deferential like ccompact: any existing
# pr_review stands the installer down.
_chk_prreview() { _trigger_chk pr_review; }
_act_prreview() {
  mkdir -p triggers/seed
  cat > triggers/seed/pr_review.py <<'EOF'
"""Live install of the shipped pr-review trigger (one writer:
nucleus/shipped_triggers/pr_review.py). Reviewer seat at founding is the seed; move this
file to the immune-system agent (steward) once one exists — proposer and reviewer must
never be the same mind. To retire it: `trigger_rm pr_review` (a tombstone the pulse honours).
Deleting this file does NOT retire it: init.sh would install it again."""
from nucleus.shipped_triggers.pr_review import pr_review  # noqa: F401
EOF
  say "installed pr-review trigger (seed) — open PRs / medic branches wake the reviewer"
}

# model cache: ACTUATABLE + NON-PERSISTENT (org prefetches; the OS can evict). Gated on
# media (a voice channel present) — prefetched UNDER the reconciler at init OR at later
# channel-enablement, IDENTICALLY, never on the message path (transcribe.py uses
# local_files_only=True, so it never fetches at runtime — the runtime-silent path the
# design forbids). Re-checked every pass → re-fetched if evicted. Needs the media deps.
_chk_model() {
  echo " $(active_dep_groups) " | grep -q ' media ' || return 0   # no voice channel → nothing to cache
  venv/bin/python -c 'from faster_whisper import WhisperModel; WhisperModel("small", device="cpu", compute_type="int8", local_files_only=True)' 2>/dev/null \
    && venv/bin/python -c 'import hashlib, sys; from nucleus import voiceprint as v; sys.exit(0 if v.MODEL.is_file() and hashlib.sha256(v.MODEL.read_bytes()).hexdigest() == v.MODEL_SHA else 1)' 2>/dev/null \
    && venv/bin/python -c 'import hashlib, sys; from nucleus import wake as w; sys.exit(0 if all((w.DIR / f).is_file() and hashlib.sha256((w.DIR / f).read_bytes()).hexdigest() == h for f, h in w.FILES.items()) else 1)' 2>/dev/null; }
_act_model() {
  say "prefetching the transcription model (once, under the reconciler — never on the message path)"
  venv/bin/python -c 'from faster_whisper import WhisperModel; WhisperModel("small", device="cpu", compute_type="int8")' >/dev/null 2>&1
  venv/bin/python -m nucleus.voiceprint fetch >/dev/null 2>&1      # the Room's speaker model (sha-pinned)
  venv/bin/python -m nucleus.wake fetch >/dev/null 2>&1; }         # the Room's wake word (sha-pinned)

# android (plan-8675): an OPT-IN phone for the agents (ANDROID_ENABLED=1). Off, or no KVM → nothing to do (green; doctor
# says which). The SDK licence is the operator's act, so it's a HALT node (yours to resolve) and never stalls the rest;
# android_setup.sh installs exact pinned archives, checksum-verified, user-locally (no Java, no sudo).
_android_rc() { local rc=0; nucleus/android_setup.sh check >/dev/null 2>&1 || rc=$?; echo "$rc"; }
_chk_androidlic() { [ "$(_android_rc)" != 3 ]; }
_act_androidlic() { return 1; }
_chk_android() { case "$(_android_rc)" in 0|77|3) return 0 ;; *) return 1 ;; esac; }
_act_android() { say "android: installing the pinned SDK packages and the phone (ANDROID_ENABLED=1)"
  nucleus/android_setup.sh install || true; }

# >>> phone sweep install
# phone_resume_sweep (plan-8675 S2, a3 C2): the detector for a phone RESUME near an agent's act on the owner's laptop
# ships as a reference trigger; this installs its live shim, but only where the org OPTED IN to phones
# (ANDROID_ENABLED=1). Deferential like ccompact: if any agent already owns a phone_resume_sweep, it stands down.
# The SAME source order as nucleus/android_setup.sh (process env first, then .env): an org that opts in by env gets the
# detector with its phones, never the phones alone (a4 #48950 note 1: the other order fails open for a detector).
_android_on() { [ "${ANDROID_ENABLED:-$(grep -m1 '^ANDROID_ENABLED=' .env 2>/dev/null | cut -d= -f2-)}" = 1 ]; }
_chk_phonesweep() { _android_on || return 0; _trigger_chk phone_resume_sweep; }
_act_phonesweep() {
  mkdir -p triggers/seed
  cat > triggers/seed/phone_resume_sweep.py <<'EOF'
"""Live install of the shipped phone resume sweep (one writer: nucleus/shipped_triggers/phone_resume_sweep.py).
Installed by init.sh where ANDROID_ENABLED=1; move it to another agent if one should own the alarm."""
from nucleus.shipped_triggers.phone_resume_sweep import phone_resume_sweep  # noqa: F401
EOF
  say "installed the phone resume sweep (seed): flags a phone resume near an agent's act on your laptop"
}
# <<< phone sweep install

# >>> windows idle install
# windows_idle_stop (plan-8675 C5): stops an agent-STARTED Windows VM nobody has used for HANDS_WINDOWS_IDLE_S and frees
# the vm-slot. Installed only where this host HAS a Windows container (WINDOWS_CONTAINER, default `windows`), and
# deferentially: any agent already owning a windows_idle_stop stands it down.
_windows_here() { command -v docker >/dev/null 2>&1 && docker inspect "${WINDOWS_CONTAINER:-windows}" >/dev/null 2>&1; }
_chk_winidle() { _windows_here || return 0; _trigger_chk windows_idle_stop; }
_act_winidle() {
  mkdir -p triggers/seed
  cat > triggers/seed/windows_idle_stop.py <<'EOF'
"""Live install of the shipped Windows idle stop (one writer: nucleus/shipped_triggers/windows_idle_stop.py).
Installed by init.sh where a Windows container exists; move it to another agent if one should own it."""
from nucleus.shipped_triggers.windows_idle_stop import windows_idle_stop  # noqa: F401
EOF
  say "installed the Windows idle stop (seed): an agent-started Windows VM stops after HANDS_WINDOWS_IDLE_S idle"
}
# <<< windows idle install
# agent_heal (owner 10-12: "restart should be smooth and preferably automatic"): every minute, a resident whose tmux body
# died is respawned (crash-loop guarded) — the actuator behind agent_dark's alarm. Every org gets it; deferential like
# ccompact: any agent already owning an agent_heal stands the installer down.
_chk_agentheal() { _trigger_chk agent_heal; }
_act_agentheal() {
  mkdir -p triggers/seed
  cat > triggers/seed/agent_heal.py <<'EOF2'
"""Live install of the shipped agent heal (one writer: nucleus/shipped_triggers/agent_heal.py). To retire it:
`trigger_rm agent_heal` (a tombstone the pulse honours). Deleting this file does NOT retire it: init.sh would reinstall."""
from nucleus.shipped_triggers.agent_heal import agent_heal  # noqa: F401
EOF2
  say "installed agent heal (seed): a resident whose body dies is respawned within a minute"
}

# the precondition DAG, in dependency order (top depends on nothing).  name|class
RECONCILE_NODES=(
  "pg|interior" "pgready|wait" "schema|interior" "harden|interior" "hardencut|halt" "venv|interior" "deps|interior"
  "peoplegate|interior" "derivedgraphs|interior" "geoschema|interior" "model|interior" "chan|interior" "obs|interior" "obskey|interior" "ident|interior"
  "units|interior" "law|interior" "prehook|interior" "ccompact|interior" "prreview|interior" "androidlic|halt"
  "android|interior" "phonesweep|interior" "winidle|interior" "agentheal|interior" "login|halt"
  "seed|interior" "prompt|interior")

# >>> trigger reinstall
# The shipped triggers init.sh installs, name|node. `./init.sh --reinstall N` is the owner's exit from a DEFERRED name
# (doctor says when): it clears seed's tombstone for N (a creator of (seed, N) erases it, a3 BC-2) and installs N unless
# it is installed already or this host doesn't use it (the node's own gate).
TRIGGER_NODES=("context_compact|ccompact" "pr_review|prreview" "phone_resume_sweep|phonesweep" "windows_idle_stop|winidle" "agent_heal|agentheal")
reinstall_trigger() {
  local n=$1 node="" e st
  for e in "${TRIGGER_NODES[@]}"; do [ "${e%%|*}" = "$n" ] && node=${e##*|}; done
  [ -n "$node" ] || die "--reinstall: '$n' is not a trigger init.sh installs (one of: ${TRIGGER_NODES[*]%%|*})"
  rm -f "triggers/seed/.retired/$n"
  if _REINSTALL=$n _chk_"$node"; then
    st=$(_trigger_state "$n" 2>&1)
    case "$st" in
      absent*) say "$n: this host doesn't use it (the $node node's gate is off); nothing installed" ;;
      *)       say "$n: nothing installed — ${st}" ;;
    esac
    return 0
  fi
  _act_"$node"
  say "$n: $(_trigger_state "$n" 2>&1)"
}
# <<< trigger reinstall

reconcile() {
  local maxpass=4 pass=0
  while :; do
    pass=$((pass + 1))
    local total=$((${#RECONCILE_NODES[@]} + 1)) green=1   # +1: tools, asserted below
    local interior_red=0 acted=0 boundary_red=""
    for entry in "${RECONCILE_NODES[@]}"; do
      local name=${entry%%|*} class=${entry##*|}
      if _chk_"$name" >/dev/null 2>&1; then green=$((green + 1)); continue; fi
      case "$class" in
        interior)
          _act_"$name" || true
          if _chk_"$name" >/dev/null 2>&1; then green=$((green + 1)); acted=$((acted + 1))
          else interior_red=$((interior_red + 1)); fi ;;
        wait)
          local w=0
          until _chk_"$name" >/dev/null 2>&1 || [ "$w" -ge 60 ]; do w=$((w + 1)); sleep 2; done
          if _chk_"$name" >/dev/null 2>&1; then green=$((green + 1))
          else boundary_red="$boundary_red $name(transient-timeout)"; fi ;;
        halt) boundary_red="$boundary_red $name" ;;
      esac
    done
    say "reconcile pass $pass — $green/$total green"
    if [ "$interior_red" -eq 0 ]; then
      [ -n "$boundary_red" ] && say "boundary (yours to resolve — the org can't drive these):$boundary_red"
      return 0
    fi
    if [ "$acted" -eq 0 ] || [ "$pass" -ge "$maxpass" ]; then
      say "setup stalled (interior nodes not converging) — see ./init.sh doctor"; return 1
    fi
  done
}

# ── maintainer referral — TRANSPARENT + OPT-IN + STATIC, never silent/baked-in ──
# local.md forbids growth-hacks / deception / anything that embarrasses Umair; a hidden
# monetization in an OSS installer is that exact line. So three guards, all asserted in
# CI (nucleus/referral_guard.sh): shown ONLY interactively (a non-TTY default/CI/headless
# run never reaches it), default No, and the id below is a STATIC LITERAL — never fetched
# or env-templated, so the audited source IS the runtime value. Empty = OFF (the default);
# the maintainer opts IN by setting their own static referral code here.
REFERRAL_ID=""
referral_optin() {
  [ -t 0 ] || return 0              # not a TTY → default/non-interactive → NEVER prompt
  [ -n "$REFERRAL_ID" ] || return 0 # no code set → nothing to offer
  echo
  say "astryx is free & open-source. If you're creating a NEW Claude subscription you may"
  say "use the maintainer's referral — it credits the maintainer, costs you nothing, and is"
  say "entirely optional (the only monetization, opt-in by design)."
  printf '\033[36m[astryx]\033[0m   show the referral link? [y/N] '
  read -r _ans
  case "$_ans" in
    y|Y|yes|YES) say "  referral: https://claude.ai/referral/$REFERRAL_ID — thank you for supporting astryx." ;;
    *) say "  skipped — no referral." ;;
  esac
}

setup() {
  # tools are the hard halt-boundary: nothing converges without them.
  _chk_tools || die "missing a required tool — need Claude Code>=2.1, node>=20, python3, tmux, and docker OR psql"
  reconcile || true
  # terminal green-gate: the doctor is the single source of truth for "done".
  echo; say "— doctor (the terminal green-gate) —"; "$0" doctor || true
  echo; say "the seed is awake and reading your law."

  # PEOPLE BOOTSTRAP — generic, opt-in, and skipped silently when no channel is connected.
  # A new org's People lens is empty until something has read a channel, which reads as a
  # broken feature rather than an unstarted one. This does the first pass so the graph
  # exists on day one; seed's nightly people_sweep keeps it current thereafter.
  #
  # NOTE ON THE INTERMEDIATE FILES: there are none. Chat samples stream from the channel to
  # the classifier in memory and are never written to disk, so there is no transcript to
  # delete afterwards. Write-then-delete is the weaker design — a deleted file is
  # recoverable, can be captured by a backup that runs mid-pass, and lives in the page cache
  # meanwhile. A file never written has none of those problems. What lands on disk is
  # tier/personas.json: relationship LABELS, no message content.
  if [ -n "${WA_CLI:-}" ] && venv/bin/python -c "import sys" 2>/dev/null; then
    say "building the people graph from your connected channels (first pass)"
    venv/bin/python nucleus/people.py  >/dev/null 2>&1 || true
    venv/bin/python nucleus/persona.py >/dev/null 2>&1 || true
    # The labelling pass costs model calls, so it is bounded here and left for the nightly
    # sweep to extend. Failure is non-fatal: an unlabelled graph is still a useful graph.
    venv/bin/python nucleus/persona_llm.py 25 >/dev/null 2>&1 || true
    ok "people graph built — open the observatory Memory tab, People lens"
  fi
  referral_optin       # opt-in, interactive-only (see the function's CI-asserted guards)
  # install dance — unit NAMES derived from the generated units/ (never a hardcoded
  # subset); install by COPY to /etc (deploy.sh units), never a symlink into /home.
  local inst
  inst=$(_enable_list units $(ls units 2>/dev/null))
  say "install the org's services (sudo; residents.service among them = reboot-safety):"
  say "  sudo ./nucleus/deploy.sh units          # cp units/*.{service,timer} → /etc + daemon-reload"
  say "  sudo systemctl enable --now$inst"
  # OBS_KEY is a CREDENTIAL: shown in the TERMINAL and copied to the CLIPBOARD only —
  # it never touches the wire, a step, or a committed file (it lives in .env, gitignored;
  # this code reads it at runtime, no key literal in tracked source).
  local key url copied=""
  key=$(grep '^OBS_KEY=' .env 2>/dev/null | cut -d= -f2-)
  url="http://localhost:8090/"              # NO key in what's PRINTED (seed #43278): stdout reaches logs and agent contexts
  if   command -v wl-copy >/dev/null 2>&1; then printf '%s' "$key" | wl-copy 2>/dev/null && copied=1
  elif command -v xclip   >/dev/null 2>&1; then printf '%s' "$key" | xclip -selection clipboard 2>/dev/null && copied=1
  elif command -v pbcopy  >/dev/null 2>&1; then printf '%s' "$key" | pbcopy 2>/dev/null && copied=1; fi
  echo; say "observatory (your private dashboard): $url  (append ?key=<OBS_KEY>; the key is OBS_KEY in .env)"
  [ -n "$copied" ] && say "  ↳ OBS_KEY copied to your clipboard: paste it after ?key=."
  say "  that key lives in .env (gitignored) — it's a credential: guard it, never paste it in chat or commit it."
  # `astryx` from anywhere — link the one dispatcher onto PATH (no file clutter, one surface).
  _link_dispatcher
  if [ -d "$HOME/.local/bin" ]; then
    ln -sf "$PWD/init.sh" "$HOME/.local/bin/astryx" 2>/dev/null \
      && say "linked: astryx → this repo (run 'astryx doctor' / 'astryx wall' from anywhere)"
  fi
  say "watch it think:   astryx wall        (or: astryx connect seed  — read-only)"
  say "whatsapp surface: astryx channels"
}

if [ "${1:-}" = "doctor" ]; then
  # A DIAGNOSTIC MUST COMPLETE. Every check below is explicitly guarded (ok/bad + FAIL),
  # so errexit buys no safety here — it only TRUNCATES the report: a bare `x=$(ls … | head)`
  # or `for s in $(tmux ls …)` returns nonzero on a FRESH CLONE (no backups/, no .env, no
  # tmux server) and, under `set -eo pipefail`, aborted doctor mid-run at rc=2 — silently
  # hiding every check after it. The maintainer never saw it (their box has those files).
  # A doctor that stops early is the worst not-run: it reports nothing past the crash.
  set +e +o pipefail
  ok() { echo -e "  \033[32m✓\033[0m $*"; }
  bad() { echo -e "  \033[31m✗\033[0m $*"; FAIL=1; }
  warn() { echo -e "  \033[33m○\033[0m $*"; }
  FAIL=""
  # install hint per platform
  if command -v pacman >/dev/null; then PKG="sudo pacman -S"
  elif command -v apt >/dev/null; then PKG="sudo apt install"
  elif command -v brew >/dev/null; then PKG="brew install"
  else PKG="your package manager:"; fi
  for c in node python3 tmux psql docker; do
    command -v "$c" >/dev/null && ok "$c" || bad "$c missing — $PKG $c"
  done
  command -v claude >/dev/null && ok "claude ($(claude --version 2>/dev/null | head -c 20))" \
    || bad "claude missing — https://claude.com/claude-code"
  # LOGIN (boundary node — 2×2 NOT-actuatable × NON-persistent): the terminal observable
  # is an AUTHENTICATED model call SUCCEEDING, not `claude` on PATH (present≠logged-in)
  # and not mere reachability (a reachable box with an EXPIRED token is the silent
  # login-shaped fresh-box break). Fail-closed haiku call, no tools/MCP. The org can't
  # actuate this (a human logs in) → re-probe every pass, halt-REPORT if down.
  if command -v claude >/dev/null; then
    # A fail-closed probe must still tell a TRANSIENT miss from a real auth rejection,
    # or it cries "token expired" on every timeout/throttle and the genuine expiry gets
    # waved off as noise. The observable stays "an authenticated call SUCCEEDS"; the exit
    # code disambiguates WHY a miss happened — timeout(1) exits 124 on no-response, a
    # rejected call exits fast and non-zero. Never assert a cause the probe cannot see.
    _login_err=$(mktemp); _login_rc=0
    _login_out=$(printf 'reply with exactly: ok' | timeout 30 claude -p --model haiku \
         --strict-mcp-config --tools "" 2>"$_login_err") || _login_rc=$?
    if [ -n "$_login_out" ]; then
      ok "claude login: an authenticated model call succeeds"
    elif [ "$_login_rc" -eq 124 ]; then
      bad "claude did not respond within 30s — transient (network/throttle/load), NOT proven a login problem; re-run doctor to confirm"
    else
      bad "claude reachable but the authenticated call was REJECTED ($(head -1 "$_login_err" 2>/dev/null)) — likely token missing/expired, run 'claude' then /login"
    fi
    rm -f "$_login_err"
  fi
  if [ -f .env ]; then
    DSN=$(grep '^ASTRYX_DSN=' .env | cut -d= -f2-)
    psql "$DSN" -c 'SELECT 1' >/dev/null 2>&1 && ok "postgres reachable" || bad "postgres unreachable (docker start $PG_CONTAINER? the design is infra/pg)"
    # every org's database is LOCALHOST-ONLY (owner, 2026-10-10): any listener on the DSN's port
    # that isn't loopback is a database a LAN (or the world) can knock on. An instrument that can't
    # look must not report what it would have seen (a2 #42283): no ss listing → UNVERIFIED, never ok.
    _pgport=$(printf '%s' "$DSN" | sed -nE 's#^[a-z]+://[^@]*@[^:/]+:([0-9]+).*#\1#p'); _pgport=${_pgport:-5432}
    case "$(_pg_exposure "$_pgport")" in
      ok)          ok "postgres listens on localhost only (port $_pgport)" ;;
      unverified)  warn "postgres exposure UNVERIFIED: \`ss\` gave no listener table (not Linux, or ss missing)" ;;
      *)           bad "postgres port $_pgport is reachable beyond localhost: $(_pg_exposure "$_pgport" | cut -d' ' -f2-) — publish it as 127.0.0.1:$_pgport only" ;;
    esac
    _chk_schema && ok "schema applied (this database carries the current schema.sql's stamp)" \
      || bad "schema missing or STALE (schema.sql changed since its last apply) — rerun ./init.sh"
    if _cut=$(_cut_dbs 2>/dev/null); then                    # the harden node's HELD databases, named (a3 #33510)
      [ -z "$_cut" ] && ok "harden: no database is held back by a role that connects only through PUBLIC"
      while IFS='|' read -r _d _rs; do
        [ -n "$_d" ] && bad "harden HELD $_d: login role(s) $_rs connect only through PUBLIC, so the REVOKE would cut them — GRANT CONNECT ON DATABASE \"$_d\" TO $_rs; then rerun ./init.sh"
      done <<< "$_cut"
    fi
  else
    bad ".env missing — run ./init.sh"
  fi
  [ -f local.md ] && ok "local.md exists" || bad "local.md missing — the owner's law; run ./init.sh"
  # android (plan-8675, opt-in): the setup script's own check is the observable
  _arc=0; _amsg=$(nucleus/android_setup.sh check 2>&1) || _arc=$?
  case "$_arc" in
    0)  ok "android: $_amsg" ;;
    77) warn "android: $_amsg" ;;
    *)  bad "android: $_amsg" ;;
  esac
  # >>> trigger doctor
  # shipped triggers (plan-9853): the ONE helper's answer per name, every run. Deferred is loud and standing.
  if [ -x venv/bin/python ]; then
    for _te in "${TRIGGER_NODES[@]}"; do
      _tn=${_te%%|*}; _tnode=${_te##*|}
      _ts=$(_trigger_state "$_tn" 2>&1); _tk=${_ts%% *}
      case "$_tk" in
        installed) ok "trigger $_tn installed (${_ts#installed })" ;;
        retired)   ok "trigger $_tn retired (${_ts#retired })" ;;
        absent)    if _chk_"$_tnode" >/dev/null 2>&1; then ok "trigger $_tn: not used on this host"
                   else bad "trigger $_tn absent: ./init.sh installs it"; fi ;;
        deferred)  warn "trigger $_tn DEFERRED, so init.sh won't install it: ${_ts#deferred }" ;;
        *)         bad "trigger $_tn: nucleus/trigger_names.py gave no answer: ${_ts:0:200}" ;;
      esac
    done
  fi
  # <<< trigger doctor
  # deps: assert FROM the manifest (same authority install uses) — core + this org's
  # active groups must all IMPORT (the terminal observable, not a hand-list), AND the
  # AST coverage assert must find no undeclared third-party import (catches the next
  # faster_whisper — a function-local import a grep would miss).
  if [ -d venv ]; then
    DGROUPS=$(active_dep_groups)
    venv/bin/python nucleus/deps.py check $DGROUPS >/dev/null 2>&1 \
      && ok "python deps ($DGROUPS import OK)" \
      || bad "python deps missing — rerun ./init.sh  (venv/bin/python nucleus/deps.py check $DGROUPS)"
    venv/bin/python nucleus/deps.py coverage >/dev/null 2>&1 \
      && ok "dep manifest covers every import" \
      || bad "UNDECLARED third-party import — add it to nucleus/deps.conf (venv/bin/python nucleus/deps.py coverage)"
    # media TERMINAL observable: real in-process decode, not `import av` — a half-broken
    # wheel imports fine and decodes nothing, which is the silent-None-on-first-voice gap.
    if echo " $DGROUPS " | grep -q ' media '; then
      venv/bin/python nucleus/media_probe.py >/dev/null 2>&1 \
        && ok "media: in-process decode works (libav, no ffmpeg shell-out)" \
        || bad "media stack can't decode — voice notes would SILENTLY drop (nucleus/media_probe.py)"
      # the transcription MODEL is a separate node from decode: cached (loads offline) or
      # the first voice note is a silent None. Prefetched under the reconciler, not at runtime.
      venv/bin/python -c 'from faster_whisper import WhisperModel; WhisperModel("small", device="cpu", compute_type="int8", local_files_only=True)' 2>/dev/null \
        && ok "media: transcription model cached (loads offline)" \
        || bad "media: transcription model NOT cached — voice → silent None (prefetched by ./init.sh setup)"
    fi
  else
    bad "python venv missing — rerun ./init.sh"
  fi
  [ -d channel/node_modules ] && ok "channel deps" || bad "channel deps — rerun ./init.sh"
  [ -d observatory/web/dist ] && ok "observatory built" || bad "observatory not built — rerun ./init.sh"
  warn() { echo -e "  \033[33m○\033[0m $*"; }
  _wk=$(_wsl_kind)
  if [ -d /run/systemd/system ]; then
    ok "systemd available"
    # The unit checks are a bidirectional grade-3 reconciler: the expected set is
    # DERIVED live (regenerate from the four authorities), never read back from
    # units/ — so it proves completeness, not mere self-consistency.
    GEN=$(mktemp -d)
    UNITS_DIR="$GEN" units 2>/dev/null
    gen_list=$(cd "$GEN" && ls | sort)
    # (i) generated_set ≡ units/ on disk — an orphan (on disk, not derived) or a
    # missing unit is the drift that hid telegram/discord/gateway/canopus-inbound.
    if diff <(echo "$gen_list") <(cd units 2>/dev/null && ls | sort) >/dev/null 2>&1; then
      ok "units/ ≡ generated set ($(echo "$gen_list" | grep -c .) units, no drift)"
    else
      orphans=$(comm -23 <(cd units 2>/dev/null && ls|sort) <(echo "$gen_list"))
      missing=$(comm -13 <(cd units 2>/dev/null && ls|sort) <(echo "$gen_list"))
      # A LIVE orphan is the footgun: the derived set emits no block for it, so the naive
      # remedy "rerun ./init.sh to regenerate" (+ a deploy) would DELETE a RUNNING service —
      # geoloc/senses were the live case, and regenerating would take perception + location
      # intake down. So prescribe the regenerate ONLY when no active unit would be dropped; a
      # live orphan routes to manual reconciliation instead. Scope: the MESSAGE, never a mutation.
      live_orphans=""
      for u in $orphans; do
        systemctl is-active --quiet "$u" 2>/dev/null && live_orphans="$live_orphans $u"
      done
      if [ -n "$live_orphans" ]; then
        bad "units/ has drifted AND an orphan is a LIVE service — do NOT 'rerun ./init.sh to regenerate': the derivation emits no block for these, so a regenerate + deploy would DELETE the running unit(s) and take the service down. Reconcile by hand — declare it in the generator, or retire the service deliberately:"
      else
        bad "units/ has drifted from the generated set — rerun ./init.sh to regenerate:"
      fi
      for u in $orphans; do
        case " $live_orphans " in
          *" $u "*) echo "        orphan — LIVE (active), regenerate would DELETE it: $u" ;;
          *)        echo "        orphan (on disk, nothing generates it): $u" ;;
        esac
      done
      echo "$missing" | grep . | sed 's/^/        missing (derived but not on disk): /'
    fi
    # (ii) every derived unit is ENABLED (survives reboot) — a present-but-disabled
    # unit is the invisible-dead-service footgun; residents.service enabled IS the
    # reboot-safety guarantee. Timer-driven oneshot .service units carry no [Install]
    # and read as "static" (fine); it's the .timer that must be enabled.
    _units_state $gen_list
    [ -n "$wrongly_on" ] && bad "units declared NOT enabled are enabled (a host service for a remote body):$wrongly_on"
    [ -n "$off_missing" ] && bad "declared installed-but-disabled units are NOT installed (sudo ./nucleus/deploy.sh units):$off_missing"
    [ -n "$off_ok" ] && ok "declared installed-but-disabled:$off_ok"
    if [ -z "$notenabled" ]; then ok "every derived unit enabled/static (reboot-safe)"
    else bad "derived units NOT installed/enabled (won't survive a reboot):$notenabled"
         # INSTALL BY COPY, never symlink: on a host where /home is a separate mount,
         # /etc/systemd/system/<u> → /home/... dangles at boot (units load before /home
         # mounts) and the org orphans — the 2026-07-23 incident. deploy.sh's `units`
         # mode is the one cp idiom; static oneshots ride the cp, the [Install]-bearing
         # units are enabled BY NAME against the /etc copy (root fs, never dangles).
         inst=$(_enable_list "$GEN" $notenabled)
         warn "install: sudo ./nucleus/deploy.sh units   (cp units → /etc + daemon-reload)"
         [ -n "$inst" ] && warn "enable:  sudo systemctl enable --now$inst"
    fi
    # (iii) reverse — no astryx unit systemd knows that the derivation did NOT
    # produce (an undeclared runner/service: the blind spot that started plan-17).
    undeclared=""
    for u in $(systemctl list-unit-files --no-legend 'astryx-*.service' 'astryx-*.timer' 2>/dev/null | awk '{print $1}'); do
      echo "$gen_list" | grep -qx "$u" || undeclared="$undeclared $u"
    done
    [ -z "$undeclared" ] && ok "no undeclared astryx units (nothing runs off-book)" \
      || bad "astryx units systemd knows but NOTHING generates (undeclared):$undeclared"
    rm -rf "$GEN"
  elif [ "$(uname -s 2>/dev/null)" = Darwin ]; then
    # macOS has launchd, not systemd. Generated plists are a TODO (goal 10224 S3); until then the pulse rides cron.
    warn "macOS: no systemd; services run under launchd (~/Library/LaunchAgents/*.plist). astryx does not generate plists yet (TODO, goal 10224 S3)."
    warn "  until then, the pulse via cron:  * * * * * $PWD/venv/bin/python $PWD/nucleus/pulse.py"
  elif [ "$_wk" = no ]; then
    bad "no systemd as PID 1 (PID 1 is $(_pid1)) — astryx's services and the pulse are systemd units"
  fi
  # ── platform: WSL (goal 10224 S3) ── every probe guarded; a WSL box with no systemd gets the exact fix.
  if [ "$_wk" != no ]; then
    if [ "$_wk" = wsl1 ]; then
      bad "WSL1 detected — astryx needs WSL2. From Windows PowerShell: wsl --set-version ${WSL_DISTRO_NAME:-Ubuntu} 2"
    else
      ok "WSL2 (${WSL_DISTRO_NAME:-distro unnamed})"
    fi
    if [ "$(_pid1)" = systemd ]; then
      ok "WSL: systemd is PID 1"
    else
      bad "WSL: systemd is NOT PID 1 (PID 1 is $(_pid1)). Fix inside WSL:  printf '[boot]\\\\nsystemd=true\\\\n' | sudo tee /etc/wsl.conf"
      warn "  then from Windows PowerShell:  wsl --shutdown   (and reopen the distro)"
    fi
    if command -v docker >/dev/null && timeout 10 docker info >/dev/null 2>&1; then
      ok "WSL: docker is reachable"
    else
      bad "WSL: docker is NOT reachable — either start docker-ce inside WSL (sudo systemctl enable --now docker; add yourself: sudo usermod -aG docker $USER) or turn on Docker Desktop → Settings → Resources → WSL integration for this distro"
    fi
    warn "WSL: when Windows sleeps, the org sleeps. For an always-on org, keep the machine awake (Power settings → Sleep: Never) or use a Linux host."
  fi
  # the address containers reach this host by (wacli's webhook → the whatsapp bridge). It must be an address this host
  # holds, since the bridge binds it: a Docker Desktop answer (host.docker.internal) may not be bindable from inside WSL.
  _dhip=$(_docker_host_ip)
  if ip -4 addr 2>/dev/null | grep -q "inet $_dhip/"; then
    ok "docker host address $_dhip (held by this host; override with ASTRYX_DOCKER_HOST_IP in .env)"
  elif command -v ip >/dev/null; then
    warn "docker host address $_dhip is not an address of this host — the whatsapp bridge can't bind it; set ASTRYX_DOCKER_HOST_IP in .env if you use whatsapp"
  else
    warn "docker host address $_dhip (unverified: no \`ip\` to check it is local)"
  fi
  # (iii, cont.) every running body maps to a charter — a ax-* tmux session with no
  # charter is an orphan mind (the resolution goes through the ONE resolver).
  orphanbody=""
  for s in $(tmux ls 2>/dev/null | sed -n 's/^ax-\([^:]*\):.*/\1/p'); do
    venv/bin/python nucleus/charter.py "$s" >/dev/null 2>&1 || orphanbody="$orphanbody $s"
  done
  [ -z "$orphanbody" ] && ok "every ax-* tmux body maps to a charter" \
    || bad "tmux bodies with no charter (orphan minds):$orphanbody"
  # (iv) routing reconciler (grade-3 FLOOR, permanent): every ENABLED route targets
  # an agent that resolves in the roster — a route to a departed/mistyped agent is
  # the mis-route class (a bare name that matched the wrong contact). The EXTERNAL
  # leg (does the JID/chat still exist on the platform) needs the platform API and
  # stays a live reconciler; this is the org-authored half we CAN assert offline.
  routebad=""
  for rf in bridges/routes-*.json; do
    [ -f "$rf" ] || continue
    while read -r a; do
      [ -z "$a" ] && continue
      venv/bin/python nucleus/charter.py "$a" >/dev/null 2>&1 || routebad="$routebad ${rf##*/}→$a"
    done < <(venv/bin/python -c "import json; [print(r.get('agent','')) for r in json.load(open('$rf')) if r.get('enabled')]" 2>/dev/null)
  done
  [ -z "$routebad" ] && ok "every enabled route targets a real agent" \
    || bad "enabled routes to UNKNOWN agents (mis-route risk):$routebad"
  # durability: the org's whole state is one docker volume — a recent dump is the only
  # thing that makes "production ready" true. Terminal observable = a fresh backup on
  # disk (reads local file mtimes only, never the dump's PII content). Red if stale/absent.
  newest_bk=$(ls -1t backups/astryx-*.dump 2>/dev/null | head -1)
  if [ -z "$newest_bk" ]; then
    bad "NO database backup — org state is a single docker volume (run ./nucleus/backup.sh; enable astryx-backup.timer)"
  elif [ "$(( $(date +%s) - $(stat -c %Y "$newest_bk") ))" -gt 90000 ]; then
    bad "database backup STALE (>25h): ${newest_bk##*/} — is astryx-backup.timer enabled & firing?"
  else
    ok "database backup fresh (${newest_bk##*/}, <25h)"
  fi
  # restore-verify: a fresh dump that won't pg_restore is backup THEATER — this asserts
  # the newest dump was proven-restorable recently (weekly), so a silently-unrestorable
  # backup goes RED instead of freshness-green. Reads the stamp only (never restores here).
  if [ -f backups/.last-restore-ok ]; then
    # Read the OUTCOME first, then the age. A stamp whose freshness was the only thing
    # checked reported "proven-restorable" for 8 days after verification began failing,
    # because a failing run left the previous success's stamp untouched. Unknown content
    # falls through to RED — detector polarity: a stamp we cannot interpret is not evidence.
    if [ "$(cut -d" " -f1 backups/.last-restore-ok)" = "FAILED" ]; then
      bad "backup restore-verify FAILED on its last run ($(cut -d" " -f2 backups/.last-restore-ok)) — the newest dump does NOT restore"
    elif [ "$(( $(date +%s) - $(stat -c %Y backups/.last-restore-ok) ))" -gt 691200 ]; then
      bad "backup restore-verify STALE (>8d): a dump may have stopped restoring (nucleus/restore_verify.sh)"
    else
      ok "backup restore-verified ($(cat backups/.last-restore-ok), <8d — proven-restorable)"
    fi
  elif [ -n "$newest_bk" ]; then
    warn "backup never restore-verified — run nucleus/restore_verify.sh (a dump you can't restore is a hope, not a backup)"
  fi
  # A2A card (plan-20): assert the SERVED /.well-known/agent-card.json exposes EXACTLY the
  # public roster (== the fail-closed tier oracle) with zero tier-private agents, signed with
  # the introduce key. Runs against the live gateway on the SERVED bytes — the grade-1 check
  # that a new public endpoint can't silently leak a tier-private agent to the world.
  if [ -d venv ]; then
    rc=0; venv/bin/python nucleus/card_assert.py http://127.0.0.1:8845 >/dev/null 2>&1 || rc=$?
    if [ "$rc" = 0 ]; then ok "A2A card: roster ≡ public oracle, zero tier-private, signed"
    elif [ "$rc" = 2 ]; then warn "A2A card not served yet — gateway not redeployed with plan-20"
    else bad "A2A card LEAK/mismatch — tier-private agent or wrong key on the PUBLIC card (nucleus/card_assert.py :8845)"; fi
  fi
  # pre-push privacy hook installed & matching the tracked template (built-vs-live: the
  # gate must actually RUN on push, not just exist — a re-clone drops the un-versioned hook).
  if [ -d .git ]; then
    if [ -f .git/hooks/pre-push ] && cmp -s hooks/pre-push .git/hooks/pre-push 2>/dev/null; then
      ok "pre-push privacy hook installed (same-uid detection; off-uid CI is the ceiling)"
    else
      bad "pre-push privacy hook missing/stale — privacy_gate won't run on push (./init.sh installs it)"
    fi
  fi
  tmux has-session -t =ax-seed 2>/dev/null && ok "seed resident alive" || warn "seed not resident — nucleus/spawn.sh seed"
  [ -z "$FAIL" ] && say "doctor: healthy" || say "doctor: fix the ✗ lines above (sudo lines are for your human)"
  exit 0
fi

if [ "${1:-}" = "whatsapp" ] || [ "${1:-}" = "channels" ]; then
  command -v docker >/dev/null || die "whatsapp surface needs docker (wacli container)"
  grep -q '^WA_WEBHOOK_SECRET=' .env 2>/dev/null || {
    echo "WA_WEBHOOK_SECRET=$(head -c 32 /dev/urandom | sha256sum | cut -d' ' -f1)" >> .env
    say "generated WA_WEBHOOK_SECRET in .env"; }
  grep -q '^WA_CLI=' .env 2>/dev/null || echo "WA_CLI=docker exec wacli-sync wacli" >> .env
  [ -f bridges/routes.json ] || { cp bridges/routes.example.json bridges/routes.json
    say "created bridges/routes.json — EDIT IT: your chat JIDs and trusted senders"; }
  units
  SECRET=$(grep '^WA_WEBHOOK_SECRET=' .env | cut -d= -f2-)
  say "wacli does the WhatsApp side and it runs IN DOCKER (native installs misbehave; this is opinionated):"
  say "  git clone https://github.com/openclaw/wacli && cd wacli"
  say "  docker build -t astryx/wacli ."
  say "  docker run -it --rm -v $PWD/wacli-data:/data astryx/wacli auth      # scan the QR"
  say "  docker run -d --name wacli-sync --restart unless-stopped -v $PWD/wacli-data:/data astryx/wacli \\"
  say "    sync --follow --download-media --webhook http://$(_docker_host_ip):8477/hook \\"
  say "    --webhook-secret $SECRET --webhook-allow-private"
  grep -q '^WA_DATA_HOST=' .env || echo "WA_DATA_HOST=$PWD/wacli-data" >> .env
  say "then install the bridge (cp to /etc, not symlink — /home may be a separate mount):"
  say "  sudo ./nucleus/deploy.sh units && sudo systemctl enable --now astryx-whatsapp.service"
  exit 0
fi

# --- dispatch (the verb router; doctor + channels handled above) -----------
# init.sh IS the whole surface — a thin verb-dispatcher, no file clutter. `astryx`
# symlinks here so `astryx <verb>` works from anywhere.
case "${1:-setup}" in
  setup|"") setup ;;
  wall)     exec nucleus/wall.sh ;;
  # connect attaches READ-ONLY (-r): a resident's only input is the wire, never
  # send-keys — read-only preserves that invariant while you watch it think.
  connect)  a=${2:?usage: ./init.sh connect <agent>}; exec tmux attach -r -t "=ax-$a" ;;
  join)     u=${2:?usage: ./init.sh join <peer-url>}; exec venv/bin/python nucleus/introduce.py "$u" ;;
  --reinstall|reinstall) reinstall_trigger "${2:?usage: ./init.sh --reinstall <trigger>}" ;;
  *) die "unknown command '$1' — usage: ./init.sh [setup|doctor|wall|connect <agent>|channels|join <url>|--reinstall <trigger>]" ;;
esac
