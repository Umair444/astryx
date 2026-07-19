#!/usr/bin/env bash
# astryx · wall — the org's step streams, live, in one tmux grid. A true wall.
#
#   nucleus/wall.sh              all residents (ax-* sessions)
#   nucleus/wall.sh seed memory  only the named ones
#
# Each pane renders its agent's last steps FROM THE TABLE (wallpane.sh): time,
# kind glyph, content. No terminal scraping, no TUI chrome, nothing attached to
# the agent sessions, so nothing to crash and nothing to size. Panes stay small
# and scale to dozens of agents; Ctrl-b z zooms one to full screen (it shows
# more lines automatically). `tmux attach -rt ax-<name>` remains the way to see
# an agent's raw terminal when you want full fidelity.
#
# Talking to an agent means the wire: Ctrl-b m on a focused pane prompts for
# one line and INSERTs it as an owner message to that agent. Keystrokes never
# touch a pane (the lesson is law). Ctrl-b d leaves.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

REBUILD=""
[ "${1:-}" = "--rebuild" ] && { REBUILD=1; shift; }
if [ $# -gt 0 ]; then
  AGENTS=$(echo "$*" | tr 'A-Z' 'a-z')
else
  # roster from the TABLE, not from tmux: an agent is whoever stepped recently
  # (a CLI-bodied agent has no ax-* session), plus any body alive right now.
  DSN=$(grep '^ASTRYX_DSN=' "$ROOT/.env" | cut -d= -f2-)
  AGENTS=$( { psql "$DSN" -At -c \
      "SELECT DISTINCT agent FROM steps WHERE ts > now() - interval '7 days'" 2>/dev/null;
      tmux ls -F '#{session_name}' 2>/dev/null | grep '^ax-' | sed 's/^ax-//'; } \
    | grep -v '^$' | sort -u)
fi
[ -n "$AGENTS" ] || { echo "no agents found (no recent steps, no ax-* sessions)"; exit 1; }

# JOIN an existing wall instead of killing it: running wall.sh twice must never
# crash the first viewer. Rebuild only when the roster changed or --rebuild.
if [ -z "$REBUILD" ] && tmux has-session -t =wall 2>/dev/null; then
  have=$(tmux list-panes -t wall -F '#{pane_title}' 2>/dev/null | sort | xargs)
  want=$(echo "$AGENTS" | xargs -n1 | sort | xargs)
  if [ "$have" = "$want" ]; then
    if [ -n "${TMUX:-}" ]; then exec tmux switch-client -t wall
    else exec tmux attach -t wall; fi
  fi
fi

tmux kill-session -t wall 2>/dev/null || true
tmux new-session -d -s wall
placeholder=$(tmux display-message -p -t wall '#{pane_id}')

tmux set -t wall pane-border-status top
tmux set -t wall pane-border-format " #[bold]#{pane_title} "
tmux set -t wall pane-border-style "fg=colour237"
tmux set -t wall pane-active-border-style "fg=cyan,bold"
tmux set -t wall status-style "bg=colour233,fg=cyan"
tmux set -t wall status-left " ✦ astryx wall │ mirror │ C-b m = message focused agent "
tmux set -t wall status-left-length 60
tmux set -t wall status-right " %a %H:%M "
tmux set -w -t wall allow-set-title off 2>/dev/null || true

# C-b m: one line -> wire message (as owner) to the agent under focus
tmux bind-key -T prefix m command-prompt -p "wire → #{pane_title}:" \
  "run-shell '$ROOT/nucleus/doorbell.sh #{pane_title} \"%1\" owner >/dev/null 2>&1 || true'"

# dead panes freeze visibly instead of collapsing the session
tmux set -w -t wall remain-on-exit on 2>/dev/null || true

for a in $AGENTS; do
  # A pane is the agent's step stream rendered from the table (wallpane.sh).
  # No attaching, no screen scraping, no sizing: the wire is the truth and
  # already records everything. The restart wrap + stderr log mean a dying
  # renderer restarts in 2s and leaves evidence in /tmp/astryx-wall.log.
  pane=$(tmux split-window -t wall -P -F '#{pane_id}' \
    "while :; do $ROOT/nucleus/wallpane.sh $a 2>>/tmp/astryx-wall.log; echo \"[$a renderer died \$(date +%H:%M:%S), restarting — see /tmp/astryx-wall.log]\"; sleep 2; done")
  tmux select-pane -t "$pane" -T "$a"
  tmux select-layout -t wall tiled >/dev/null
done
tmux kill-pane -t "$placeholder" 2>/dev/null || true
tmux select-layout -t wall tiled >/dev/null

if [ -n "${TMUX:-}" ]; then
  exec tmux switch-client -t wall     # already inside tmux: switch, never nest
else
  exec tmux attach -t wall
fi
