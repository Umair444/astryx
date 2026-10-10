#!/usr/bin/env bash
# test_deploy_build — deploy.sh's build and restart failures STOP the deploy (seed #43278), and init.sh's banner prints no
# credential. Every side effect is stubbed (no real npm, unit or sudo): the REAL deploy.sh is copied into a temp root.
#   1. a failing web build → rc 1, "ABORTED", NOTHING restarted, never "done." (it used to restart the old bundle and
#      print "deploy: obs done.", because set -e doesn't trip on the left of `build_web && restart`)
#   2. a good build → restarted, "done."
#   3. under sudo (uid 0, SUDO_USER set) the build runs AS the invoking user (`sudo -u <user>`): root's PATH has no node
#   4. a failing restart → rc 1, "ABORTED at <unit>", never "done."
#   4b. a root-owned stale build log from an earlier sudo run can't make a user's good build read FAILED
#   5. init.sh's closing banner prints the observatory URL WITHOUT the key (stdout reaches logs and agent contexts)
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fails=0
arm() { if eval "$2"; then echo "  PASS  $1"; else echo "  FAIL  $1"; fails=$((fails+1)); fi; }

setup() {   # $1: npm rc, $2: systemctl-restart rc, $3: uid the stub `id` reports
  rm -rf "$T/root" "$T/bin"; mkdir -p "$T/root/nucleus" "$T/root/observatory/web" "$T/bin"
  cp "$REPO/nucleus/deploy.sh" "$T/root/nucleus/deploy.sh"
  : > "$T/log"
  printf '#!/usr/bin/env bash\necho "npm $* as=${STUB_AS:-self}" >> "%s"\nexit %s\n' "$T/log" "$1" > "$T/bin/npm"
  # $2: restart rc for EVERY unit, or "first" = only astryx-observatory's restart fails (the `all` arm, a2 R1)
  if [ "$2" = first ]; then
    printf '#!/usr/bin/env bash\necho "systemctl $*" >> "%s"\n[ "$1" = restart ] && [ "$2" = astryx-observatory ] && exit 1\n[ "$1" = is-active ] && echo active\nexit 0\n' \
      "$T/log" > "$T/bin/systemctl"
  else
    printf '#!/usr/bin/env bash\necho "systemctl $*" >> "%s"\n[ "$1" = restart ] && exit %s\n[ "$1" = is-active ] && echo active\nexit 0\n' \
      "$T/log" "$2" > "$T/bin/systemctl"
  fi
  # sudo: `sudo -u U -H bash -lc CMD` runs CMD as "U" (marked, no real login shell); anything else runs as is
  cat > "$T/bin/sudo" <<P
#!/usr/bin/env bash
echo "sudo \$*" >> "$T/log"
if [ "\$1" = -u ]; then u=\$2; shift 3; if [ "\$1" = bash ] && [ "\$2" = -lc ]; then c=\$3; shift 3; exec env STUB_AS="\$u" bash -c "\$c" "\$@"; fi; exec "\$@"; fi
exec "\$@"
P
  printf '#!/usr/bin/env bash\n[ "$1" = -u ] && echo %s && exit 0\nexec /usr/bin/id "$@"\n' "$3" > "$T/bin/id"
  chmod +x "$T"/bin/*
}
run() { PATH="$T/bin:$PATH" SUDO_USER="${1:-}" bash "$T/root/nucleus/deploy.sh" "${2:-obs}" 2>&1; }

setup 1 0 1000; out=$(run); rc=$?
arm "1. a failing web build → rc 1 and ABORTED" '[ $rc = 1 ] && grep -q "ABORTED — the build failed" <<<"$out"'
arm "1. …nothing is restarted" '! grep -q "systemctl restart" "$T/log"'
arm "1. …and it never claims done" '! grep -q "deploy: obs done" <<<"$out"'

setup 0 0 1000; out=$(run); rc=$?
arm "2. a good build → restarted, done (rc 0)" '[ $rc = 0 ] && grep -q "systemctl restart astryx-observatory" "$T/log" && grep -q "deploy: obs done" <<<"$out"'
arm "2. …as the caller when not under sudo" 'grep -q "npm run build as=self" "$T/log"'

setup 0 0 0; out=$(run alice); rc=$?
arm "3. under sudo the build runs AS the invoking user (root has no node)" '[ $rc = 0 ] && grep -q "sudo -u alice -H bash -lc" "$T/log" && grep -q "npm run build as=alice" "$T/log"'

export TMPDIR="$T/tmp"; mkdir -p "$TMPDIR"; : > "$TMPDIR/astryx-build.log"; chmod 000 "$TMPDIR/astryx-build.log"
setup 0 0 1000; out=$(run); rc=$?
arm "4b. a stale unwritable build log (an earlier sudo run's) can't fail a good build: each run logs fresh" \
  '[ $rc = 0 ] && grep -q "deploy: obs done" <<<"$out"'
setup 0 1 1000; out=$(run); rc=$?
arm "4. a failing restart → rc 1, ABORTED at the unit, never done" '[ $rc = 1 ] && grep -q "ABORTED at astryx-observatory" <<<"$out" && ! grep -q "deploy: obs done" <<<"$out"'

# 4c. a2 #44267 R1: under `obs` a failing LAST && element trips set -e anyway, so restart's own exit was unwitnessed.
#     `all` restarts observatory THEN whatsapp: the first failing must stop the deploy before the second.
setup 0 first 1000; out=$(run "" all); rc=$?
arm "4c. \`all\` with the FIRST restart failing → rc 1, ABORTED at it, the next unit never restarted, never done" \
  '[ $rc = 1 ] && grep -q "ABORTED at astryx-observatory" <<<"$out" && ! grep -q "restart astryx-whatsapp" "$T/log" && ! grep -q "deploy: all done" <<<"$out"'
# 3b. a2 R3: the build path reaches the user's shell as DATA (a quote in it can't break or inject)
arm "3b. the sudo build passes the path as an argument (bash -lc '…\$1…' _ <dir>), never inside the shell text" \
  'grep -q "bash -lc '"'"'cd \"\$1\" && npm run build'"'"' _ " "$REPO/nucleus/deploy.sh"'

# 5b. a2 R2: BEHAVIOURAL — run the real banner block with a sentinel OBS_KEY; the sentinel must never reach stdout
#     (a print-verb denylist missed printf: any verb that prints the key is the defect)
mkdir -p "$T/ban" "$T/clip"; printf 'OBS_KEY=SENTINELKEY4242\n' > "$T/ban/.env"
# STUB clipboards FIRST on PATH (a2 #44272 B1): /usr/bin/wl-copy exists on this host, and from the owner's Wayland
# terminal the banner's copy branch would put the sentinel in HIS clipboard on every check.sh run. The stubs take
# the bytes into the temp dir instead, which also shows the copy branch ran; no real clipboard is ever reachable.
for c in wl-copy xclip pbcopy; do printf '#!/usr/bin/env bash\ncat > "%s/%s"\nexit 0\n' "$T/clip" "$c" > "$T/clip/$c"; done
chmod +x "$T/clip/wl-copy" "$T/clip/xclip" "$T/clip/pbcopy"
blk=$(sed -n '/OBS_KEY is a CREDENTIAL/,/never paste it in chat/p' "$REPO/init.sh")
bout=$(cd "$T/ban" && PATH="$T/clip:/usr/bin:/bin" bash -c 'say() { echo "$*"; }; f() { '"$blk"'
}; f' 2>&1)
arm "5b. the REAL banner block, run with a sentinel key: it says where the key lives and never prints it" \
  '[ -n "$bout" ] && grep -q "localhost:8090" <<<"$bout" && ! grep -q SENTINELKEY4242 <<<"$bout"'
arm "5b. …the key went to the (STUB) clipboard only, never a real one" \
  'grep -q SENTINELKEY4242 "$T/clip/wl-copy" 2>/dev/null && grep -q "copied to your clipboard" <<<"$bout"'

# 5. the banner block: what init.sh PRINTS never carries the key (it goes to the clipboard and lives in .env)
banner=$(sed -n '/OBS_KEY is a CREDENTIAL/,/never paste it in chat/p' "$REPO/init.sh")
arm "5. init.sh's banner prints no key (no \$key in any say/echo; the URL carries none)" \
  '[ -n "$banner" ] && ! grep -E "(say|echo).*\\\$key" <<<"$banner" && ! grep -q "key=\$key" <<<"$banner" && grep -q "url=\"http://localhost:8090/\"" <<<"$banner"'

[ $fails = 0 ] && echo PASS || { echo "FAIL ($fails)"; exit 1; }
