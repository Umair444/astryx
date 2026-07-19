#!/usr/bin/env bash
# ASTRYX nucleus·spawn — bring a resident to life (or resume its life). v0.
# Body = interactive claude in tmux (tmux is a CONTAINER, not a nervous system: the only
# inputs a resident ever receives are channel events. Boot dialogs are the sole send-keys
# exception, and only until the CLI ships non-interactive acceptance.)
set -euo pipefail
ROOT=/home/umair/astryx
AGENT=${1:?usage: spawn.sh <agent>}
CHARTER="$ROOT/agents/$AGENT.md"
[ -f "$CHARTER" ] || { echo "no charter: $CHARTER"; exit 1; }
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
  'nightly review: read your own day (query_steps yourself), ask what you should have done better and what tool, trigger, or skill you lack, then take ONE concrete growth action: build it, file it as a goal, or propose it to seed. The org grows because you do.')
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
      { "type": "command", "command": "$ROOT/venv/bin/python $ROOT/hooks/step.py", "timeout": 10 } ] } ]
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

tmux new-session -d -s "$SESS" -c "$HOME_D"
# --strict-mcp-config + explicit --mcp-config: a resident's world is EXACTLY its
# own .mcp.json, nothing inherited. (strict alone ignores even the project file —
# that deafened the whole org once; the explicit flag is load-bearing.)
tmux send-keys -t "=$SESS:" "claude ${RESUME}--model $MODEL --permission-mode bypassPermissions --strict-mcp-config --mcp-config $HOME_D/.mcp.json --dangerously-load-development-channels server:astryx" Enter

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
echo "$AGENT resident (tmux:$SESS, boot=$([ -n "$RESUME" ] && echo resumed || echo fresh))"
