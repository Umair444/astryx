#!/usr/bin/env bash
# ASTRYX nucleus·spawn — bring a resident to life (or resume its life). v0.
# Body = interactive claude in tmux (tmux is a CONTAINER, not a nervous system: the only
# inputs a resident ever receives are channel events. Boot dialogs are the sole send-keys
# exception, and only until the CLI ships non-interactive acceptance.)
set -euo pipefail
ROOT=/home/umair/astryx
AGENT=${1:?usage: spawn.sh <agent>}
# A charter is agents/<name>.md at any depth: composites are directories, a
# self-form agent is agents/<name>/<name>.md, members live inside composite dirs
# (nesting allowed). The stem is the canonical name and a GLOBAL key (plan-2 §4):
# a duplicated stem is a corrupted registry and refuses to spawn — the tree is
# the registry, so the collision must be resolved in the tree, not raced past.
# Tombstoned charters (## Tombstone, owner-authored) hold their name forever but
# never spawn. Examples and reserved names are never charters.
# Resolution goes through the ONE shared resolver (nucleus/charter.py): any depth,
# examples and .git excluded, a duplicated stem REFUSED (the two-seed class). The
# observatory and init.sh resolve through the same module, so the rule can never
# drift between a shell copy and a python copy — it had (the observatory silently
# took the first match on a dup stem while this refused).
CHARTER=$("$ROOT/venv/bin/python" "$ROOT/nucleus/charter.py" "$AGENT") || exit 1
grep -q '^## Tombstone' "$CHARTER" && { echo "'$AGENT' is tombstoned — the name rests"; exit 1; }
# AGENT TYPE (charter `Type:` line, resolved through the ONE resolver so shell and python
# never disagree; default resident). A STATIONED agent has no body: it is a stateless
# `claude -p` API invoked per request via nucleus/station.py — spawn.sh has nothing to
# embody, so it says so and exits 0 (a skip, not a failure). This REINSTATES the stationed
# pattern retired in plan-17: the retirement was right for vega (a public voice belongs to
# a full resident, served by a contained conjure), but wrong as a blanket ban — an
# app-facing, high-throughput, thinking-off API worker is a legitimate KIND of agent, and
# denying it a lifecycle just meant re-implementing one ad hoc (the vega conjure was that).
# The type is the honest place for the distinction; containment still lives in station.py's
# fail-closed flags (--tools "" + --strict-mcp-config), never in withholding a body.
ATYPE=$("$ROOT/venv/bin/python" "$ROOT/nucleus/charter.py" "$AGENT" --type 2>/dev/null || echo resident)
if [ "$ATYPE" = "stationed" ]; then
  echo "'$AGENT' is stationed — a stateless claude -p API, not a resident. Invoke it with nucleus/station.py; there is no body to spawn."
  exit 0
fi
# One agent, ONE body: if a channel server already runs under this identity
# anywhere (e.g. the founder CLI outside tmux), a second spawn would race it
# on the same doorbell — messages split between bodies invisibly. That was
# the two-seed incident of 2026-07-25 (a full day of "lost" owner messages);
# this guard retires the class.
# (ASTRYX_AGENT is ENV, invisible to pgrep -f — read /proc/<pid>/environ)
if ! tmux has-session -t "=ax-$AGENT" 2>/dev/null; then
  for pid in $(pgrep -f 'channel/server.mjs' 2>/dev/null); do
    if tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -qx "ASTRYX_AGENT=$AGENT"; then
      echo "'$AGENT' already has a live body outside tmux (channel server pid $pid) — refusing a second one"
      exit 1
    fi
  done
fi
SESS="ax-$AGENT"
HOME_D="$ROOT/homes/$AGENT"
NODE=/home/umair/.local/share/mise/installs/node/26.2.0/bin/node

# Default heartbeat: every agent wakes on its own rhythm (charter line
# "Heartbeat: <cron>", default daily 09:00) and retunes it with trigger_set.
# Runs before the residency check so existing residents gain it too.
HB=$(grep -m1 '^Heartbeat:' "$CHARTER" | cut -d: -f2- | xargs || true)
DSN=$(grep '^ASTRYX_DSN=' "$ROOT/.env" | cut -d= -f2-)
psql "$DSN" -qc "INSERT INTO triggers (agent, name, schedule, kind)
  VALUES ('$AGENT', 'heartbeat', '${HB:-0 9 * * *}', 'heartbeat')
  ON CONFLICT (agent, name) DO NOTHING" 2>/dev/null || true

