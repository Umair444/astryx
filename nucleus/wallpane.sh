#!/usr/bin/env bash
# astryx · wallpane — one wall pane: an agent's step stream, straight from the
# table. No terminal scraping, no attaching, no sizing wars: the wire already
# records everything, this just renders the last pane-height lines of it.
# Zoom (C-b z) shows more lines automatically: height is re-read every cycle.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DSN=$(grep '^ASTRYX_DSN=' "$ROOT/.env" | cut -d= -f2-)
A="${1:?agent}"
export PGTZ="$(timedatectl show -p Timezone --value 2>/dev/null || echo UTC)"

while :; do
  H=$(tmux display -p -t "$TMUX_PANE" '#{pane_height}' 2>/dev/null || echo 20)
  W=$(tmux display -p -t "$TMUX_PANE" '#{pane_width}' 2>/dev/null || echo 80)
  out=$(psql "$DSN" -At -F'|' -c \
    "SELECT to_char(ts,'HH24:MI'), kind,
            left(regexp_replace(coalesce(content,''), E'[\\n\\r\\t ]+', ' ', 'g'), $((W - 9)))
     FROM steps WHERE agent='$A' ORDER BY id DESC LIMIT $((H > 1 ? H : 1))" 2>/dev/null \
    | tac | awk -F'|' '
      { g = "·"; c = "37" }
      $2 == "tool"      { g = "◌"; c = "36" }
      $2 == "tool_done" { g = "●"; c = "36" }
      $2 == "response"  { g = "▸"; c = "97" }
      $2 == "milestone" { g = "★"; c = "92" }
      $2 == "error"     { g = "⚠"; c = "91" }
      { printf "\033[2m%s\033[0m \033[%sm%s\033[0m %s\033[K\n", $1, c, g, $3 }')
  if [ -z "$out" ]; then out="  (no steps yet — the wire is quiet)"; fi
  printf '\033[H%s\033[0m\033[J' "$out"
  sleep 2
done
