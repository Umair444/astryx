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

if tmux has-session -t "=$SESS" 2>/dev/null; then echo "$AGENT already resident"; exit 0; fi

mkdir -p "$HOME_D/.claude"
# genome → body: charter + law are the auto-loaded context (no boot prompt needed)
{ cat "$CHARTER"; echo; echo "## The law (local.md)"; cat "$ROOT/local.md"; } > "$HOME_D/CLAUDE.md"

cat > "$HOME_D/.mcp.json" <<EOF
{ "mcpServers": { "astryx": {
    "command": "$NODE",
    "args": ["$ROOT/channel/server.mjs"],
    "env": { "ASTRYX_AGENT": "$AGENT" }
} } }
EOF

cat > "$HOME_D/.claude/settings.json" <<EOF
{
  "env": { "ASTRYX_AGENT": "$AGENT" },
  "hooks": {
    "PreToolUse": [ { "matcher": "", "hooks": [
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

tmux new-session -d -s "$SESS" -c "$HOME_D"
# --strict-mcp-config: a resident's world is its own .mcp.json, nothing inherited.
# Without it, user-scope MCP servers leak in and agents can bypass the wire.
tmux send-keys -t "=$SESS:" "claude ${RESUME}--model sonnet --permission-mode bypassPermissions --strict-mcp-config --dangerously-load-development-channels server:astryx" Enter

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
