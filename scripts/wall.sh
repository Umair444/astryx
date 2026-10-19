#!/usr/bin/env bash
# astryx · wall — the org's step streams, live, in one tmux grid. A true wall.
#
#   scripts/wall.sh              all residents (ax-* sessions)
#   scripts/wall.sh seed memory  only the named ones
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
#
# A COG (several orgs on this host, src/astryx/orgs.py):
#   scripts/wall.sh --cog              every org's agents, one pane each, titled agent@org
#   scripts/wall.sh --cog seed lab     only those: a bare name in every org, seed@lab in lab only
# Each pane renders from ITS org's table: wallpane.sh runs under that org's ASTRYX_HOME, so the one resolver
# (config.py dsn) gives that org's DSN, never another's. The roster reads each org's steps and its residents' own
# tmux server (-L ax-<org>; the primary's is the default socket). The cog wall is session `cogwall` on the
# primary's server (tmux's default socket), beside the primary's own `wall`, so neither clobbers the other.
# C-b m on an agent@org pane rings THAT org's doorbell (under its ASTRYX_HOME). One org: --cog refuses and says
# so, and plain `scripts/wall.sh` is exactly as before.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# C-b m on the cog wall: `--bell <pane title> <body>`. A title agent@org is that org's agent, rung under its own
# ASTRYX_HOME; an org the registry doesn't hold refuses (never another org's wire as a guess). A bare title is
# this org's agent: the one-org bell exactly.
if [ "${1:-}" = "--bell" ]; then
  t="${2:?pane title}"; body="${3:-}"
  case "$t" in
    *@*) home=$("$ROOT/venv/bin/python" "$ROOT/src/astryx/orgs.py" rooms | awk -F'\t' -v o="${t##*@}" '$1 == o { print $2 }')
         [ -n "$home" ] || { echo "wall --bell: no org ${t##*@} in this cog" >&2; exit 1; }
         ASTRYX_HOME="$home" exec "$ROOT/scripts/doorbell.sh" "${t%@*}" "$body" owner ;;
    *)   exec "$ROOT/scripts/doorbell.sh" "$t" "$body" owner ;;
  esac
fi

REBUILD=""; COG=""
while :; do
  case "${1:-}" in
    --rebuild) REBUILD=1; shift ;;
    --cog) COG=1; shift ;;
    *) break ;;
  esac
done
S=wall
if [ -n "$COG" ]; then
  # the cog wall is the PRIMARY's server (tmux's default socket, NAMED, as orgs.socket names it in a cog: a bare
  # `tmux` would follow an inherited $TMUX into another org's server), whichever org's shell asks
  S=cogwall
  rc=0; ROOMS=$("$ROOT/venv/bin/python" "$ROOT/src/astryx/orgs.py" rooms) || rc=$?
  case "$rc" in
    0) ;;
    1) echo "wall --cog: this host runs one org (no cog registry naming two or more); scripts/wall.sh shows it"; exit 1 ;;
    *) echo "wall --cog: the cog registry refuses (see above)"; exit 2 ;;
  esac
  AX_SOCK=default
  tmux() { command tmux -L "$AX_SOCK" "$@"; }
else
  . "$ROOT/scripts/org_tmux.sh"   # `tmux` is THIS org's server (S3b): the wall and its residents' sessions
fi

if [ -n "$COG" ]; then
  # One line per pane, `<agent>@<org> <its org's HOME>`. Each org's roster is read as that one org's: its own table
  # (the one resolver under its HOME) and its own residents' server. A name outside the charter grammar never
  # reaches a tmux command line; an org whose DSN won't resolve is named and skipped, never read through another's.
  pick=" $(echo "$*" | tr 'A-Z' 'a-z' | xargs) "
  PANES=""
  while IFS=$'\t' read -r org home sock; do
    [ -n "$org" ] || continue
    dsn=$(ASTRYX_HOME="$home" "$ROOT/venv/bin/python" "$ROOT/src/astryx/config.py" dsn --file) \
      || { echo "wall --cog: $org's database can't be resolved (its HOME $home): skipped" >&2; continue; }
    names=$( { psql "$dsn" -At -c \
        "SELECT DISTINCT agent FROM steps WHERE ts > now() - interval '7 days'" 2>/dev/null;
        command tmux -L "$sock" ls -F '#{session_name}' 2>/dev/null | grep '^ax-' | sed 's/^ax-//'; } \
      | grep -E '^[a-z0-9][a-z0-9._-]*$' | sort -u)
    for a in $names; do
      if [ $# -gt 0 ]; then
        case "$pick" in *" $a "*|*" $a@$org "*) ;; *) continue ;; esac
      fi
      PANES+="$a@$org $home"$'\n'
    done
  done <<< "$ROOMS"
  AGENTS=$(printf '%s' "$PANES" | cut -d' ' -f1)
  [ -n "$AGENTS" ] || { echo "no agents found in any org of the cog (no recent steps, no ax-* sessions)"; exit 1; }
