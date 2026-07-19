#!/usr/bin/env bash
# astryx · wall — every resident body, live, in one tmux grid. Eyes only.
#
#   nucleus/wall.sh              all residents (ax-* sessions)
#   nucleus/wall.sh seed memory  only the named ones
#
# Panes MIRROR each agent's screen (capture-pane once a second) instead of
# attaching to it. A mirror always fills its pane at any size on any monitor,
# never fights other viewers over window size, and leaves the agent sessions
# completely untouched, so `tmux attach -rt ax-<name>` stays native and
# full-fidelity whenever you want the real thing.
#
# Talking to an agent means the wire: Ctrl-b m on a focused pane prompts for
# one line and INSERTs it as an owner message to that agent. Keystrokes never
# touch a pane (the lesson is law). Ctrl-b z zooms, Ctrl-b d leaves.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ $# -gt 0 ]; then
  AGENTS=$(echo "$*" | tr 'A-Z' 'a-z')
else
  AGENTS=$(tmux ls -F '#{session_name}' 2>/dev/null | grep '^ax-' | sed 's/^ax-//' | sort)
fi
[ -n "$AGENTS" ] || { echo "no residents alive (no ax-* tmux sessions)"; exit 1; }

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

for a in $AGENTS; do
  # Mirror loop: home the cursor, repaint the last pane-height lines of the
  # agent's screen (colors kept, each line erased to EOL), wipe the rest.
  # $TMUX_PANE pins the size query to THIS pane, whatever monitor it is on.
  cmd='while :; do
    H=$(tmux display -p -t "$TMUX_PANE" "#{pane_height}" 2>/dev/null || echo 20)
    if out=$(tmux capture-pane -pe -t "=ax-'"$a"'" 2>/dev/null); then
      printf "\033[H%s\033[0m\033[J" "$(printf "%s\n" "$out" | sed -e "s/\$/\x1b[K/" | tail -n "$H")"
    else
      printf "\033[H\033[J  ['"$a"' is down — the nucleus can respawn it]"
    fi
    sleep 1
  done'
  pane=$(tmux split-window -t wall -P -F '#{pane_id}' "$cmd")
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
