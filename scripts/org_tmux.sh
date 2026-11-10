# shellcheck shell=bash
# Sourced (never run): defines `tmux` as THIS org's tmux (plan-11324 S3b, #58435). The sourcing script sets ROOT.
#
# `ax-<agent>` is a HOST-wide name: on a cog of several orgs, two orgs' `seed` would be one session. So each
# org's residents live on a tmux server of their own, `-L ax-<org>` (src/astryx/orgs.py socket: the ONE resolver).
# One org (no registry file at all, the host today): nothing is asked and AX_SOCK stays empty, so every `tmux` below is
# exactly `command tmux "$@"`, the default socket, byte for byte. A registry present: orgs.py decides; a HOME it can't
# place REFUSES (exit 2), never the default socket as a guess.
# `exec tmux` and `command tmux` bypass a function: those call sites spell `${AX_SOCK:+-L "$AX_SOCK"}` themselves.
AX_SOCK=""
if [ -e "${ASTRYX_COG_REGISTRY:-/etc/astryx/cog.json}" ]; then
  _ax_rc=0; AX_SOCK=$("$ROOT/venv/bin/python" "$ROOT/src/astryx/orgs.py" socket) || _ax_rc=$?
  case "$_ax_rc" in
    0) ;;
    1) AX_SOCK="" ;;
    *) echo "org_tmux: this host's org registry can't place this process's org HOME (set ASTRYX_HOME): refusing" >&2
       exit 2 ;;
  esac
fi
tmux() { command tmux ${AX_SOCK:+-L "$AX_SOCK"} "$@"; }
