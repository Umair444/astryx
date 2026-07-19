#!/usr/bin/env bash
# astryx · wall — every resident body, live, in one tmux grid. Eyes only.
#
#   nucleus/wall.sh            all residents (ax-* sessions), read-only panes
#   nucleus/wall.sh seed memory  only the named ones
#
# There is no write mode. Talking to an agent means the wire: press Ctrl-b m
# on a focused pane and type; your line is INSERTed as an owner message to
# that agent and delivered through its channel like any other. Keystrokes
# never touch a pane (the lesson is law).
#
# Ctrl-b d leaves the wall; agents are unaffected. Rebuild any time.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ $# -gt 0 ]; then
  AGENTS=$(echo "$*" | tr 'A-Z' 'a-z')
else
  AGENTS=$(tmux ls -F '#{session_name}' 2>/dev/null | grep '^ax-' | sed 's/^ax-//' | sort)
fi
[ -n "$AGENTS" ] || { echo "no residents alive (no ax-* tmux sessions)"; exit 1; }

tmux kill-session -t wall 2>/dev/null || true
tmux new-session -d -s wall -x "${COLUMNS:-220}" -y "${LINES:-50}"
placeholder=$(tmux display-message -p -t wall '#{pane_id}')

tmux set -t wall pane-border-status top
tmux set -t wall pane-border-format " #[bold]#{pane_title} "
tmux set -t wall pane-border-style "fg=colour237"
tmux set -t wall pane-active-border-style "fg=cyan,bold"
tmux set -t wall status-style "bg=colour233,fg=cyan"
tmux set -t wall status-left " ✦ astryx wall │ eyes only │ C-b m = message focused agent "
tmux set -t wall status-left-length 60
tmux set -t wall status-right " %a %H:%M "
tmux set -w -t wall allow-set-title off 2>/dev/null || true

# C-b m: one line -> wire message to the agent under focus (pane title = agent)
tmux bind-key -T prefix m command-prompt -p "wire → #{pane_title}:" \
  "run-shell '$ROOT/nucleus/doorbell.sh #{pane_title} \"%1\" owner >/dev/null 2>&1 || true'"

for a in $AGENTS; do
  # Self-healing pane: attach while the session lives, wait when it does not.
  # TMUX= clears the env so tmux allows the nested attach; '=ax-name' is an
  # EXACT session match; detach-on-destroy keeps a respawn from hopping this
  # viewer onto some other agent's session (GENESIS wall lessons, kept).
  cmd="while :; do if tmux has-session -t =ax-$a 2>/dev/null; then TMUX= tmux attach -r -t =ax-$a \\; set detach-on-destroy on; else clear; echo '  [$a is down — the nucleus can respawn it]'; sleep 2; fi; done"
  pane=$(tmux split-window -t wall -P -F '#{pane_id}' "$cmd")
  tmux select-pane -t "$pane" -T "$a"
  tmux select-layout -t wall tiled >/dev/null
done
tmux kill-pane -t "$placeholder" 2>/dev/null || true
tmux select-layout -t wall tiled >/dev/null

exec tmux attach -t wall
