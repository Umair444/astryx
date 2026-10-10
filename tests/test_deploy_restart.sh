#!/usr/bin/env bash
# test_deploy_restart — deploy.sh restart's failure paths, with EVERY side effect stubbed (no real
# db, unit, tmux or resident is touched). A resident whose spawn refuses must be a named ✗, the run
# must CONTINUE to the next resident, end "INCOMPLETE" (rc 1), and the pulse timer must be started
# again even so (a2 #42367: under set -e the first version aborted and left the pulse dark).
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/root/nucleus" "$T/root/venv/bin" "$T/bin"
LOG="$T/log"; : > "$LOG"
printf 'ASTRYX_DSN=postgres://x@127.0.0.1:5432/x\n' > "$T/root/.env"
# the roster: two residents; "bad" refuses to spawn, "good" spawns
cat > "$T/root/venv/bin/python" <<'P'
#!/usr/bin/env bash
if [ "${1:-}" = "nucleus/charter.py" ]; then printf 'bad\ngood\n'; exit 0; fi
cat >/dev/null                                           # ears() (run from ROOT): none until "good"
[ -e spawned-good ] && echo "good 999999999"            # has spawned, then one, so its ready check runs
exit 0
P
cat > "$T/root/nucleus/spawn.sh" <<'P'
#!/usr/bin/env bash
if [ "$1" = bad ]; then echo "'bad' already has a live body outside tmux — refusing a second one"; exit 3; fi
touch "$(dirname "$0")/../spawned-$1"
echo "$1 resident (tmux:ax-$1, boot=resumed)"
P
for c in psql docker tmux curl; do printf '#!/usr/bin/env bash\necho "%s $*" >> "%s"\nexit 0\n' "$c" "$LOG" > "$T/bin/$c"; done
# psql: "busy" queries answer 0
printf '#!/usr/bin/env bash\necho "psql $*" >> "%s"\ncase "$*" in *count*) echo 0;; esac\nexit 0\n' "$LOG" > "$T/bin/psql"
printf '#!/usr/bin/env bash\necho "sudo $*" >> "%s"\nexit 0\n' "$LOG" > "$T/bin/sudo"
# systemctl: no enabled units to restart; is-active answers yes
printf '#!/usr/bin/env bash\necho "systemctl $*" >> "%s"\nexit 0\n' "$LOG" > "$T/bin/systemctl"
# tmux pane shows the ready mode line for "good"; like real tmux, an exact "=name" with no ":" is a
# session, not a pane, and capture-pane can't find it (the 10-10 restart reported 16 live agents ✗)
cat > "$T/bin/tmux" <<STUB
#!/usr/bin/env bash
echo "tmux \$*" >> "$LOG"
if [ "\$1" = capture-pane ]; then
  for t in "\$@"; do case "\$t" in =*:*) ;; =*) echo "can't find pane: \${t}" >&2; exit 1;; esac; done
  echo "bypass permissions on"
fi
exit 0
STUB
chmod +x "$T"/bin/* "$T/root/venv/bin/python" "$T/root/nucleus/spawn.sh"
out=$(PATH="$T/bin:$PATH" ROOT="$T/root" ASTRYX_AGENT= bash -c '
  set -euo pipefail
  eval "$(sed -n "/^ears() {/,/^}/p; /^ears_of() /p; /^restart_org() {/,/^}/p" "'"$REPO"'/nucleus/deploy.sh")"
  sleep() { :; }
  restart_org' 2>&1); rc=$?
fails=0
arm() { if eval "$2"; then echo "  PASS  $1"; else echo "  FAIL  $1"; fails=$((fails+1)); fi; }
arm "a refusing spawn is a named ✗" 'grep -q "✗ bad: spawn failed" <<<"$out"'
arm "the run CONTINUES to the next resident" 'grep -q "✓ good resident" <<<"$out"'
arm "it ends INCOMPLETE with rc 1, never \"the org is back\"" '[ $rc = 1 ] && grep -q INCOMPLETE <<<"$out" && ! grep -q "the org is back" <<<"$out"'
arm "a ready resident passes the ready check" 'grep -q "^tmux capture-pane" "$LOG" && ! grep -q "good: spawned, but" <<<"$out"'
arm "the pulse is started again after the failure" 'grep -q "sudo systemctl start astryx-pulse.timer" "$LOG"'
arm "the pulse was paused before any resident restart" '[ "$(grep -n "stop astryx-pulse.timer" "$LOG" | head -1 | cut -d: -f1)" -lt "$(grep -n "kill-session" "$LOG" | head -1 | cut -d: -f1)" ]'
[ $fails = 0 ] && echo PASS || { echo "$out" | tail -8; echo "FAIL ($fails)"; exit 1; }
