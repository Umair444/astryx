#!/usr/bin/env bash
# ASTRYX nucleus·spawn — bring a resident to life (or resume its life). v0.
# Body = interactive claude in tmux (tmux is a CONTAINER, not a nervous system: the only
# inputs a resident ever receives are channel events. Boot dialogs are the sole send-keys
# exception, and only until the CLI ships non-interactive acceptance.)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# ROOT is the CODE; ORGH is the ORG (its HOME: .env, local.md, agents/, homes/, tier/), plan-11324 S3a #58435 item 5.
# One org (no host registry, src/astryx/orgs.py): ORGH is ROOT and every line below is what it was. Several orgs: the
# HOME comes from the ONE resolver (astryx.paths: ASTRYX_HOME naming a REGISTERED home, or its marker; never the
# checkout), the agent is found in THAT org's agents/, and the pane's environment is BUILT (astryx.orgenv, BC-S3).
MULTI=""
PY="$ROOT/venv/bin/python"
"$PY" "$ROOT/src/astryx/orgs.py" multi && MULTI=1 || { rc=$?; [ "$rc" = 1 ] || exit 1; }
ORGH="$ROOT"
if [ -n "$MULTI" ]; then
  ORGH=$("$PY" -c 'import sys; sys.path.insert(0, sys.argv[1] + "/src")
from astryx import paths; print(paths.home())' "$ROOT") || { echo "spawn: no registered org HOME (set ASTRYX_HOME)"; exit 1; }
fi
. "$ROOT/scripts/org_tmux.sh"   # `tmux` is THIS org's server (S3b): the default socket on one org, -L ax-<org> on several
# RENDER MODE: `spawn.sh --render <agent> <outdir>` writes the home files a spawn would write
# (CLAUDE.md, .mcp.json, .claude/settings.json) into <outdir>, then exits BEFORE any side
# effect: no DB write, no tmux, no claude, no residency refusal. It is THIS script, one code
# path with each side effect guarded by $RENDER, never a copy (a copy is a second authority for
# what a home contains). Tests and builds that change the genome check the REAL generation
# through it (seed, plan-4227). The output can hold the same secrets a home does (runtime_env
# splices a provider token into settings.json), so <outdir> must lie OUTSIDE the repo (homes/
# is gitignored; nothing else is), and it must NOT EXIST: render creates it fresh, 0700 under
# umask 077. An existing dir would keep its own permissions (mkdir -p changes nothing), and the
# three writes truncate what's there, so `--render seed ~` would overwrite the owner's own
# ~/.claude/settings.json (abstractor-4, plan-4227 review #4).
RENDER=""
if [ "${1:-}" = "--render" ]; then
  RENDER=1
  AGENT=${2:?usage: spawn.sh --render <agent> <outdir>}
  OUT=${3:?usage: spawn.sh --render <agent> <outdir>}
  umask 077
  OUT="$(realpath -m "$OUT")"                  # canonical BEFORE anything is created
  case "$OUT/" in
    "$(realpath -m "$ROOT")"/*|"$(realpath -m "$ORGH")"/*) echo "spawn --render: <outdir> must be outside the repo and the org's HOME ($OUT)"; exit 1;;
  esac
  [ -e "$OUT" ] && { echo "spawn --render: <outdir> must not exist; render creates it fresh ($OUT)"; exit 1; }
  mkdir "$OUT"
else
  AGENT=${1:?usage: spawn.sh <agent>   |   spawn.sh --render <agent> <outdir>}
fi
# A charter is agents/<name>.md at any depth: composites are directories, a
# self-form agent is agents/<name>/<name>.md, members live inside composite dirs
# (nesting allowed). The stem is the canonical name and a GLOBAL key (plan-2 §4):
# a duplicated stem is a corrupted registry and refuses to spawn — the tree is
# the registry, so the collision must be resolved in the tree, not raced past.
# Tombstoned charters (## Tombstone, owner-authored) hold their name forever but
# never spawn. Examples and reserved names are never charters.
# Resolution goes through the ONE shared resolver (src/astryx/core/charter.py): any depth,
# examples and .git excluded, a duplicated stem REFUSED (the two-seed class). The
# observatory and init.sh resolve through the same module, so the rule can never
# drift between a shell copy and a python copy — it had (the observatory silently
# took the first match on a dup stem while this refused).
CHARTER=$(ASTRYX_HOME="$ORGH" "$ROOT/venv/bin/python" "$ROOT/src/astryx/core/charter.py" "$AGENT") || exit 1
grep -q '^## Tombstone' "$CHARTER" && { echo "'$AGENT' is tombstoned — the name rests"; exit 1; }
# AGENT TYPE (charter `Type:` line, resolved through the ONE resolver so shell and python
# never disagree; default resident). A STATIONED agent has no body: it is a stateless
# `claude -p` API invoked per request via src/astryx/core/station.py — spawn.sh has nothing to
# embody, so it says so and exits 0 (a skip, not a failure). This REINSTATES the stationed
# pattern retired in plan-17: the retirement was right for vega (a public voice belongs to
# a full resident, served by a contained conjure), but wrong as a blanket ban — an
# app-facing, high-throughput, thinking-off API worker is a legitimate KIND of agent, and
# denying it a lifecycle just meant re-implementing one ad hoc (the vega conjure was that).
# The type is the honest place for the distinction; containment still lives in station.py's
# fail-closed flags (--tools "" + --strict-mcp-config), never in withholding a body.
ATYPE=$(ASTRYX_HOME="$ORGH" "$ROOT/venv/bin/python" "$ROOT/src/astryx/core/charter.py" "$AGENT" --type 2>/dev/null || echo resident)
if [ "$ATYPE" = "stationed" ]; then
  echo "'$AGENT' is stationed — a stateless claude -p API, not a resident. Invoke it with src/astryx/core/station.py; there is no body to spawn."
  exit 0
fi
# A charter the Claude Code plugin's /astryx:join wrote (its line `Plugin: joined`) belongs to a person's own
# session on the wire: that session IS its body. Embodying it here (spawn-all, or agent_dark's FIX line) would put
# a second ear on its doorbell, and a resident body never takes the plugin's one-body lock, so the lock can't
# refuse it. Skip, like stationed. Oracle: tests/test_plugin_hooks.py.
if grep -q '^Plugin: joined$' "$CHARTER"; then
  echo "'$AGENT' joined from a Claude Code session (the ASTRYX plugin); that session is its body, so there is nothing to spawn."
  exit 0
fi
# One agent, ONE body: if a channel server already runs under this identity
# anywhere (e.g. the founder CLI outside tmux), a second spawn would race it
# on the same doorbell — messages split between bodies invisibly. That was
# the two-seed incident of 2026-07-25 (a full day of "lost" owner messages);
# this guard retires the class.
# (ASTRYX_AGENT is ENV, invisible to pgrep -f — read /proc/<pid>/environ)
if [ -z "$RENDER" ] && ! tmux has-session -t "=ax-$AGENT" 2>/dev/null; then
  for pid in $(pgrep -f 'channel/server.mjs' 2>/dev/null); do
    # several orgs: an agent NAME is per org (S3b), so only a body of THIS org's agent (its HOME carried) counts
    if tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -qx "ASTRYX_AGENT=$AGENT" \
       && { [ -z "$MULTI" ] || tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -qxF "ASTRYX_HOME=$ORGH"; }; then
      echo "'$AGENT' already has a live body outside tmux (channel server pid $pid) — refusing a second one"
      exit 1
    fi
  done
fi
SESS="ax-$AGENT"
HOME_D="$ORGH/homes/$AGENT"
[ -n "$RENDER" ] && HOME_D="$OUT"
if [ -n "$MULTI" ]; then NODE=$("$PY" "$ROOT/src/astryx/config.py" get ASTRYX_NODE); NODE=${NODE:-$(command -v node || true)}
else NODE=${ASTRYX_NODE:-$(command -v node || true)}   # org-home: one org only, exactly as before (several orgs: the line above)
fi
# A version manager (mise, nvm) puts node in the user's interactive PATH only: systemd units (astryx-residents at
# boot) and sudo see a bare PATH. 10-12: a reboot spawned 1 of 17 residents for exactly this. Ask the manager.
if [ -z "$NODE" ]; then
  for m in mise "$HOME/.local/bin/mise" /usr/bin/mise; do
    command -v "$m" >/dev/null 2>&1 && NODE=$(cd "$ROOT" && "$m" which node 2>/dev/null) && [ -x "$NODE" ] && break
    NODE=""
  done
fi
[ -z "$NODE" ] && [ -x "$HOME/.local/share/mise/shims/node" ] && NODE="$HOME/.local/share/mise/shims/node"
[ -z "$NODE" ] && NODE=$(ls -d "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null | sort -V | tail -1)
[ -n "$NODE" ] || { echo "spawn: node not found on PATH or via mise/nvm (set ASTRYX_NODE)"; exit 1; }

# Default heartbeat: every agent wakes on its own rhythm (charter line
# "Heartbeat: <cron>", default daily 09:00) and retunes it with trigger_set.
# Runs before the residency check so existing residents gain it too.
HB=$(grep -m1 '^Heartbeat:' "$CHARTER" | cut -d: -f2- | xargs || true)
DSN=$("$PY" "$ROOT/src/astryx/config.py" dsn --file)
[ -z "$RENDER" ] && psql "$DSN" -qc "INSERT INTO triggers (agent, name, schedule, kind)
  VALUES ('$AGENT', 'heartbeat', '${HB:-0 9 * * *}', 'heartbeat')
  ON CONFLICT (agent, name) DO NOTHING" 2>/dev/null || true

# Standard nightly self-review: the growth law made mechanical. Staggered by a
# hash of the name (02:00-03:59 window) so the org does not wake all at once.
CK=$(printf '%s' "$AGENT" | cksum | cut -d' ' -f1)
[ -z "$RENDER" ] && psql "$DSN" -qc "INSERT INTO triggers (agent, name, schedule, kind, note)
  VALUES ('$AGENT', 'night-review', '$((CK % 60)) $((2 + CK % 2)) * * *', 'heartbeat',
  'nightly review: FIRST read the org''s shipping log — query_thread(''org-news'') — new capabilities land daily and change what is possible for you. THEN read your own day (query_steps yourself), ask what you should have done better and what tool, trigger, or skill you lack, and take ONE concrete growth action: build it, file it as a goal, or propose it to seed (dedup against org-news first — what you lack may already exist). This review is also YOURS: informed by what the org has become, you are free to reshape who you are — personality, interests, boundaries, any SHELL section of your charter — via self_edit, exactly as far as the understanding moves you. The org grows because you do.')
  ON CONFLICT (agent, name) DO NOTHING" 2>/dev/null || true

if [ -z "$RENDER" ] && tmux has-session -t "=$SESS" 2>/dev/null; then echo "$AGENT already resident"; exit 0; fi

mkdir -p "$HOME_D/.claude"
# genome → body: charter + law are the auto-loaded context (no boot prompt needed)
# the law is the ORG's (a2 BC-S2): HOME/local.md, and a missing one FAILS the spawn (cat exits non-zero under set -e),
# never another org's law as a fallback
{ cat "$CHARTER"; echo; echo "## The law (local.md)"; cat "$ORGH/local.md"; } > "$HOME_D/CLAUDE.md"

# grants: a charter line "Grants: gmail, ..." maps to extra MCP servers in this
# agent's world. With --strict-mcp-config the .mcp.json IS the capability list.
EXTRA=""
for g in $(grep -m1 '^Grants:' "$CHARTER" 2>/dev/null | cut -d: -f2- | tr ',' ' '); do
  case "$g" in
    gmail) EXTRA="$EXTRA,
  \"gmail\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/gmail/server.py\"] }";;
    compose) EXTRA="$EXTRA,
  \"compose\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/compose/server.py\"] }";;
    imagegen) EXTRA="$EXTRA,
  \"imagegen\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/imagegen/server.py\"] }";;
    growbot) EXTRA="$EXTRA,
  \"growbot\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/growbot/server.py\"] }";;
    org) EXTRA="$EXTRA,
  \"org\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/org/server.py\"] }";;
    memory) EXTRA="$EXTRA,
  \"memory\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/memory/server.py\"] }";;
    jobs) EXTRA="$EXTRA,
  \"jobs\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/jobs/server.py\"] }";;
    docpdf) EXTRA="$EXTRA,
  \"docpdf\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/docpdf/server.py\"] }";;
    contacts) EXTRA="$EXTRA,
  \"contacts\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/contacts/server.py\"] }";;
    channels) EXTRA="$EXTRA,
  \"channels\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/channels/server.py\"] }";;
    # browser: official @playwright/mcp (adopt-mature-OSS; the one sanctioned Node
    # MCP). Headless, system chromium, persistent per-agent profile so logins the
    # owner establishes survive respawns — the agent never sees a password.
    # env = keyring reach: chromium cookies are v11-encrypted against the user's
    # secret-service, so headless chromium must reach the session bus to decrypt
    # them — without these two keys every owner-established login reads as logged
    # OUT (cookie present, undecryptable). And since this file REGENERATES
    # .mcp.json each spawn, a hand-fix in the home is clobbered on the next
    # respawn: the fix lives here or nowhere. Derived from uid, never hardcoded.
    browser) EXTRA="$EXTRA,
  \"browser\": { \"command\": \"$(dirname "$NODE")/npx\", \"args\": [\"-y\", \"@playwright/mcp@latest\",
    \"--headless\", \"--executable-path\", \"/usr/bin/chromium\",
    \"--user-data-dir\", \"$HOME_D/.browser-profile\"],
    \"env\": { \"XDG_RUNTIME_DIR\": \"/run/user/$(id -u)\",
      \"DBUS_SESSION_BUS_ADDRESS\": \"unix:path=/run/user/$(id -u)/bus\" } }";;
    *) echo "warning: unknown grant '$g' in $CHARTER" >&2;;
  esac
done

# hands = the agent's own desktop on this machine (plan-7862, owner 2026-10-10: "it should use my
# laptop like i can do — nothing container… we should trust these agents"). Every RESIDENT gets it,
# like the door: residents are trusted (owner ruling), and a resident already holds Bash on this
# machine, so its own desktop adds sight and a cursor, not reach. NOT given to STATIONED agents.
# tools = the registry door (goal 4227 S4). Every RESIDENT gets it, not a grant: it's flat rent
# (two tools however many the org grows), and no new capability, because a resident already
# holds Bash and the door runs registered scripts only, never a granted MCP server. It is
# deliberately NOT given to STATIONED agents (src/astryx/core/station.py, --tools "" fail-closed), where
# it WOULD be a new execution capability. tests/test_spawn_wiring.py pins both halves.
# influence = who_should_i_ask (plan-11324, seed #58432): its OWN server, every RESIDENT, like hands. Not behind the
# memory grant (that one stays `ask` only): the asker is every resident, and the reply is ABOUT the asker, so
# ASTRYX_AGENT is written into its env HERE, never inherited (this file is the source of truth for who asks; an
# inherited value is whatever launched claude). STATIONED agents never reach this heredoc (the Type: stationed exit
# above), so they never get it. tests/test_spawn_wiring.py pins both halves, and that `Grants: memory` adds memory only.
# phone = an Android phone under the agent's hands (plan-8675), only where the org OPTED IN (ANDROID_ENABLED=1 in
# .env; scripts/android_setup.sh installs it). Every resident then gets it, like hands. Its server is a facade over
# a pinned upstream: it reaches 13 reviewed tools and builds the upstream's environment itself.
PHONE=""
if [ "$("$PY" "$ROOT/src/astryx/config.py" get ANDROID_ENABLED --file 2>/dev/null)" = 1 ]; then
  PHONE=",
  \"phone\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/phone/server.py\"],
    \"env\": { \"ASTRYX_AGENT\": \"$AGENT\" } }"
fi
cat > "$HOME_D/.mcp.json" <<EOF
{ "mcpServers": { "astryx": {
    "command": "$NODE",
    "args": ["$ROOT/channel/server.mjs"],
    "env": { "ASTRYX_AGENT": "$AGENT", "ASTRYX_HOME": "$ORGH" }
},
  "tools": { "command": "$ROOT/venv/bin/python", "args": ["$ROOT/mcp/tools/server.py"] },
  "hands": { "command": "$ROOT/venv/bin/python", "args": ["$ROOT/mcp/hands/server.py"],
    "env": { "ASTRYX_AGENT": "$AGENT", "XDG_RUNTIME_DIR": "/run/user/$(id -u)",
      "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/$(id -u)/bus" } },
  "influence": { "command": "$ROOT/venv/bin/python", "args": ["$ROOT/mcp/influence/server.py"],
    "env": { "ASTRYX_AGENT": "$AGENT" } }$PHONE$EXTRA } }
EOF

# think: charter line "Think: off" zeroes extended thinking for reflex-class
# agents whose craft is a fast small reply (growbot: a wake becomes motion in
# seconds, not a deliberation). Absent line = thinking stays on (the default).
THINK=$(grep -m1 '^Think:' "$CHARTER" | cut -d: -f2- | xargs || true)
TENV=""
[ "$THINK" = "off" ] && TENV=", \"MAX_THINKING_TOKENS\": \"0\""

# per-agent provider/auth override (runtime.json, gitignored; observatory-written). Emits the
# extra env keys — ANTHROPIC_BASE_URL/AUTH_TOKEN, the opus/sonnet/haiku model map, effort — to
# splice into THIS agent's settings.json env block, or nothing when the agent has no entry (it
# then falls through to the org's ambient default: "default = settings.json"). settings.json's
# env WINS over process env, so this per-home file is the ONE correct seam; a shell export
# before launch would be silently ignored. Token stays in .env; only its NAME is in runtime.json.
RENV=$("$ROOT/venv/bin/python" "$ROOT/src/astryx/core/runtime_env.py" "$AGENT") || RENV=""

# plan-9139 S1d (S0 D4, seed #45086): a TIER member's auto-memory goes to its own dir under tier/, never the shared
# one, set in THIS template because every spawn rewrites settings.json (so --resume reads it too). The label comes from
# the door's own reader over THIS tree's agents/; a label that can't be read (no charter, a malformed grant: it raises)
# is private here as well. Nothing goes in env: CLAUDE_CODE_DISABLE_AUTO_MEMORY=0 there would force memory back ON.
LBL=$("$ROOT/venv/bin/python" -c 'import json, sys; from pathlib import Path; sys.path.insert(0, sys.argv[1] + "/src")
from astryx.security.release import label_of
print(json.dumps(sorted(label_of(sys.argv[2], Path(sys.argv[3]) / "agents"))))' "$ROOT" "$AGENT" "$ORGH" 2>/dev/null) \
  && LRC=0 || LRC=$?
MEMDIR=""
if [ "$LRC" -ne 0 ] || [ "$LBL" != "[]" ]; then
  MEMDIR=",
  \"autoMemoryDirectory\": \"$ORGH/tier/memory/$AGENT\""
  [ -z "$RENDER" ] && install -d -m 700 "$ORGH/tier/memory/$AGENT"
fi

cat > "$HOME_D/.claude/settings.json" <<EOF
{
  "env": { "ASTRYX_AGENT": "$AGENT", "ASTRYX_HOME": "$ORGH"$TENV$RENV },
  "hooks": {
    "PreToolUse": [ { "matcher": "", "hooks": [
      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/step.py", "timeout": 5 } ] } ],
    "PostToolUse": [ { "matcher": "", "hooks": [
      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/step.py", "timeout": 5 } ] } ],
    "Stop": [ { "hooks": [
      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/step.py", "timeout": 10 } ] } ],
    "UserPromptSubmit": [ { "hooks": [
      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/usage.py", "timeout": 5 } ] },
      { "hooks": [
      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/nudge.py", "timeout": 3 } ] } ]
  }$MEMDIR
}
EOF

# RENDER stops here: everything below reads the transcript/DB and starts the body.
if [ -n "$RENDER" ]; then echo "$AGENT rendered into $HOME_D (no side effects)"; exit 0; fi

# resume-first: a resident's life survives its process (GENESIS lesson, kept)
RESUME=""
TDIR="$HOME/.claude/projects/$(echo "$HOME_D" | tr / -)"
newest=$(ls -t "$TDIR"/*.jsonl 2>/dev/null | grep -v '/agent-' | head -1 || true)
# The session ID comes from the DB: step.py records every turn's session_id in `turns`,
# so the newest row IS this agent's current life (owner's design, 2026-09-29). The file
# must still exist — refresh.sh sets transcripts aside for a deliberate fresh boot, and a
# missing file means fresh, not a resume into nothing. turns is written at Stop and has
# known gaps (a compacted session can end with no turn row), so a strictly NEWER
# transcript on disk wins and says so. DB unreachable/empty → the newest transcript.
latest=""
sid=$(psql "$DSN" -tAc "SELECT session_id FROM turns WHERE agent='$AGENT' AND session_id IS NOT NULL ORDER BY ended_at DESC NULLS LAST LIMIT 1" 2>/dev/null || true)
if [ -n "$sid" ] && [ -f "$TDIR/$sid.jsonl" ]; then
  latest="$TDIR/$sid.jsonl"
  if [ -n "$newest" ] && [ "$newest" != "$latest" ] && [ "$newest" -nt "$latest" ]; then
    echo "  note: newer transcript than turns.session_id ($sid) — resuming $(basename "$newest" .jsonl)"
    latest="$newest"
  fi
else
  # DB empty, OR its session_id has no transcript (a non-persisted headless run under
  # this home still logs a turn — abstractor-4 booted fresh over a 13MB life this way,
  # 2026-10-09). A deliberate fresh boot needs no carve-out here: refresh.sh moves ALL
  # transcripts aside, so $newest is empty too.
  latest="$newest"
fi
# --resume <id> — NOT --continue, whose own "most recent conversation in this
# directory" heuristic can land on the wrong session. And no age gate:
# how long an outage lasted must not decide whether an agent keeps its memory (a >72h
# gate wiped every resident's context after a multi-day host outage, 2026-09-29).
# Deliberate fresh boots stay refresh.sh's job: it sets transcripts aside first, so
# $latest is empty here and the agent boots fresh. And no SIZE gate either: a resident
# never dies — it compacts and goes on (owner ruling 2026-10-09; a 10MB gate booted the
# seed fresh over a 48MB life after a 9-day outage). Size is compaction's problem, not
# a reason to forget.
if [ -n "$latest" ]; then RESUME="--resume $(basename "$latest" .jsonl) "; fi

# model: charter line "Model: haiku|sonnet|opus" (default opus — owner's call;
# philosophers pin haiku in their charters, idle residents cost nothing anyway)
MODEL=$(grep -m1 '^Model:' "$CHARTER" | cut -d: -f2- | xargs || true)
MODEL=${MODEL:-opus}

# permissions: charter line "Permissions: relay" runs the resident WITHOUT bypass —
# every gated tool call opens a real approval prompt, which the channel server
# relays to the owner's chat ("yes <id>" / "no <id>", first answer wins; see
# claude/channel/permission in server.mjs). Default remains bypassPermissions:
# the full-trust fleet is the owner's ratified baseline, relay is per-charter.
PERM=$(grep -m1 '^Permissions:' "$CHARTER" | cut -d: -f2- | xargs || true)
PERMFLAG="--permission-mode bypassPermissions"
# must be EXPLICIT default, not merely omitted: the owner's user-level settings
# set defaultMode=bypassPermissions, and an absent flag inherits that
[ "$PERM" = "relay" ] && PERMFLAG="--permission-mode default"

if [ -n "$MULTI" ]; then
  # BUILT, never inherited (a3 BC-S3): `-e` can only add names, so the pane's command is the builder, which execs a
  # shell that reads no rc file. The pane's environ = the PASS classes of data/org_env.json + this org's home class.
  tmux new-session -d -s "$SESS" -c "$HOME_D" -- "$PY" "$ROOT/src/astryx/orgenv.py" exec --home "$ORGH" --agent "$AGENT" -- \
    bash --norc --noprofile
else
  tmux new-session -d -s "$SESS" -c "$HOME_D" -e "ASTRYX_HOME=$ROOT"
fi
# --strict-mcp-config + explicit --mcp-config: a resident's world is EXACTLY its
# own .mcp.json, nothing inherited. (strict alone ignores even the project file —
# that deafened the whole org once; the explicit flag is load-bearing.)
# ASTRYX_CLI: the harness is swappable — any CLI that speaks the same flags (claude,
# a fork, a wrapper that maps them). The org is agents-on-terminals, not a framework.
CLI=${ASTRYX_CLI:-claude}
# --disallowedTools AskUserQuestion: a resident lives in a headless tmux pane no human
# watches, and AskUserQuestion is elicitation-class — it renders a terminal picker that
# BLOCKS on stdin and cannot be relayed to a channel, so an agent that calls it LATCHES
# its own body until someone opens the pane (cost the seed ~6h once). Deny it org-wide;
# agents ask the owner through the wire (a channel poll), never a local picker.
tmux send-keys -t "=$SESS:" "$CLI ${RESUME}--model $MODEL $PERMFLAG --disallowedTools AskUserQuestion --strict-mcp-config --mcp-config $HOME_D/.mcp.json --dangerously-load-development-channels server:astryx" Enter

# boot-dialog drain (research-preview channel confirmation + any first-run dialogs)
for i in $(seq 1 30); do
  sleep 2
  pane=$(tmux capture-pane -t "=$SESS:" -p 2>/dev/null || true)
  if echo "$pane" | grep -qE '❯ 1\.|Do you want|Yes, I accept'; then
    tmux send-keys -t "=$SESS:" "1" ; sleep 1; tmux send-keys -t "=$SESS:" Enter
  elif echo "$pane" | grep -qE '^\s*❯\s*$|bypass permissions'; then
    break
  fi
done
BOOT=$([ -n "$RESUME" ] && echo resumed || echo fresh)
# boot marker: a queryable session-start row (steps.kind='boot') so health patrols can
# compute session AGE. The philosophers' send path degrades on long CONTINUOUS sessions;
# the preventative clean-restart keys on now()-last_boot. One cheap row per spawn.
psql "$DSN" -qc "INSERT INTO steps (agent, kind, content) VALUES ('$AGENT', 'boot', 'session start (boot=$BOOT)')" 2>/dev/null || true
echo "$AGENT resident (tmux:$SESS, boot=$BOOT)"