# Standard nightly self-review: the growth law made mechanical. Staggered by a
# hash of the name (02:00-03:59 window) so the org does not wake all at once.
CK=$(printf '%s' "$AGENT" | cksum | cut -d' ' -f1)
psql "$DSN" -qc "INSERT INTO triggers (agent, name, schedule, kind, note)
  VALUES ('$AGENT', 'night-review', '$((CK % 60)) $((2 + CK % 2)) * * *', 'heartbeat',
  'nightly review: FIRST read the org''s shipping log — query_thread(''org-news'') — new capabilities land daily and change what is possible for you. THEN read your own day (query_steps yourself), ask what you should have done better and what tool, trigger, or skill you lack, and take ONE concrete growth action: build it, file it as a goal, or propose it to seed (dedup against org-news first — what you lack may already exist). This review is also YOURS: informed by what the org has become, you are free to reshape who you are — personality, interests, boundaries, any SHELL section of your charter — via self_edit, exactly as far as the understanding moves you. The org grows because you do.')
  ON CONFLICT (agent, name) DO NOTHING" 2>/dev/null || true

if tmux has-session -t "=$SESS" 2>/dev/null; then echo "$AGENT already resident"; exit 0; fi

mkdir -p "$HOME_D/.claude"
# genome → body: charter + law are the auto-loaded context (no boot prompt needed)
{ cat "$CHARTER"; echo; echo "## The law (local.md)"; cat "$ROOT/local.md"; } > "$HOME_D/CLAUDE.md"

# grants: a charter line "Grants: geoloc, ..." maps to extra MCP servers in this
# agent's world. With --strict-mcp-config the .mcp.json IS the capability list.
EXTRA=""
for g in $(grep -m1 '^Grants:' "$CHARTER" 2>/dev/null | cut -d: -f2- | tr ',' ' '); do
  case "$g" in
    geoloc) EXTRA="$EXTRA,
  \"geoloc\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/geoloc/server.py\"] }";;
    gmail) EXTRA="$EXTRA,
  \"gmail\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/gmail/server.py\"] }";;
    compose) EXTRA="$EXTRA,
  \"compose\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/compose/server.py\"] }";;
    contacts) EXTRA="$EXTRA,
  \"contacts\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/contacts/server.py\"] }";;
    channels) EXTRA="$EXTRA,
  \"channels\": { \"command\": \"$ROOT/venv/bin/python\", \"args\": [\"$ROOT/mcp/channels/server.py\"] }";;
    # browser: official @playwright/mcp (adopt-mature-OSS; the one sanctioned Node
    # MCP). Headless, system chromium, persistent per-agent profile so logins the
    # owner establishes survive respawns — the agent never sees a password.
    browser) EXTRA="$EXTRA,
  \"browser\": { \"command\": \"$(dirname "$NODE")/npx\", \"args\": [\"-y\", \"@playwright/mcp@latest\",
    \"--headless\", \"--executable-path\", \"/usr/bin/chromium\",
    \"--user-data-dir\", \"$HOME_D/.browser-profile\"] }";;
    *) echo "warning: unknown grant '$g' in $CHARTER" >&2;;
  esac
done

cat > "$HOME_D/.mcp.json" <<EOF
{ "mcpServers": { "astryx": {
    "command": "$NODE",
    "args": ["$ROOT/channel/server.mjs"],
    "env": { "ASTRYX_AGENT": "$AGENT" }
}$EXTRA } }
EOF

cat > "$HOME_D/.claude/settings.json" <<EOF
{
  "env": { "ASTRYX_AGENT": "$AGENT" },
  "hooks": {
    "PreToolUse": [ { "matcher": "", "hooks": [
      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/step.py", "timeout": 5 } ] } ],
    "PostToolUse": [ { "matcher": "", "hooks": [
      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/step.py", "timeout": 5 } ] } ],
    "Stop": [ { "hooks": [
      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/step.py", "timeout": 10 } ] } ],
    "UserPromptSubmit": [ { "hooks": [
      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/usage.py", "timeout": 5 } ] } ]
  }
}
EOF

# resume-first: a resident's life survives its process (GENESIS lesson, kept)
RESUME=""
TDIR="$HOME/.claude/projects/$(echo "$HOME_D" | tr / -)"
latest=$(ls -t "$TDIR"/*.jsonl 2>/dev/null | grep -v '/agent-' | head -1 || true)
if [ -n "$latest" ]; then
  age=$(( $(date +%s) - $(stat -c %Y "$latest") )); size=$(stat -c %s "$latest")
  if [ "$age" -lt 259200 ] && [ "$size" -lt 10485760 ]; then RESUME="--continue "; fi
fi

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

tmux new-session -d -s "$SESS" -c "$HOME_D"
# --strict-mcp-config + explicit --mcp-config: a resident's world is EXACTLY its
# own .mcp.json, nothing inherited. (strict alone ignores even the project file —
# that deafened the whole org once; the explicit flag is load-bearing.)
tmux send-keys -t "=$SESS:" "claude ${RESUME}--model $MODEL $PERMFLAG --strict-mcp-config --mcp-config $HOME_D/.mcp.json --dangerously-load-development-channels server:astryx" Enter

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
