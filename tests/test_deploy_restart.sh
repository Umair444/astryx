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
# systemctl: ONE enabled unit (so a full restart really restarts something); is-active answers yes
printf '#!/usr/bin/env bash\necho "systemctl $*" >> "%s"\n[ "$1" = list-unit-files ] && echo "astryx-observatory.service enabled enabled"\nexit 0\n' "$LOG" > "$T/bin/systemctl"
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
# the full run DID ask docker for the database container and systemctl for the units (the control for the arms below)
arm "control: a full restart asks docker for the db and RESTARTS the enabled unit" 'grep -q "^docker ps" "$LOG" && grep -q "systemctl restart astryx-observatory" "$LOG"'
# `restart_org residents` (deploy.sh residents): the residents roll, the database and the services are never touched
rm -f "$T/root/spawned-good"; : > "$LOG"
out2=$(PATH="$T/bin:$PATH" ROOT="$T/root" ASTRYX_AGENT= bash -c '
  set -euo pipefail
  eval "$(sed -n "/^ears() {/,/^}/p; /^ears_of() /p; /^restart_org() {/,/^}/p" "'"$REPO"'/nucleus/deploy.sh")"
  sleep() { :; }
  restart_org residents' 2>&1)
arm "residents: no docker call at all (the database is not bounced)" '! grep -q "^docker " "$LOG"'
arm "residents: no unit is restarted (the verify step may still READ unit states)" '! grep -qE "systemctl restart astryx-" "$LOG"'
arm "residents: the residents are still rolled (kill-session + spawn)" 'grep -q "kill-session" "$LOG" && grep -q "✓ good resident" <<<"$out2"'
arm "residents: the pulse is paused and started again" 'grep -q "stop astryx-pulse.timer" "$LOG" && grep -q "start astryx-pulse.timer" "$LOG"'
[ $fails = 0 ] && echo PASS || { echo "$out" | tail -8; echo "FAIL ($fails)"; exit 1; }