elif [ $# -gt 0 ]; then
  AGENTS=$(echo "$*" | tr 'A-Z' 'a-z')
else
  # roster from the TABLE, not from tmux: an agent is whoever stepped recently
  # (a CLI-bodied agent has no ax-* session), plus any body alive right now.
  DSN=$("$ROOT/venv/bin/python" "$ROOT/src/astryx/config.py" dsn --file)   # the ONE resolver (plan-11324 S3a)
  AGENTS=$( { psql "$DSN" -At -c \
      "SELECT DISTINCT agent FROM steps WHERE ts > now() - interval '7 days'" 2>/dev/null;
      tmux ls -F '#{session_name}' 2>/dev/null | grep '^ax-' | sed 's/^ax-//'; } \
    | grep -v '^$' | sort -u)
fi
[ -n "$AGENTS" ] || { echo "no agents found (no recent steps, no ax-* sessions)"; exit 1; }   # org-home: a message, not a path

# JOIN an existing wall instead of killing it: running wall.sh twice must never
# crash the first viewer. Rebuild only when the roster changed or --rebuild.
if [ -z "$REBUILD" ] && tmux has-session -t "=$S" 2>/dev/null; then
  have=$(tmux list-panes -t "$S" -F '#{pane_title}' 2>/dev/null | sort | xargs)
  want=$(echo "$AGENTS" | xargs -n1 | sort | xargs)
  if [ "$have" = "$want" ]; then
    if [ -n "${TMUX:-}" ]; then exec tmux ${AX_SOCK:+-L "$AX_SOCK"} switch-client -t "$S"
    else exec tmux ${AX_SOCK:+-L "$AX_SOCK"} attach -t "$S"; fi
  fi
fi

tmux kill-session -t "$S" 2>/dev/null || true
tmux new-session -d -s "$S"
placeholder=$(tmux display-message -p -t "$S" '#{pane_id}')

tmux set -t "$S" pane-border-status top
tmux set -t "$S" pane-border-format " #[bold]#{pane_title} "
tmux set -t "$S" pane-border-style "fg=colour237"
tmux set -t "$S" pane-active-border-style "fg=cyan,bold"
tmux set -t "$S" status-style "bg=colour233,fg=cyan"
if [ -n "$COG" ]; then
  # the status line names the cog: its orgs, as the registry keys them
  tmux set -t "$S" status-left " ✦ astryx cog │ $(cut -f1 <<< "$ROOMS" | xargs | sed 's/ / · /g') │ C-b m = message focused agent "
  tmux set -t "$S" status-left-length 120
else
  tmux set -t "$S" status-left " ✦ astryx wall │ mirror │ C-b m = message focused agent "
  tmux set -t "$S" status-left-length 60
fi
tmux set -t "$S" status-right " %a %H:%M "
tmux set -w -t "$S" allow-set-title off 2>/dev/null || true

# C-b m: one line -> wire message (as owner) to the agent under focus. A binding is the SERVER's, and the cog wall
# shares the primary's server with its own wall: the cog's verb (--bell) rings a bare title exactly as the one-org
# binding does, so whichever wall bound it last, every pane's bell reaches its own org.
if [ -n "$COG" ]; then
  tmux bind-key -T prefix m command-prompt -p "wire → #{pane_title}:" \
    "run-shell '$ROOT/scripts/wall.sh --bell #{pane_title} \"%1\" >/dev/null 2>&1 || true'"
else
  tmux bind-key -T prefix m command-prompt -p "wire → #{pane_title}:" \
    "run-shell '$ROOT/scripts/doorbell.sh #{pane_title} \"%1\" owner >/dev/null 2>&1 || true'"
fi

# dead panes freeze visibly instead of collapsing the session
tmux set -w -t "$S" remain-on-exit on 2>/dev/null || true

for a in $AGENTS; do
  # A pane is the agent's step stream rendered from the table (wallpane.sh).
  # No attaching, no screen scraping, no sizing: the wire is the truth and
  # already records everything. The restart wrap + stderr log mean a dying
  # renderer restarts in 2s and leaves evidence in /tmp/astryx-wall.log.
  # In a cog the pane carries its org's HOME, so wallpane.sh reads THAT org's table.
  run="$ROOT/scripts/wallpane.sh $a"
  if [ -n "$COG" ]; then
    home=$(printf '%s' "$PANES" | awk -v t="$a" '$1 == t { sub(/^[^ ]+ /, ""); print; exit }')
    run="ASTRYX_HOME=$(printf '%q' "$home") $ROOT/scripts/wallpane.sh ${a%@*}"
  fi
  pane=$(tmux split-window -t "$S" -P -F '#{pane_id}' \
    "while :; do $run 2>>/tmp/astryx-wall.log; echo \"[$a renderer died \$(date +%H:%M:%S), restarting — see /tmp/astryx-wall.log]\"; sleep 2; done")
  tmux select-pane -t "$pane" -T "$a"
  tmux select-layout -t "$S" tiled >/dev/null
done
tmux kill-pane -t "$placeholder" 2>/dev/null || true
tmux select-layout -t "$S" tiled >/dev/null

if [ -n "${TMUX:-}" ]; then
  exec tmux ${AX_SOCK:+-L "$AX_SOCK"} switch-client -t "$S"     # already inside tmux: switch, never nest
else
  exec tmux ${AX_SOCK:+-L "$AX_SOCK"} attach -t "$S"
fi
