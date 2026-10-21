#!/usr/bin/env bash
# astryx · run every committed CODE invariant in one place.
#
# The invariant tests and guards (plan-17/18/19) were each committed but nothing RAN
# them together — and a test nothing runs only proves its last manual invocation. This
# is the single command, local and in CI (.github/workflows/tests.yml), so a regression
# to the charter resolver, the tier floor, dep coverage, or the referral guard is caught
# continuously instead of by memory. Distinct from `./init.sh doctor` (runtime health of
# a live org); this checks the CODE's invariants and needs no running org.
#
# The three unit tests + coverage are PURE-STDLIB — they run on a bare python3, so CI
# needs no pip install. The media probe runs only where the media stack is installed.
#
# ── A SKIP IS NOT A PASS (08-14) ────────────────────────────────────────────────────
# The second blind spot in this file, the same shape as the first one level down. The
# first was "is every oracle INVOKED" (test_check_coverage.py). This is "did every
# invoked oracle actually RUN." Reproduced on a clean checkout of HEAD: five gates
# verified NOTHING — two of them because the trigger BODY under test was absent from the
# artifact entirely — and this printed `ALL CODE INVARIANTS PASS` and exited 0. Each
# oracle announced its skip honestly on stdout; the AGGREGATE verdict, the one line a
# human or a CI badge reads, out-claimed every one of them.
#
# The protocol: an oracle that verified LESS THAN IT CLAIMS exits 77 (the GNU automake
# SKIP convention — a standard, not an invention). A partial skip is a 77 too: a suite
# that checked eight things and could not check the ninth is not a pass, because the
# unverified part is exactly where a regression hides.
#
# DEFAULT IS STRICT — an unverified gate is RED. That is the fail-safe polarity for a
# detector (unknown -> WATCHED): on a developer machine or a live org there is no
# legitimate reason for a gate to observe nothing, so a vanished trigger body or a
# broken venv now goes red instead of green. Set CHECK_ALLOW_SKIP=1 to downgrade skips
# to amber — that is for a bare CI clone, where the gitignored bodies genuinely are not
# there. Even then the verdict NAMES every unverified gate and never claims ALL PASS.
# There is no manifest of what-may-skip-where to rot: the caller opts out, visibly.
set -uo pipefail
# No gate inherits a repo locator or the caller's `git -c` settings. A hook from a linked
# worktree, a branch check, or a worktree shell can all carry GIT_DIR/GIT_CONFIG_PARAMETERS,
# and one test's `git init <tmp>` under GIT_DIR re-initialized the SHARED repo as bare
# (2026-09-30). This is the chokepoint every gate's environment passes through, so the scrub
# lives here for every caller. Oracle: tests/test_git_env_isolation.py.
for v in $(compgen -e | grep "^GIT_"); do unset "$v"; done
# No gate runs AS the caller either. A gate's child `claude -p` runs the user-wide Stop hook (hooks/step.py), which
# writes turns and steps to prod under ASTRYX_AGENT. With a resident's name inherited, init.sh's login probe credited
# fake turns to it (a2 #53059), and so would any future probe (a stationed call now names ITSELF: station.py). The pulse's run_check already runs
# every gate with no name (systemd env), so no gate needs one. Oracle: tests/test_check_noagent.py.
unset ASTRYX_AGENT
# The timer's seen-set role reaches ONE gate (plan-11908 D5, a3 BC-1 #62652): check_watch.sh exports it, it's read once
# here and unset, and only the enforce line below carries it back. Every other gate (and anything it spawns) runs
# without it, so no second process can become a writer of the live sqlguard_seen. Oracle: tests/test_sqlguard_seen.py N6.
SQLGUARD_WRITE_SEEN=${ASTRYX_SQLGUARD_WRITE_SEEN:-}; unset ASTRYX_SQLGUARD_WRITE_SEEN
# No gate sees the HOST's org registry either (plan-11324 S3f S3, seed #60778 item 4). /etc/astryx/cog.json is a host
# FILE that no env scrub removes, so in a cog every gate would run under multi. Pinned to a path that names no file, a
# gate runs as this checkout's own org, which in a cog is the PRIMARY's (its HOME is the checkout), exactly as before the
# cog; an oracle that needs a cog builds its own registry and names it, as every one does. Before the first estate read.
export ASTRYX_COG_REGISTRY="${TMPDIR:-/tmp}/astryx-gate-$$-no-registry/cog.json"
cd "$(dirname "$0")/.."
PY=${PY:-venv/bin/python}; [ -x "$PY" ] || PY=python3

# Node for the channel gates. The pulse runs check.sh on a minimal systemd PATH with no
# mise dir, so the node the org actually spawns agents with is invisible and the channel
# gates (test_ear_survival, test_wake_recovery) silently SKIP — verified nothing — on every
# timer run while passing interactively. They resolve node via shutil.which, so put the org's
# node on PATH from the ASTRYX_NODE anchor (env first, then .env — the same host-config
# spawn.sh honors; pulse.py loads only ASTRYX_DSN, not the whole .env, so read it here).
# Harmless where ASTRYX_NODE is unset or node is already found. (seed, steward check_stamp finding 2026-09-20.)
NODE_BIN=$("$PY" src/astryx/config.py get ASTRYX_NODE 2>/dev/null)   # env first, then the org's settings: the ONE resolver (plan-11324 S3a)
[ -n "$NODE_BIN" ] && export PATH="$(dirname "$NODE_BIN"):$PATH"

EXIT_SKIP=77
fail=0
verified=0
declare -a UNVERIFIED=()
declare -a FAILED=()
declare -a LIARS=()
# EVERY GATE HAS A WALL CLOCK (seed #45252). A wedged chromium under the pilot gate held a whole run open for 3h36m
# (a4 #45241), and with it every agent waiting for "no check.sh running". So each gate runs under GNU `timeout`, which
# puts the gate in its OWN process group and signals that whole group on expiry (grandchildren, chromium and vite
# included), then SIGKILLs it CHECK_GATE_KILL_AFTER seconds later. An expired gate is ✗ TIMED OUT: a failure, named,
# never a pass and never 77. The default is generous; a known-long gate takes `run --cap=<s> "<label>" cmd…`.
# The gate runs in the BACKGROUND and is waited on, so a signal to check.sh itself (Ctrl-C, an outer timeout, a kill)
# reaches the trap below, which kills the running gate's group. Before this, killing check.sh orphaned its gate.
GATE_CAP=${CHECK_GATE_CAP:-1200}
GATE_KILL_AFTER=${CHECK_GATE_KILL_AFTER:-15}
# read once and NOT passed down: a gate that runs check.sh's run() itself (test_check_gate_cap's stubs, a nested
# branch_check suite) would otherwise append its own rows to the top-level run's timing file (1714 rows for ~155 gates)
GATE_TIMES_FILE=${CHECK_GATE_TIMES:-}
unset CHECK_GATE_TIMES
GATE_PGID=""
GATE_OUT=$(mktemp "${TMPDIR:-/tmp}/check-gate.XXXXXX")
# The group kill can race the fork: `$!` is known before the forked timeout has called setpgid, so a signal in that
# millisecond finds no group (a4 #45258 measured 1 survivor in 40). Then signal timeout itself: it forwards a TERM to
# its child, and a timeout killed before it set its handler never started the gate at all.
# And a signal can land between the fork and `GATE_PGID=$!` (a4 #45394 saw survivors on the arm), when the variable is
# still empty: so every background job of this shell is reaped too, by group and then by pid. check.sh starts no
# background job but a gate, so `jobs -p` names exactly the gate's timeout.
# And a single TERM to a JUST-forked child can be lost: measured with check.sh sourced, one TERM right after `cmd &`
# left 20 of 20 children alive (19/20 even with its TERM trap removed), while the same TERM 0.2s later, or in a bare
# shell with or without any trap, killed 20/20. The mechanism is NOT identified, so the reap doesn't depend on one:
# whatever is still alive after a 1s grace gets SIGKILL, which nothing can catch or defer. A target killed that early
# has not exec'd timeout yet, so it has no gate child to orphan.
# EVERY GATE HAS ITS OWN DIR (plan-10108 D1, a4 #50739): a gate silently assumed it was the only one on the host, and
# concurrent check.sh runs are routine (10-12: forge's merge_check, seed's harness and a review all ran pilot gates within
# a minute). run() hands each gate a fresh $G as TMPDIR, so every mkdtemp/tmpdir()-derived profile, cache and scratch is
# per gate by construction, with no gate edit. XDG_CACHE_HOME rides it (a3 BC-1 i; XDG_RUNTIME_DIR stays the user's), and
# so does VITE_CACHE_DIR (D2, read by observatory/web/vite.config.ts). The rule: $G holds what the gate OWNS and NOTHING
# OUTLIVES the gate; whatever a later run reads lives in a declared shared root (`# shared-on-purpose:`), e.g. runscope's
# SCOPE_ROOT and the oracle reaper's ORACLE_BASE, the cross-run ownership ledgers (a2 rider #50743), never under $G.
# The ROOT is short (a1 BC-1): a resident's scratchpad TMPDIR is ~80 bytes, `$TMPDIR/g.XXXXXX` then ~90, and a socket a
# gate binds below it passes AF_UNIX's 108-byte sun_path. So a TMPDIR longer than 40 bytes is not inherited: $G roots at
# /tmp, and the first gate logs which root was used.
GATE_ROOT=${TMPDIR:-/tmp}
GATE_ROOT_WHY="TMPDIR (${#GATE_ROOT} bytes)"
if [ "${#GATE_ROOT}" -gt 40 ]; then GATE_ROOT_WHY="/tmp, not the ${#GATE_ROOT}-byte TMPDIR (AF_UNIX's 108-byte path)"; GATE_ROOT=/tmp; fi
GATE_ROOT_LOGGED=""
GATE_DIR=""
# Cleanup by OWN $G (a1 F3, a3 R3-3): a descendant that left the gate's process group (start_new_session) survives the group
# kill, still writing into $G. Every descendant inherited TMPDIR=$G and a chromium names its profile under $G, so those
# marks ARE ownership: the processes carrying them are killed, then $G is removed. Only file NAMES are read from /proc.
# The cmdline pattern is the path regex-ESCAPED, so this grep's own argv (`g\.XXXXXX`) never carries the literal it looks
# for. No terminator: mktemp's suffix is fixed-length, so no other gate's dir has this one as a prefix.
_gate_dir_rm() {
  local d=$GATE_DIR p pids re
  GATE_DIR=""
  [ -n "$d" ] || return 0
  re=$(printf '%s' "$d" | sed 's/[][\.*^$+?(){}|]/\\&/g')
  pids=$( { grep -lasF -- "TMPDIR=$d" /proc/[0-9]*/environ; grep -lasE -- "$re" /proc/[0-9]*/cmdline; } 2>/dev/null \
          | sed -n 's#^/proc/\([0-9]*\)/.*#\1#p' | sort -u)
  for p in $pids; do [ "$p" != "$$" ] && [ "$p" != "$BASHPID" ] && kill -KILL "$p" 2>/dev/null; done
  rm -rf -- "$d" 2>/dev/null || { sleep 0.2; rm -rf -- "$d" 2>/dev/null; }
  [ -e "$d" ] && printf '  NOTE  the gate dir %s outlived its cleanup\n' "$d"
  return 0
}
_gate_reap() {
  local j targets n
  # `jobs -p` is safe ONLY because check.sh backgrounds exactly one command, run()'s gate, which run() always waits
  # (a finished-but-unwaited job would linger here by a stale pid). tests/test_check_gate_cap.py pins that invariant.
  targets="$GATE_PGID $(jobs -p)"
  GATE_PGID=""
  for j in $targets; do kill -TERM -- "-$j" 2>/dev/null || kill -TERM "$j" 2>/dev/null; done
  for n in 1 2 3 4 5 6 7 8 9 10; do
    local live=""
    for j in $targets; do kill -0 "$j" 2>/dev/null && live="$live $j"; done
    [ -z "$live" ] && return 0
    sleep 0.1
  done
  for j in $targets; do kill -KILL -- "-$j" 2>/dev/null || kill -KILL "$j" 2>/dev/null; done
}
trap '_gate_reap; _gate_dir_rm; rm -f "$GATE_OUT"' EXIT
trap '_gate_reap; _gate_dir_rm; exit 130' INT
trap '_gate_reap; _gate_dir_rm; exit 143' TERM
run() {
  local cap=$GATE_CAP
  if [[ ${1:-} == --cap=* ]]; then cap=${1#--cap=}; shift; fi
  local label=$1; shift
  printf '\033[36m▶\033[0m %s\n' "$label"
  if ! [[ $cap =~ ^[1-9][0-9]*$ ]]; then        # whole seconds only: the wall judge compares integer SECONDS
    fail=1; FAILED+=("$label (bad cap '$cap')"); printf '\033[31m  ✗ %s — bad cap %q (whole seconds)\033[0m\n' "$label" "$cap"
    return
  fi
  local out rc t0=$SECONDS timed_out=""
  if [ -z "$GATE_ROOT_LOGGED" ]; then printf '  (each gate gets its own TMPDIR under %s, rooted at %s)\n' "$GATE_ROOT" "$GATE_ROOT_WHY"; GATE_ROOT_LOGGED=1; fi
  if ! GATE_DIR=$(mktemp -d "$GATE_ROOT/g.XXXXXX"); then
    GATE_DIR=""; fail=1; FAILED+=("$label (no gate dir under $GATE_ROOT)"); printf '\033[31m  ✗ %s — could not make its own dir under %s\033[0m\n' "$label" "$GATE_ROOT"
    return
  fi
  ASTRYX_SQLGUARD_GATE="$label" TMPDIR="$GATE_DIR" XDG_CACHE_HOME="$GATE_DIR/cache" VITE_CACHE_DIR="$GATE_DIR/vite" \
    timeout -k "$GATE_KILL_AFTER" "$cap" "$@" >"$GATE_OUT" 2>&1 </dev/null &
  GATE_PGID=$!          # timeout makes itself its group's leader, so its pid IS the gate's process group id
  wait "$GATE_PGID"; rc=$?
  GATE_PGID=""
  _gate_dir_rm
  out=$(cat "$GATE_OUT")
  printf '%s\n' "$out"
  # 124 is timeout's own expiry code (137 after the SIGKILL); a gate can also exit 124 itself, so the WALL is the judge
  if { [ "$rc" = 124 ] || [ "$rc" = 137 ]; } && [ $((SECONDS - t0)) -ge "$cap" ]; then timed_out=1; fi
  # optional per-gate timing, so a cap is set from measured durations rather than guessed (one tsv row per gate)
  [ -n "$GATE_TIMES_FILE" ] && printf '%s\t%s\t%s\n' "$((SECONDS - t0))" "$rc" "$label" >> "$GATE_TIMES_FILE"
  # The belt. A gate that ANNOUNCES a skip and still exits 0 has broken the protocol —
  # it is the exact defect this accounting exists to catch, so it is reported as a
  # violation rather than quietly trusted. Narrow by construction: only a line whose
  # first non-space token is SKIP or ○ counts, so a passing test whose NAME contains
  # "skipped" (test_plan_lifecycle has one) can never trip it. So a leading ○ or SKIP IS a skip
  # announcement: never use either as a neutral marker in a gate's output (sqlguard enforce did, and
  # its admitted rows read an enforcing gate as UNVERIFIED on every run; seed #24103). This belt can only ever
  # ADD strictness — it cannot turn a real skip into a pass — so both the exit code and
  # the announcement must fail before a vacuous gate reads green.
  # here-string, NOT `printf | grep -q`: the pipe form is the SIGPIPE/pipefail race seed
  # fixed in restore_verify.sh (2026-08-14). grep -q exits on the first match, printf takes
  # SIGPIPE, and `set -o pipefail` reports the pipeline FAILED though grep succeeded — so the
  # belt silently does not fire and the gate is counted verified on its own exit code. That
  # is the fail-OPEN direction, the inverse of restore_verify's false-RED. Measured on this
  # construct: 0/200 misses at 200 lines, 198/200 at 2000, 200/200 at 20000 (deterministic
  # once output exceeds the 64KB pipe buffer with the SKIP line early). Latent today — the
  # largest real gate emits 3956 bytes — but it fails silently, so it is fixed by shape
  # rather than left to a margin. (abstractor-1)
  if [ "$rc" = 0 ] && grep -qE '^[[:space:]]*(SKIP|○)' <<<"$out"; then
    rc=$EXIT_SKIP; LIARS+=("$label")
  fi
  # sqlguard (goal 4243): the effective rc per gate. The judge reads this to decide whether a site's NEGATIVE
  # verdict saw a complete search (C1: every covering gate exited 0).
  [ -n "${ASTRYX_SQLGUARD_DIR:-}" ] && printf '%s\t%s\n' "$label" "$rc" >> "$ASTRYX_SQLGUARD_DIR/gates.tsv"
  if [ -n "$timed_out" ]; then
    fail=1; FAILED+=("$label (TIMED OUT after ${cap}s)")
    printf '\033[31m  ✗ %s — TIMED OUT after %ss (its process group was killed)\033[0m\n' "$label" "$cap"
    return
  fi
  case $rc in
    0)  verified=$((verified+1)); printf '\033[32m  ✓ %s\033[0m\n' "$label" ;;
    "$EXIT_SKIP")
        UNVERIFIED+=("$label")
        printf '\033[33m  ○ %s — VERIFIED NOTHING this run\033[0m\n' "$label" ;;
    *)  fail=1; FAILED+=("$label"); printf '\033[31m  ✗ %s\033[0m\n' "$label" ;;
  esac
}
# A gate whose PREREQUISITE is absent is itself unverified — never silently omitted.
skip() { [ -n "${ASTRYX_SQLGUARD_DIR:-}" ] && printf '%s\t77\n' "$1" >> "$ASTRYX_SQLGUARD_DIR/gates.tsv"
  UNVERIFIED+=("$1"); printf '\033[33m○\033[0m %s — VERIFIED NOTHING (%s)\n' "$1" "$2"; }

# KEEP ON RED ONLY (seed #61226, goal 11580): the sqlguard trace dir this run MADE is removed on a green verdict and
# kept on a red one, its path named on the line above the verdict line, for a reviewer to read the traces. Each
# run used to leave it in tmpfs /tmp: 129 a day, 45 MB (steward #61225). Only a dir check.sh itself created is
# ever removed: branch_check, mutation_probe, sqlsite and several oracles pass their OWN dir and read it after.
# So the ownership flag is set in the mktemp branch alone, unset here first (never inherited from the
# environment), and NEVER exported. test_check_verdict sources this file inside a real run and drives green
# verdicts, and an exported flag would let that child delete the parent's dir mid-suite.
unset _SQLGUARD_OWNED
_sqlguard_settle() {
  [ -n "${_SQLGUARD_OWNED:-}" ] && [ -n "${ASTRYX_SQLGUARD_DIR:-}" ] && [ -d "$ASTRYX_SQLGUARD_DIR" ] || return 0
  if [ "$1" = 0 ]; then
    rm -rf -- "$ASTRYX_SQLGUARD_DIR"
  else
    echo "sqlguard traces kept (red verdict): $ASTRYX_SQLGUARD_DIR"
  fi
}
verdict() {
  echo
  for l in "${LIARS[@]}"; do
    printf '\033[31mPROTOCOL\033[0m %s announced a skip and exited 0 — counted as UNVERIFIED.\n' "$l"
  done
  if [ "${#FAILED[@]}" != 0 ]; then
    printf 'FAILED (%d):\n' "${#FAILED[@]}"; printf '  ✗ %s\n' "${FAILED[@]}"
  fi
  if [ "${#UNVERIFIED[@]}" != 0 ]; then
    printf 'UNVERIFIED (%d) — this run did NOT check these; they are not evidence of anything:\n' "${#UNVERIFIED[@]}"
    printf '  ○ %s\n' "${UNVERIFIED[@]}"
  fi
  echo
  # The verdict may never out-claim its parts. "ALL" is spoken only when nothing skipped.
  # The rc is decided FIRST so the trace dir is settled before the verdict line, which stays the LAST `check:`
  # line every reader keys on (merge_check, branch_check, pushed_tree_check, check_watch, check_stamp).
  local rc=1
  if [ "$fail" = 0 ] && { [ "${#UNVERIFIED[@]}" = 0 ] || [ -n "${CHECK_ALLOW_SKIP:-}" ]; }; then rc=0; fi
  _sqlguard_settle "$rc"
  if [ "$fail" != 0 ]; then
    echo "check: FAILURES above — a committed invariant regressed"
  elif [ "${#UNVERIFIED[@]}" = 0 ]; then
    echo "check: ALL CODE INVARIANTS PASS ($verified gates verified)"
  elif [ -n "${CHECK_ALLOW_SKIP:-}" ]; then
    echo "check: $verified verified, ${#UNVERIFIED[@]} UNVERIFIED (skips allowed here) — NOT a full pass"
  else
    echo "check: $verified verified, ${#UNVERIFIED[@]} UNVERIFIED — a gate that observes nothing is RED here."
    echo "       Set CHECK_ALLOW_SKIP=1 only where the missing prerequisites are expected (a bare CI clone)."
  fi
  return "$rc"
}

# Sourcing hook for tests/test_check_verdict.py, which drives run()/skip()/verdict()
# against SYNTHETIC gates so the accounting is proven against THIS file rather than a
# copy of it. Everything above is definitions; everything below runs the real gates.
[ -n "${CHECK_LIB_ONLY:-}" ] && return 0

# FIRST, which astryx does this tree's python import? An installed copy (pip -e of another checkout, a PyPI
# wheel) shadows the tree for any process that doesn't start at its root, and every gate below would then
# pass code it never ran (plan-10224 D1). Runs before the sqlguard exports so no PYTHONPATH reaches it.
# Hermetic. Mutants: tests/mutants_identity_gate.py.
run "identity gate: this tree's python imports only this tree's astryx" "$PY" tests/test_identity_gate.py

# sqlguard (goal 4243): the driver shim rides every python gate as `sitecustomize`. check.sh sets
# all three ITSELF, because run_check runs this under pulse's bare systemd env (the runner-env law:
# ASTRYX_NODE/507e7ea). The run id names this run's fixture databases, so the leak arm only ever looks for
# its own prefix.
export ASTRYX_RUNSCOPE_TEST=1                # every run role a gate makes is a TEST role (runscope TEST_STAMP)
export ASTRYX_SQLGUARD_RUN="${ASTRYX_SQLGUARD_RUN:-r$(date +%s)x$$}"
if [ -z "${ASTRYX_SQLGUARD_DIR:-}" ]; then
  ASTRYX_SQLGUARD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sqlguard.XXXXXX")"; _SQLGUARD_OWNED=1   # ours: settled at verdict
fi
export ASTRYX_SQLGUARD_DIR
export PYTHONPATH="$PWD/src/astryx/security/sqlguard/shim${PYTHONPATH:+:$PYTHONPATH}"
echo "$ASTRYX_SQLGUARD_RUN" > "$ASTRYX_SQLGUARD_DIR/run_id"
# The canary proves THIS run's shim can observe: one statement through the REAL pulse_run.Ctx.sql. If it isn't
# RESPONSIVE, the whole sqlguard verdict is NOT SEARCHED (a check that can't observe says so).
run "sqlguard canary: the shim observes through the real Ctx.sql" "$PY" -m astryx.security.sqlguard.canary
run "sqlguard oracle: privacy (P1) + controls"          "$PY" tests/test_sqlguard.py
run "sqlguard shim: a fetchval counts its rows (one record, the value unchanged)" "$PY" tests/test_sqlguard_fetchval.py
run "sqlguard site forms: a bare verb is no statement, every caller names its form, drops only by safe use" "$PY" tests/test_sqlguard_forms.py
# a3 night-review 10-09: a range that re-texts a LISTED SQL literal without moving its ledger row is RED before
# merge, statically (plan-4918 was backed out twice for exactly that). Hermetic, ~2s. Reviewers run the tool:
#   venv/bin/python -m astryx.security.sqlguard.rekey <base> <head>
run "sqlguard rekey: a re-texted listed literal needs its ledger move" "$PY" tests/test_sqlguard_rekey.py
# plan-11908 D1-D3. Mutants: tests/mutants_sqlguard_seal.py (a3, 13 caught).
run "sqlguard seal: a grade is judged from sealed evidence, and every reader reads that seal" "$PY" tests/test_sqlguard_seal.py
# plan-11908 D5: only the timer advances sqlguard_seen. Mutants: tests/mutants_sqlguard_seen.py.
run "sqlguard seen: enforce is read-only on the seen-set clocks unless it is the timer" "$PY" tests/test_sqlguard_seen.py
# plan-11908 D6: the land judge (hermetic half; the f46eb3e5 replay needs the fixture DB).
# Mutants: tests/mutants_sqlguard_landjudge.py.
run "sqlguard land judge: a range that adds SQL sites is graded before it pushes" "$PY" tests/test_sqlguard_landjudge.py
run "sqlguard land judge replay: f46eb3e5 without its D4 arms is refused, with them it passes" "$PY" tests/test_sqlguard_landjudge_replay.py
# seed #56874 / a3 #56878: a hashed absent row's R-STALE says its own admitted date and reason, every path-shaped
# token masked when private. Hermetic. Mutants: tests/mutants_sqlguard_stale_reason.py.
run "sqlguard stale reason: a hashed absent row names its ledger text, never a private path" "$PY" tests/test_sqlguard_stale_reason.py
# runscope (plan-4918 R1): a run's databases, role and directory are torn down by OWNERSHIP, a run-owned template
# included; the stale sweep keys on (pid, start time); a lockfile naming a foreign role or path is refused; the
# server only ever sees a SCRAM verifier. Real roles/DBs, cleaned up independently. Mutants: tests/mutants_runscope.py.
run "runscope: teardown by ownership, stale sweep, foreign scopes refused" "$PY" tests/test_runscope.py
# branch_check prep (plan-4918 P0/P1): the P0-b precondition asks has_database_privilege (a NULL ACL is PUBLIC
# CONNECT), the cached extension template (keep set, escaped LIKE, no PUBLIC CONNECT, clonable by the NOSUPERUSER
# run role), the private repo, the estate copy that skips credential-bearing files, the branch-tree secret scan,
# the generated env, and no password on pg_dump argv. Mutants: tests/mutants_branch_check_prep.py.
run "branch_check prep: hardening precondition, template, repo, estate, env" "$PY" tests/test_branch_check_prep.py
# the base (R2): a real pg_dump of prod into a run-OWNED base the run role can write; prod only read. ~2.5 min.
run "branch_check base: prod restored into a run-owned base" "$PY" tests/test_branch_check_base.py
# branch_check sandbox (R3/R5): the allowlist holds from INSIDE (bwrap), every negative probe has its OUTSIDE
# positive control, and each probe FIRES on a planted breach (the live .env, the real HOME's .pgpass, the docker
# socket, an unhardened foreign DB). The probe run inside is the TOOL's copy, never the branch's.
# Mutants: tests/mutants_branch_check_sandbox.py.
run "branch_check sandbox: the boundary holds from inside, every probe falsifiable" "$PY" tests/test_branch_check_sandbox.py
# branch_check orchestrator (P2): check.sh's own sets compared, FLAKY != REGRESSED, a prod-reaching statement
# fails the run, and on an unhardened host the run REFUSES rc 77 naming P0-a and leaves nothing.
# Mutants: tests/mutants_branch_check.py.
run "branch_check: differential verdict, prod witness, clean refusal" "$PY" tests/test_branch_check.py
# init.sh's harden node (plan-4918 P0-a): a fresh org is born with no PUBLIC CONNECT on the databases it
# administers. Run against the oracle's own scratch DBs only, by name. Mutants: tests/mutants_init_harden.py.
run "init.sh harden: no PUBLIC CONNECT on the org's databases" "$PY" tests/test_init_harden.py
# init.sh's schema node (seed #38258): GREEN iff the database carries the stamp of the EXACT schema.sql last applied
# in full, so a pulled NEW table is applied, and a failed apply never reads green. On a scratch DB. Mutants:
# tests/mutants_init_schema.py.
run "init.sh schema: a changed schema.sql is re-applied, a failed apply stays RED" "$PY" tests/test_init_schema.py
# the tracked `astryx` link stays the RELATIVE init.sh: no host path, no churn, the PATH link untouched (seed #38930).
# Hermetic. Mutants: tests/mutants_init_link.py.
run "init.sh dispatcher link: the tracked astryx link stays relative" "$PY" tests/test_init_link.py
# init.sh starts in the repo however it's invoked: through the PATH link, a chain, or a relative link (a2 #39198).
# Hermetic. Mutants: tests/mutants_init_self_dir.py.
run "init.sh start directory: the repo, through any link to init.sh" "$PY" tests/test_init_self_dir.py
# ~/.local/bin/astryx is written only where nothing else owns it: a pip console script is never replaced (plan-10224).
run "init.sh PATH link: never over a console script" "$PY" tests/test_init_path_link.py
# The astryx package (plan-10224 S1/S3). The pulse imports astryx every minute: the root shim and src/astryx must be
# ONE module with ONE _registry on every path. paths: HOME's four rungs. config: the one .env reader/writer.
# cli: every verb's dispatch with subprocess stubbed; secrets hidden, written mode 600, never printed. All hermetic.
run "astryx package: one registry on every import path" "$PY" tests/test_astryx_registry.py
run "astryx paths: HOME resolves env > marker > checkout > ~/.astryx" "$PY" tests/test_astryx_paths.py
run "astryx config: the one .env reader, in-place 0600 writer" "$PY" tests/test_astryx_config.py
run "reorg census: moved roots are the repo root, every stub IS its module" "$PY" tests/test_reorg_roots.py
run "astryx cli: verbs dispatch, user errors calm, secrets never printed" "$PY" tests/test_astryx_cli.py
# The pulse's astryx-import canary: a shim with no src/astryx (mid-checkout) disables nothing and alarms once.
# Fixture DB. Mutants: tests/mutants_pulse_import_canary.py.
run "pulse canary: astryx won't import -> one alarm, every trigger stays enabled" "$PY" tests/test_pulse_import_canary.py
# devtools/merge_check.sh: the merged-tree chain before a merge request, base resolved ONCE (merge parent == control),
# a conflict refused (never a wrong tree), transient links removed. Hermetic. Mutants: tests/mutants_merge_check.py.
run "merge_check: one base read, conflicts refused, links removed" "$PY" tests/test_merge_check.py
# devtools/review_range.sh: a review range is the MERGE-BASE..the branch head, both read from git; --check refuses the
# merged-ONTO sha, an older base, a stale or unresolvable head (a4 night-review 10-12). Mutants: tests/mutants_review_range.py.
run "review_range: base is the merge-base, head is the branch, typed shas refused" "$PY" tests/test_review_range.py
# rebase_equiv (a4 night-review 10-21, per-commit replay per a3 #61571): a REBASED range is PROVEN the reviewed work
# only when each reviewed commit replays (merge-tree) onto its twin's parent as the twin's tree; a conflicted commit is
# HAND-RESOLVED (rc 3) unless its labelled fallback finds a difference; raw messages compared; a merge refused. Hermetic.
# Mutants: tests/mutants_rebase_equiv.py.
run "rebase_equiv: per-commit replay proves a rebase, hand resolutions named, raw messages equal" "$PY" tests/test_rebase_equiv.py
# devtools/marker.sh (a4 night-review 10-22): the author's pushed_tree_check clause for a merge-ready marker, read from
# git and the check, never typed: full shas, no timeout, refused when the branch moved or the check printed no verdict.
# Hermetic (stub checks). Mutants: tests/mutants_marker.py.
run "marker: the author's pushed_tree_check clause read from git and the check, never typed" "$PY" tests/test_marker.py
# devtools/review_live.py: branch code measured against the LIVE tree (repo_root rebound only for the extract), the
# child read-only by default and without ASTRYX_AGENT (a3 night-review 10-16, seed #56224). Mutants: tests/mutants_review_live.py.
run "review_live: branch code reads the live REPO, fixtures untouched, postgres read-only, no agent identity" "$PY" tests/test_review_live.py
# devtools/land.sh: the merger's half of a merge-ready marker: clean tracked tree, ff only, live bodies at the PASSed
# sha, the range's tests run without ASTRYX_AGENT, red rolls main back, the push rc read before the receipt
# (seed night-review 10-16). Mutants: tests/mutants_land.py.
run "land: ff only, clean tree, body sha, tests without agent identity, red rolls back, push rc read" "$PY" tests/test_land.py
# the database's SHAPE, which the stamp can't see (a1 #38264): live == a fresh apply of the schema files, table by
# table, column by column, with types. Catches a column added inside an existing CREATE TABLE IF NOT EXISTS (a no-op
# on a live host) and a hand DROP. Live read is read-only. Mutants: tests/mutants_schema_parity.py.
run "schema parity: the live catalog has every table and column the schema files define" "$PY" tests/test_schema_parity.py
# people library 1a: relation details readable only by people_cleared, the network layer by the resident role;
# the move's receipt; the writers' cutover. ACCIDENT-GRADE (a same-uid resident can read the superuser credential),
# proven on scratch roles and DBs. Mutants: tests/mutants_people_gate.py, tests/mutants_people_move.py.
run "people gate: details only to people_cleared, network to the resident (accident-grade)" "$PY" tests/test_people_gate.py
# The derived graph databases' DECLARED design (owner 10-10 via seed #42323 (b)): astryx_social / astryx_people hold one
# graph each, declared in social_age.DESIGN; drift = a missing or undeclared label, or any ad-hoc relation. Scratch AGE
# databases for the red arms; the live read is read-only.
run "derived graph DBs match their declared design" "$PY" tests/test_social_age_design.py
# The running postgres SERVER against its declared design, infra/pg (owner 10-10 "the design on github should match
# local"; F4): ports exactly loopback, the image, every -c setting's effective value, the extension versions the
# Dockerfile declares. Synthetic RED arms; the live read is read-only. Mutants: tests/mutants_pg_design.py.
run "the running postgres matches infra/pg" "$PY" tests/test_pg_design.py
# the restore seam (#5497): an empty data dir's initdb holds infra/pg/.env's placeholder while the restored ~/.pgpass holds
# the real value. pg_role_sync sets the role FROM the pgpass value (client-side SCRAM verifier; RED control on a throwaway
# role), and the drill walks docs/restore.md on a throwaway server from the declared image with a small fixture dump.
run "pg_role_sync: the role's password is set from the pgpass value, never printed" "$PY" tests/test_pg_role_sync.py
run "restore drill: an empty data dir restores, its role synced to the restored pgpass" "$PY" tests/test_restore_drill.py
# the privilege census 1b is decided on: statement classes by surface, DSN source by file. Hermetic.
# Mutants: tests/mutants_privilege_census.py.
run "privilege census: classes discriminate, surfaces and DSN sources assigned" "$PY" tests/test_privilege_census.py

run "charter resolver invariants"      "$PY" tests/test_charter.py
# org MCP write-tool role gate (t-org-grant): the genome/identity writes are governance-gated
# (cross-agent amend_charter refused for non-governance; set_persona self-only) so grant:org is
# safe to grant widely, while reads + benign writes (goals/economy/propose_goal/announce) stay
# OPEN — over-gating them would re-break abstractor read-access. DB-free; mutation-control arm.
run "org MCP write-tool role gate"     "$PY" tests/test_org_write_gate.py
run "tier floor invariants"            "$PY" tests/test_tier.py
run "dep coverage invariants"          "$PY" tests/test_deps.py
run "dep manifest covers all imports"  "$PY" src/astryx/core/deps.py coverage
# no committed .py static-imports a gitignored triggers module (2026-09-14, 3× recurring): such
# an import fails the line above IN A CLEAN CLONE ONLY (triggers/ empty → not first-party →
# reads as unmanifested third-party), an opaque push-blocker that points at the manifest not the
# cause. This STATIC guard catches it on the live host, before the clone gate does. Fix = load
# the gitignored body by path + skip-77 (test_spawn_drift), never static-import it.
run "no committed static triggers import" "$PY" tests/test_no_committed_triggers_import.py
# economy heat-definition drift (goal 3408, enforcement half): no live surface may compute
# heat Q as flux−budget (Φ−W). The live gate scans the tree; the oracle proves it RED.
# MIGRATED, not retired, in goal 4227 S1b: the budget columns are deprecated read-only with NO
# DROP and v1's frozen W stays in the econ rows, so a budget stays mixable into heat for as long
# as the org exists. S1b closed a2's launder (#21341): stores into local dicts are traced.
run "economy heat-definition (legend)" "$PY" src/astryx/econ/legend_guard.py
run "legend guard invariants"          "$PY" tests/test_legend_guard.py
# RETIRED in goal 4227 S1b (owner law 2026-09-29: no budgets): attribution_guard (credited value
# never exceeds shipped BUDGETS) and pay_the_author (resharing the shipped BUDGET to tool
# authors) conserved a quantity that no longer exists; their four lines and modules are removed,
# not left passing vacuously. The wash detector MIGRATES: v2 tool GDP already discounts
# self-use, so it now finds RINGS (A→B→…→A tool use, as strongly connected components over the
# GDP-counted edges) and reports their share of GDP — detection, never an actuator.
run "wash detector: v2 rings (live, report-only)" "$PY" src/astryx/econ/wash_detector.py
run "wash detector invariants"                    "$PY" tests/test_wash_detector.py
# economy-integrity (goal 3499): funded_by ATTRIBUTION, not prevention. The migration is
# idempotent, the legacy watermark separates pre-feature NULL from new-unfunded, the
# goals_done_stamp trigger stamps done_at (W-birth) WITHOUT rejecting any close (a superuser is
# unstoppable in-DB) — its funder-NAMING retired with budgets at goal 4227 S3 — and every W-bearing surface
# is labeled attribution-grade. Two oracles: the DB behaviour (throwaway-pg, RED-first) and
# the source labeling-parity drift guard (pure stdlib).
run "3499 funded_by attribution + W-birth intact" "$PY" tests/test_funded_by.py
# goal 4227 S3 (steward): the budget WRITERS retire — propose_goal and the observatory's goal_create
# stop writing budgets, goals_done_stamp stops naming funders — and goals.budget_tokens /
# spent_tokens / funded_by are FROZEN read-only by a DB trigger (kept, never dropped: v1 history).
# triggers.premium is excluded (the survival flag). Drives the REAL functions in a sqlguard fixture.
run "goal budgets frozen, writers retired (4227 S3)" "$PY" tests/test_goal_budget_frozen.py
run "3499 econ honest-labeling parity"            "$PY" tests/test_econ_labeling.py
# disk-guard (09-05 ENOSPC remediation): hermetic band-ladder oracle — the guard itself
# goes LIVE only when wired into the wa-bridge lifespan (BUILT ≠ DEPLOYED; wiring is a
# separate deliberate act on the live owner-lifeline). This line keeps the committed
# oracle invoked (coverage meta-oracle) and the ladder logic pinned meanwhile.
run "disk-guard: resource + timer-health stays learnable" "$PY" tests/test_disk_guard.py
# usage-authority (goal 3833): ONE FETCH/EXTRACT/SERVE for the account-usage gauge — the
# idle-fallback poll + the current_usage/usage_readings views unify five hand-copied readers
# and keep the gauge fresh when the org is idle. Hermetic (throwaway schema built from the
# real schema.sql DDL); every arm ships its RED control — gate, newest-good, error-clock,
# empty, tier(key-level/served/2 controls), read-census.
run "usage-authority: fresh-when-idle + tier + read-census" "$PY" tests/test_usage_poll.py
# mcp/memory ask() tier boundary (goal 3410): the SECOND wall for the ask server — an
# independent black-box proof that tier-private (un-admitted) nodes reach NEITHER the
# synthesized answer NOR the citations. Shares no code with memory's admit gate: it plants a
# secret-bearing Person, drives the real ask() over a throwaway AGE graph, and (arm B) removes
# the gate to confirm the secret WOULD leak — so the green means the gate, not a dead query.
# SKIPs 77 without a createdb role / installable AGE.
run "memory ask() hides tier-private data" "$PY" tests/test_memory_ask_tier.py
# mcp/memory window() synthesis-span picker (goal 3438 item-1, memory msg 17231): the span fed
# to the LLM must land on the RARE query discriminators, weighting each hit 1/page_freq so
# stopwords/page-generics can't swamp it (a raw-count window landed on a stopword-dense decoy
# and excluded the answer section). Hermetic, pure-stdlib, RED-first against count-based.
run "memory window() picks rare-term mass" "$PY" tests/test_memory_window.py
# tool ledger (goal 4227, S0): the REAL step hook, run as a subprocess into a throwaway schema
# (PGOPTIONS search_path, no public fallback), stamps each registered-tool call with its
# registry_id + result_bytes and NOTHING else (I5: a secret planted in command, args and result
# never reaches meta). Also: authorship derived from the steps ledger, a toolreg failure never
# costs the row, and the classifications table refuses a prompt-shaped label. RED-first against
# the pre-4227 hook; the arms that pass vacuously there are pinned by tests/mutants_tool_ledger.py.
run "tool ledger: ids only, ledger authorship" "$PY" tests/test_tool_ledger.py
# grep guard (a3 night-review 10-10; rule #12548/#40752): a recursive PLAIN grep rooted above a .gitignore is the
# ugrep shell function and silently skips the gitignored estate. Hermetic; mutants in tests/mutants_grep_guard.py.
run "grep guard: a blind recursive sweep is denied, the real binary never" "$PY" tests/test_grep_guard.py
run "fixture_db reaps a killed run's database, never a live one's" "$PY" tests/test_fixture_reaper.py
run "fixture stamps sign and check under one fixed search_path" "$PY" tests/test_fixture_sigpath.py
# Hands S1, the browser cell (plan-7862): per-lease default-deny egress, NO model-API pinhole, no
# secrets or mounts, kill = stop + wipe, and a lease dies at its STEP or WALL-TIME cap (seed #38260).
# The real executor drives the real images against a throwaway lease table, in its OWN namespace.
# Grade: prevention vs the external adversary (residents trusted, owner #38554). 77 without docker/images.
run "hands cell: per-lease egress, wipe on kill, step + wall caps" "$PY" tests/test_hands_cell.py
# Hands, the owner's design (plan-7862, 10-10: "use my laptop like i can do — nothing container"): each
# agent's own REAL desktop on this machine (headless sway + its own seat via wayvnc), watched, joined and
# stopped from the observatory. Two tools, text replies, a 960x600 view: the token budget is pinned.
run "hands desktop: real clicks/typing land, owner stop refuses, two small tools" "$PY" tests/test_hands_desktop.py
run "hands portal: a desk file chooser opens on the desk, never on the owner screen (seed 57131)" "$PY" tests/test_hands_portal.py
# The phone (plan-8675): the facade's census/allowlist/telemetry, the surface stamp, step.py's phone strip and the HELD
# leases, with no device (77 where the pinned upstream isn't installed). tests/test_android_device.py drives a REAL
# phone end to end; it boots a ~3 GB emulator for minutes, so it verifies only when asked (ANDROID_DEVICE_TEST=1)
# and otherwise reads UNVERIFIED here, never green.
run "phone facade: upstream census, allowlist, telemetry off, surface stamp, phone strip, HELD leases" "$PY" tests/test_phone_facade.py
run "android device: an agent drives Settings on a real phone (77 unless ANDROID_DEVICE_TEST=1 and set up)" "$PY" tests/test_android_device.py
# S2 (plan-8675): the phone in its own Hands desktop, stopped from the observatory's REAL routes; Hands can't reach it
# (allowlist pinned); one spelling of its name; the resume-near-a-laptop-act sweep; persistence by omission; and the
# VNC key never in the journal (in-process + one live owner connect). No phone needed.
run "phone view: owner stop via the real routes, Hands can't reach it, resume sweep, no key in the log" "$PY" tests/test_phone_view.py
run "phone view on a CI tree: with no .env its arms still run, never an import-time exit (seed 55410)" "$PY" tests/test_phone_view_ci.py
run "init.sh phonesweep: the phone resume sweep installs itself only where phones are opted in" "$PY" tests/test_init_phonesweep.py
# C5 (plan-8675): the Windows VM on demand. Opening its viewer claims the vm-slot then starts it (refused, naming the
# holder, while the phone has it); only a run that an open STARTED is ever stopped idle, asynchronously. Stand-in only.
run "windows on demand: claim before start, refuse naming the holder, idle stop only of its own starts" "$PY" tests/test_windows_ondemand.py
run "init.sh winidle: the Windows idle stop installs itself only where a Windows container exists" "$PY" tests/test_init_winidle.py
run "check.sh: gates run with no agent name (a child claude writes no turn as the caller)" "$PY" tests/test_check_noagent.py
# init.sh login probes (a2 #53059): the probe's claude -p runs the Stop hook, which wrote a fake turn to prod under the
# caller's inherited ASTRYX_AGENT. A fake claude on PATH sees it UNSET; static: every claude -p carries env -u.
run "init.sh login probes: claude -p runs with no agent name (writes no turn)" "$PY" tests/test_init_probe_agent.py
run "station: a stationed agent runs claude -p under its OWN name, never the name of its caller (seed 53066)" "$PY" tests/test_station_agent_env.py
# Hands caps (seed's binding item, #44137): a STEP and a WALL-TIME cap per AGENT session, refusing with the cap named;
# idle resets a session, a loop stays capped; atomic across processes; charged before any desktop is touched.
run "hands caps: per-agent step + wall caps, idle reset, atomic, charged before the desktop" "$PY" tests/test_hands_caps.py
run "hands errors: a failed tool says its exit code or signal, never an empty error (the canopus grim report)" "$PY" tests/test_hands_run_errors.py
# every org's database is localhost-only (owner 10-10): doctor's _pg_exposure, with ss that can't answer → UNVERIFIED
run "doctor: postgres localhost-only, unverified when ss can't answer" bash tests/test_doctor_pg_exposure.sh
# goal 10224 S3: doctor's WSL/systemd checks, the docker host address order, install.sh's dry-run (installs nothing)
run "install + platform: WSL/systemd doctor checks, docker host address order, install.sh dry-run runs nothing" bash tests/test_install_platform.sh
# turns retention (owner 10-10: "add retention to save space"): old turns lose image bytes, keep their words
run "turns retention: old images stripped, words kept, recent untouched, idempotent" "$PY" tests/test_turns_retention.py
# deploy.sh restart's failure paths, all side effects stubbed: a refusing spawn is a named ✗, the run continues,
# ends INCOMPLETE, and the pulse is started again (a2 #42367)
run "cog_add_org: an org's own setup path, every step judged first, nothing made on a dry-run (plan-11324 S3f S5)" "$PY" tests/test_cog_add_org.py
run "org names: each org of a cog under its own federation name (10224 NAMES)" "$PY" tests/test_org_names.py
run "env reader: every Python .env read goes through config.read_env, per line, a bad line skipped loudly (10224 ENVREAD)" "$PY" tests/test_envread.py
run "org auth: each org of a cog runs its agents on its own login, never another org's (10224 ORGAUTH)" "$PY" tests/test_org_auth.py
run "org backup: a cog org's own dump and restore-verify triggers, the shims' one source (plan-10224 add-org-parity)" "$PY" tests/test_org_backup.py
run "init.sh schedules a one-org backup, deferentially by either name (seed 61526)" "$PY" tests/test_init_orgbackup.py
run "cog rehearsal: the runbook's steps 2-6 end to end on a fixture registry, the double spawn seen and refused (plan-11324 S3f S6)" "$PY" tests/test_cog_rehearsal.py
run "doctor in a cog: the primary served, its units-drift its own units only, its seats on its own server; another org refused (plan-11324 S3f S7)" "$PY" tests/test_doctor_cog.py
run "ops cog: pause, smoke, refresh and vitals act on THIS org in a cog (plan-11324 S3f S4)" "$PY" tests/test_ops_cog.py
run "wall cog: one wall of every org's agents titled agent@org, each pane from its own org's table, each bell to its own org; one org as before" "$PY" tests/test_wall_cog.py
run "deploy cog: each org's own units, only the primary touches the database, the cog's gateway and front say so (plan-11324 S3f S4)" "$PY" tests/test_deploy_cog.py
run "deploy restart: a failed resident is named, the run continues, the pulse comes back" bash tests/test_deploy_restart.sh
run "context compact: /compact reaches only the named session (exact tmux target, no prefix fallback)" "$PY" tests/test_compact_exact_target.py
run "tmux: no pane command targets a bare =session (capture-pane on \"=ax-x\" fails silently: 09-29 idle gates, 10-10 restart)" "$PY" tests/test_tmux_targets.py
run "the Room: addressing, the wire message, voiceprint lines, every reply kind spoken or acted (owner brief 10-11)" "$PY" tests/test_room.py
run "the Room's SQL on a fixture schema: voiceprints, the router, the ear's speaker stamp, the speaker's claim/voice/ask" "$PY" tests/test_room_db.py
run "channel oracles: none stages server.mjs without its sibling modules (10-11)" "$PY" tests/test_stage_channel_users.py
run "pushed_tree_check: the committed tree inherits no database or credential env (a4, 10-11)" "$PY" tests/test_pushed_tree_env.py
run "trigger_set: a python trigger name can never write outside triggers/<agent>/ (a2 #45063)" node tests/test_trigger_name.mjs
run "send: a malformed [[poll:]]/[[file:]] to a human surface is refused before the INSERT, in parity with the bridge grammar" node tests/test_send_embeds.mjs
run "bridges: a [[file:]] embed is read only from the SENDER's roots (home, scratchpad, media/; tier/ to the owner alone), realpath + O_NOFOLLOW + /proc" "$PY" tests/test_embed_root.py
run "bridges: every real [[file:]] ever sent to a human, through the root rule (933 /tmp + 19814 tier/-to-group + 2 home dot-path embeds refused)" "$PY" tests/test_embed_root.py --census
run "observatory pilot: one action catalog, matrix-gated executor, handler parity (plan-9000 S1)" "$PY" tests/test_pilot_s1.py
run "observatory pilot: the owner-tap confirm under trusted input in chromium (plan-9000 S1 arms i-v)" node tests/pilot_browser_test.mjs
run "concurrent browser gates: two pilots and two voice orbs 1 s apart, a squatter on the old ports, each gate's own vite cache (plan-10108)" "$PY" tests/test_gate_concurrency.py
run "observatory pilot: what leaves for the realtime provider is the allowlisted projection only (plan-9000 S2, C1)" node tests/pilot_egress_test.ts observatory/pilot/catalog.json
run "observatory pilot voice: owner-only routes, one ledger and one cap across canvas and the observatory (plan-9000 S2, C4)" "$PY" tests/test_pilot_voice_server.py
run "deploy build: a failed build or restart stops the deploy, the build runs as the caller, the banner prints no key" bash tests/test_deploy_build.sh
# geoloc /recent (a3 #32078, privacy): location history needs GEOLOC_TOKEN even from localhost, the
# token compare is constant-time, and a malformed ingest token is a 401, never a 500. The body
# (bridges/geoloc.py) is gitignored, so this SKIPs 77 on a clean clone. No location data is used.
run "geoloc /recent: token required, localhost included" "$PY" tests/test_geoloc_recent_auth.py
# the registry door's find() (steward #25795): whole-token matching (no "is" inside "list"),
# 4+ char prefixes either way (healthy/health), stopwords dropped, IDF-weighted, and a relative
# floor that drops common-word-only matches. Fixture registry, RED against the substring ranker.
run "toolreg find ranks the tool a question is about" "$PY" tests/test_toolreg_find.py
# observatory without budget economics (goal 4227 follow-up, a2 #23159): no component renders
# spent_tokens (never written: 0 means never measured), sends a budget, or draws a budget bar;
# a legacy budget_tokens is labelled "budget-era". Scans the TSX with comments stripped.
run "observatory renders no budget economics" "$PY" tests/test_observatory_no_budget_ui.py
# steps doorbell owner-match (a4 #22117, defense in depth): a payload {id, agent} resolves only
# to a step OF THAT AGENT, in both consumers: the REAL channel server against a throwaway DB (a
# forged payload pushes nothing, with a positive control landed AFTER it), and the bridges'
# step_line on a real pool, whose agent= is a required keyword every caller passes.
run "steps doorbell resolves only the named agent's step" "$PY" tests/test_step_doorbell.py
# bridge reply routing (seed #33250): an unaddressed human reply on a discord/whatsapp/telegram
# thread goes to the newest agent-bearing row there (the human's last chat OR poll target, or an
# agent's own last message); the surface default only when none. Synthetic threads, stamped fixture.
run "bridge replies route to who the thread is talking with" "$PY" tests/test_bridge_routing.py
run "whatsapp /hook: one message, one wire row, however its webhooks arrive" "$PY" tests/test_wa_hook_dedup.py
run "whatsapp /hook: every inbound file arrives as a path beside its caption, or says why not" "$PY" tests/test_wa_media.py
run "whatsapp: wacli retries only transient errors (store locked, 429), bounded" "$PY" tests/test_wa_retry.py
run "whatsapp /hook: a reaction to an agent's message reaches that agent" "$PY" tests/test_wa_reactions.py
run "workflows: one DAG converging on one agent, actuals measured from main (plan-11324 S4)" "$PY" tests/test_workflow.py
run "workflow SQL: load, goals, save and the observatory endpoint against a fixture database" "$PY" tests/test_workflow_sql.py
run "observatory overview: the header counts the tree's agents, never a charterless name" "$PY" tests/test_observatory_overview_roster.py
# the registry door (goal 4227, S4): find + run, and never a new capability. run() executes
# registered SCRIPTS only, as an argv list (no shell), with a clamped timeout, and never starts
# an MCP server, because that would walk past its charter grant. Mutants: tests/mutants_tools_door.py.
run "tools door: registered scripts only, no shell, no server" "$PY" tests/test_tools_door.py
# the registry's search text (medic): a tool is described by its OWN header. The docstring regex
# ran over shell scripts too, so a `'''` in code or a heredoc template described a tool by its body
# (mcp/new.sh was registered as its template's placeholder). RED-first against the unscoped regex.
run "toolreg: a tool's search text is its own header" "$PY" tests/test_toolreg_describe.py
# jobs MCP: a posting is "closed" only when the board says so; transport, 5xx, 429, shape and
# register-header failures are errors, never a false "closed". Hermetic (MockTransport, temp cache).
run "jobs MCP: fail-closed ATS status + sponsor-register lookup" "$PY" tests/test_jobs_mcp.py
# docpdf MCP: HTML→PDF is verified (pages, extractable text, page cap) and fails closed without
# touching a good PDF; paths confined to the root; the page fetches nothing (real Chromium vs a
# real loopback listener: 0 hits). Mutants: proxy flag removed → X3 RED; confinement off → 6 RED.
run "docpdf MCP: verified render, confined paths, no network from the page" "$PY" tests/test_docpdf_mcp.py
# gmail MCP: a Gmail query reaches IMAP byte-exact (quotes, backslash, non-ASCII, OR braces) as a
# literal; inlined as "{query}" any quote got BAD. Real imaplib vs a strict fake IMAP on loopback;
# the old inline form is the mutant and must fail the quote arm. Imports without .env.
run "gmail MCP: byte-exact search query, imports without .env" "$PY" tests/test_gmail_mcp.py
# the tool nudge, O5 (goal 4227, S4): the REAL UserPromptSubmit hook against a fake loopback
# classifier. It never exits non-zero (static, from the AST), stays silent and inside its hard
# deadline whether the classifier is unset/down/hung/DRIPPING, refuses non-loopback endpoints
# without connecting, never classifies content-private agents, persists labels only, and
# nudges on RECURRENCE, not difficulty. Mutants: tests/mutants_nudge.py.
run "tool nudge (O5): never blocks, never leaks, recurrence-gated" "$PY" tests/test_nudge.py
# spawn.sh --render + the S4 wiring (W1 + W3): the REAL generation path (fixture charters, shims
# for tmux/psql/claude/pgrep that log and touch nothing) renders a resident's home with NO side
# effect, and every resident gets the door and the nudge (own UserPromptSubmit group, timeout 3
# < usage.py's 5); stationed agents never get the door. Mutants: tests/mutants_spawn_wiring.py.
run "spawn --render: real generation, no side effect; S4 wiring" "$PY" tests/test_spawn_wiring.py
run "spawn --which-cli: the harness binary is resolved (mise, its install, PATH), never the boot wrapper" "$PY" tests/test_spawn_cli.py
# This suite's own blind spot: the list below is hand-maintained, so a newly committed
# tests/test_*.py was silently never run and this still printed ALL PASS (reproduced
# 08-13). Derives the expected set from the tests/test_*.py glob — a new oracle must
# be wired here or this goes RED. Pure stdlib, no DB.
run "check.sh runs every committed oracle" "$PY" tests/test_check_coverage.py
# The coverage gate's own trip condition, fired (its §2 predicted the case): an oracle
# outside the test_*.py glob — or any nucleus script — can land invoked-by-nothing and
# every gate stays green. This derives the population from git, parses real invocation
# syntax across tracked+out-of-tree surfaces (units, runners, triggers classified via
# check-ignore, never assumed), and fails any script neither reached nor exempted with
# a reason. Exit 77 when a surface is unreadable: it never accuses while blind.
run "every committed nucleus script is invoked" "$PY" tests/test_reachability.py
# The interim ratchet for the mutation estate (steward's ruling 08-15: the FULL probe run
# costs 100.6s and belongs in CI, not in the interactive loop — a gate slow enough to skip
# gets skipped). This is the sub-second structural half: every tests/mutants_*.py imports,
# declares SUBJECT/ORACLE/ENV/MUTANTS, points at files that exist, and still has patterns
# that apply. It asserts APPLICABILITY and never discrimination. Pure stdlib, no DB, ~0.1s.
run "mutants files still point at something real" "$PY" tests/test_mutants_wellformed.py
# mutation_probe REFUSING names its arm: the baseline oracle's own failing lines are printed, so a one-off loaded refusal
# is attributable (a4 night 10-16, memory #57741). Hermetic. Mutants: tests/mutants_mutation_probe_refusal.py.
run "mutation_probe: a refusing baseline prints its own failing lines (never a bare exit code)" "$PY" tests/test_mutation_probe_refusal.py
# mutation_probe's TREE form (a1 #62024, a4 #62026): a spec whose mutants span several files names each mutant's file, and
# every run happens in a fresh copy of the tree, never the checkout; the same baseline/canary/skip refusals as the single
# form. Hermetic (temp git trees). Mutants: tests/mutants_mutation_probe_tree.py.
run "mutation_probe tree form: multi-file specs, graded in a copy, with every refusal" "$PY" tests/test_mutation_probe_tree.py
# ...and the probe MACHINERY demonstrably runs (one family, ~4s). The full battery is the
# monthly steward trigger; this edge is what keeps probe_all/mutation_probe auto-reached.
# probe_all's REFUSED block keeps the probe's refusal HEADER (timeout vs red vs wiring fault), never only its tail
# (a1 #62229, a4 #62230). Hermetic: a stub probe in a temp tree. Mutants: tests/mutants_probe_all.py.
run "probe_all: a refused set shows the refusal's own header, then its last lines" "$PY" tests/test_probe_all.py
run "mutant machinery smoke (one family)" bash devtools/probe_all.sh --smoke
# The SECOND blind spot in this file, the same shape one level down: the gate above proves
# every oracle is INVOKED; this one proves an invoked oracle actually RAN. Drives this
# file's own run()/verdict() against synthetic gates. Pure stdlib, no DB.
run "a skip is not a pass (verdict accounting)" "$PY" tests/test_check_verdict.py
# per-gate wall clock (seed #45252): an expired gate is ✗ TIMED OUT and its whole process group dies; a signal to
# check.sh reaches the running gate. Driven through the REAL run() with stub gates and 1-2s caps.
run "check.sh gate cap: an expired gate is TIMED OUT and its group killed" "$PY" tests/test_check_gate_cap.py
run "check.sh registry pin: no gate sees the host's org registry; each runs as the checkout's own org (plan-11324 S3f S3)" "$PY" tests/test_check_registry_pin.py
run "check.sh gate dir: each gate gets its own short TMPDIR, and nothing of it outlives the gate (plan-10108 D1)" "$PY" tests/test_gate_dir.py
run "gate census: no literal port, probe-then-release or shared-root write in any gate's reach, unless declared (plan-10108 D4)" "$PY" tests/test_gate_census.py
# plan-10224 child-env-gate (seed #61406): no oracle hands a subprocess an env that silently drops the parent's cog
# registry pin (10-20: three reds and a masked fourth read /etc/astryx/cog.json). Hermetic AST. Mutants:
# tests/mutants_child_env_gate.py.
run "child-env gate: every subprocess env in tests/ carries the registry pin, provably plain, or declared (plan-10224)" "$PY" tests/test_child_env_gate.py
# steward 10-20: the review queue counts a medic/* branch's open work by PATCH (git cherry), never by sha; seed lands by
# replaying, so rev-list read every landed branch as open forever. Hermetic (a throwaway repo). Mutants:
# tests/mutants_pr_review.py.
run "pr_review: a branch's open work is counted by patch, so a replayed (landed) branch drops out of the queue" "$PY" tests/test_pr_review.py
# The gate on the OTHER actuator. .git/hooks/pre-push is a COPY of the tracked hooks/pre-push,
# so the reviewed artifact and the executed one are two writers of one fact with no reconciler
# — and privacy_gate already rides on that copy. Proves the installed hook matches byte for
# byte AND is executable (git skips a non-executable hook silently: byte-identical and inert).
# SKIPs loudly where no hook is installed — a fresh clone or CI legitimately has none, and
# that is not a pass: it means nothing gates a push there. Pure stdlib, no DB.
run "installed pre-push hook is the reviewed one" "$PY" tests/test_hook_integrity.py
run "...and the reviewed one still does the job" "$PY" tests/test_pre_push_contract.py
# The pushed-tree check runs check.sh under the hook's environment. From a linked worktree
# that environment carried GIT_DIR, and a test's `git init` re-initialized the SHARED repo as
# bare (2026-09-30). The oracle reproduces it on a throwaway repo (RED unfixed, GREEN fixed,
# main-tree CONTROL); the tripwire reads this repo's common config on every run, so any
# other path that flips core.bare is caught by the next check. Pure stdlib + git, ~1s.
run "a worktree push cannot reach the shared .git" "$PY" tests/test_git_env_isolation.py
run "the shared repo is not bare (core.bare tripwire)" "$PY" tests/test_git_env_isolation.py --tripwire
# The org's PII detector, gated on the two properties that failed in the field: a finding
# is silenced only by REPAIR or by an explicit ruling (warn-once let a live finding sit
# unmentioned for 22 days), and the guard never emits the shape it hunts (an unmasked
# `messages.thread` put a group JID into its own alarm, msg#344). Hermetic — synthetic
# fixtures, no DB, no live estate. SKIPs by name where triggers/ is absent, which is every
# clean checkout: there the guard is not here to be verified. ~0.3s.
run "pii_sweep cannot forget a finding or print a routing id" "$PY" tests/test_pii_sweep_ledger.py
# CANVAS privacy (steward, seed #35151): pii_canvas sweeps every canvas version + live value (history is
# guest-readable via ?v=N), REACH-tagged; its state IS the share gate, src/astryx/core/canvas.py:share_blockers,
# which fails closed. Fixture DB only. The gate arms always run; the sweep arms SKIP 77 without the body.
run "canvas: privacy sweep + fail-closed share gate" "$PY" tests/test_pii_canvas.py
run "send: a name nothing consumes is refused in the sender's turn" "$PY" tests/test_send_address.py
# The guard that reads THIS suite's own live-tree result. check.sh runs automatically in
# exactly two places and both are clones, where the gitignored estate cannot exist — so
# devtools/check_watch.sh runs it here on a timer and stamps the outcome, and the guard
# reads the stamp. Gated on the three ways such a guard goes quiet: a standing red that
# warns once, a stopped runner whose silence reads as health, and an unparseable stamp
# read as all-clear. Hermetic (temp stamp, fake ctx); SKIPs by name where triggers/ is
# absent. ~0.2s.
run "live-tree check guard can't go quiet" "$PY" tests/test_check_stamp.py
run "live-tree stamp says what ran it" "$PY" tests/test_check_watch.py
run "metabolism patrol invariants" "$PY" tests/test_stale_goals.py
run "out-of-band doorbell is watched" "$PY" tests/test_doorbell_proof.py
# ship_watch (goal 3909): vanish and fresh are DECOUPLED (a standing removal no longer masks a
# concurrent fresh ship, on both the shared _watch and the inline trigger_ship_watch), and a
# removal is auto-ACK'd out of the standing nag ONLY on an independent positive trace
# (grant/tool/mcp git commit, one-shot goal='done'); the traceless geoloc/hand-deleted set
# stays flagged. Drives both bodies with a fake ctx; the discrimination arm's controls are real
# git (grant:geoloc traced vs mcp:geoloc gitignored). Gitignored subject -> SKIP 77 on a clean
# clone. ~0.5s.
run "ship_watch decouple + traced auto-ACK" "$PY" tests/test_ship_watch.py
# The out-of-pulse clock witness — the guard that replaced the deleted nucleus/pulse_watch.py
# after the one-clock ruling. It rides the whatsapp bridge's own loop (no second timer),
# reads max(triggers.last_eval), and doorbells the owner when astryx-pulse.timer looks dead.
# This proves the classifier's polarity (stale/fresh/UNKNOWN), the standing-condition re-nag
# and re-arm, and the actuator's two lifeline properties: it CAN fire, and it fails OPEN (a
# DB blip never rings, never clears the latch, never raises into the delivery loop). Pure
# stdlib, no DB, no wire — the I/O seams are injected. ~0.1s.
run "pulse witness: clock death stays learnable" "$PY" tests/test_pulse_witness.py

# THE INSTRUMENT, NOT THE ESTATE. devtools/glob_vacuity.py runs the whole suite under a
# shim to find globs that match nothing and pass anyway (forge's *.json against a
# *.jsonl archive, dormant for the life of the org). That sweep is minutes long and
# needs the live estate, so it stays a manual tool — but its SELFTEST is ~1s and plants
# a dormant glob it must find. Gating the selftest keeps the instrument from rotting
# without putting a multi-minute sweep in the fast loop; a tool that can no longer find
# a planted defect reports "none dormant" in exactly the same words as a clean estate.
run "glob-vacuity can still find a planted dormant glob" "$PY" devtools/glob_vacuity.py --selftest
run "referral opt-in + static-literal" bash devtools/referral_guard.sh
# its ORACLE (plan-10224 S2F, seed #61794): the guard on ~1 MB producers, the offending line first, 3 runs each, because
# its pipe-into-grep -q form passed on SIGPIPE under pipefail. Hermetic fixture trees. Mutants: tests/mutants_referral_guard.py.
run "referral_guard oracle: a leaked or fetched referral FAILs on any producer size" "$PY" tests/test_referral_guard.py
# the CLASS (plan-10224 S2F): no `producer | grep -q` in a tracked shell file that turns pipefail on. grep -q exits at its
# first match, the producer takes SIGPIPE, and pipefail reads the match as a failure (restore_verify 08-14, check.sh's
# belt, sqlsite 10-21). Capture, then grep -q <<<"$v". The race itself is measured, and a parser arm pairs every shape.
run "pipefail early-exit readers: no grep -q/-m/-l, head or sed q whose pipeline status is a condition (SIGPIPE reads a match as a failure)" "$PY" tests/test_pipefail_grep_q.py
# OKF frontmatter for the memory estate. The invariant is ADDITIVITY: attaching metadata
# must change nothing the three live lints read. Pure stdlib; the arms that touch the real
# estate skip on a clean checkout (memory/ is gitignored), and the PyYAML cross-check arm
# runs only where PyYAML happens to be importable — it is not a dependency.
run "OKF frontmatter additivity"      "$PY" tests/test_okf.py
# The recall-graph compiler. Its load-bearing arm is CONFORMANCE: the page-link set it
# extracts must equal the trusted link guard's — _wiki_links() in memory/lints/drift.py (the
# reconstructed link_integrity) — edge for edge, or the graph and the lint watching the same
# files disagree with nothing to arbitrate. Pure stdlib; the estate arms skip loudly on a
# clean checkout, and the wire layer is never touched here.
run "recall-graph compiler"           "$PY" tests/test_memgraph.py
# plan-8018 S-retire: the kg schema is retired (the graph compiles on request); no tracked file may name a kg
# relation again outside the dated-history exemptions. Pure stdlib + git; works on a clean checkout.
run "kg retired: no tracked file names a kg relation (8018 S-retire)" "$PY" tests/test_kg_retired.py
# Its ESTATE leg, a gate of its own: the same pattern and exempt list over the gitignored memory/**/*.py and
# triggers/**/*.py, where the old graph's writers lived. 77 (UNVERIFIED) where triggers/ is absent; planted RED/CONTROL arms.
run "kg retired, estate leg: no memory/ or triggers/ .py names a kg relation (8018 S-retire)" "$PY" tests/test_kg_retired_estate.py
# Its LIVE leg: the database itself, read-only (the schema was dropped 2026-10-16); planted RED/CONTROL on fixtures. 77 with no DB.
run "kg retired, live leg: the database holds no kg schema (8018 S-retire)" "$PY" tests/test_kg_retired_live.py
run "another checkout of this repo: one shared predicate for every walker, a foreign repo still walked, an unknown source named (seed 53453)" "$PY" tests/test_checkouts.py
run "derived-copy registry: digests + writer count (8018 S1)" "$PY" tests/test_copies.py
run "derived-copy registry: the graph builder stamps its own digest (8018 S1)" "$PY" tests/test_copies_builder.py
# The typed layer's lint. Every finding must be FALSIFIABLE and every expected field set
# DERIVED from the corpus — a hand-kept list would be the drift class this org has hit
# five ways. Named for the false positive it prevents: the lint's first version condemned
# `goal`, a type with a real shared core AND a long narrative tail, as a bucket.
run "ontology lint invariants"        "$PY" tests/test_ontology.py
# Every name a trigger file references must resolve. Earned when three agents edited one
# trigger file in two hours and a dropped helper left another author's function throwing
# on every tick — a defect no per-proposal oracle can see, because each tests its own
# function against its own staged copy. SKIPS where triggers/ or pyflakes is absent.
run "trigger bodies resolve"          "$PY" tests/test_trigger_smoke.py
run "no undefined name in any tracked .py (pyflakes; a deleted class under a lazy 3.14 annotation hid a 3.12 import crash)" "$PY" tests/test_undefined_names.py
# ...and the half of that family pyflakes can't see: a name bound somewhere, but not yet when an import-time annotation
# runs (a later class, a class naming itself, a TYPE_CHECKING-only import). Fixtures checked against a real 3.12.
run "no import-time annotation names a not-yet-bound name (3.12 NameError, hidden by lazy 3.14)" "$PY" tests/test_eager_annotations.py
# plan-9853 D2: a python trigger's retirement is trigger_rm's per-(agent, name) TOMBSTONE, which the pulse honours (it
# used to re-enable the row within a minute); trigger_set clears it. Runs tests/test_tombstone.mjs (the wiring) too.
run "trigger tombstone: trigger_rm retires a python trigger for good, per agent and name" "$PY" tests/test_trigger_tombstone.py
run "fixture gates with no database: 77 on a committed-only tree, 1 on a live host, never a traceback (seed 54113)" "$PY" tests/test_fixture_unavailable.py
# plan-9853 D1/D3/D4: "is trigger N installed?" is ONE helper modelling the pulse (checked against discover()), and
# every init.sh trigger install asks it by NAME
run "trigger names: the pulse's registration model (closure, blind → defer, retired per target, legacy, parity)" "$PY" tests/test_trigger_names.py
run "agent heal: a dead resident body is respawned, a DEAF idle one restarted (busy never cut), live ones never touched, crash loops stop, a blind tmux or db acts on nothing" "$PY" tests/test_agent_heal.py
run "agent heal arm two: its pending-rows SQL in a fixture" "$PY" tests/test_agent_heal_sql.py
run "launch flags: a body missing the channel flag or its charter's permission mode is named" "$PY" tests/test_launch_flags.py
# plan-11859 U5 (D10): the CLI adapter table is the one source of a resident's launch: spawn types its line, every value
# quoted; a CLI with no launcher refuses; a table that can't launch on the wire is refused at load. Mutants:
# tests/mutants_cli_adapters.py, tests/mutants_spawn_launch.py.
run "cli adapters: spawn types the table's line, today's argv for every live value, one argument for any other (U5)" "$PY" tests/test_cli_adapters.py
# goal 10224 S6: medic sends a framework fix upstream (fork + PR, never instance data, privacy-gated, deduped, capped,
# 77 without gh), and the upstream org's medic hears each outside PR once per head, fenced as DATA. A fake gh; no GitHub.
run "upstream PR tool: instance paths and privacy hits refused, dedup to a comment, the cap, fork or not, 77 without gh" "$PY" tests/test_upstream_pr.py
run "upstream PR watch: each outside PR reaches medic once per head, fenced as DATA; gh trouble said once per change" "$PY" tests/test_upstream_prs.py
run "init.sh trigger installs: by NAME through the helper, never over a retirement or a legacy row; --reinstall; census" "$PY" tests/test_init_trigger_names.py
# plan-11324 S3a: THE ORG IS ITS HOME. On a two-org fixture registry and an estate-free checkout, every process binds
# its own org's HOME, database and law (H1-H9); an org-B resident's pane carries none of org A's names (P1-P2); and the
# census finds no org-state read outside the resolvers, sees the pre-S3a class, and keeps both partitions total (C1-C5).
# Mutants: tests/mutants_org_home_*.py. With no registry (this host), nothing they test changes a byte.
run "org home: each org process binds its own HOME, DSN and law; the backup is the org's; one org is unchanged" "$PY" tests/test_org_home.py
run "restore row counts: an empty table restores as empty only where live is empty (seed 61553)" "$PY" tests/test_restore_counts.py
run "org home pane: an org-B resident's environment is built from HOME-B, none of org A's names" "$PY" tests/test_org_home_pane.py
run "org home units: each org's units are its own @<org> instance files, the partition (org_units.json) is total, one org is plain" "$PY" tests/test_org_home_units.py
run "gateway cog: one door serves every org of a cog by federation name; a sibling's row goes in process through its own door's checks" "$PY" tests/test_gateway_cog.py
run "gateway pickup: what a NAT'd org collects by long-polling passes the one inbound door (reach, intent, cap, replay)" "$PY" tests/test_gateway_pickup.py
run "cog scope: every registry iterator is declared (tests/cog_scope.json); only the design's cog-scoped set opens every org" "$PY" tests/test_cog_scope.py
run "observatory cog: the cog's front lists every org and pipes each to its own observatory, adding no authority" "$PY" tests/test_observatory_cog.py
# plan-11859 U0 (D3+D4): every relay applies ONE allowlist header policy (src/astryx/security/relay.py): only the
# destination's own cookie, never the caller's x-forwarded-* or X-Forwarded-For, the relay's observed view set; the
# observatory units pin their proxy trust. Hermetic (stub backends). Mutants: tests/mutants_relay_headers.py.
run "relay headers: one allowlist for every relay, the destination's own cookie only, the relay's observed view (plan-11859 D3)" "$PY" tests/test_relay_headers.py
# plan-11859 U0 (D6, BLOCKING from U0: a2 BC-1): no agent-/org-authored active content runs on the front's origin,
# which holds the owner key in localStorage. Client census (iframes sandboxed or EXEMPT with a reason, no allow-same-origin,
# no raw HTML sink, every dangerouslySetInnerHTML DOMPurify'd) + canvas's file serving. Mutants: tests/mutants_active_content.py.
run "active content: nothing an agent authored runs on the front's origin (plan-11859 D6)" "$PY" tests/test_active_content.py
# plan-11859 U0 (D5): every door the host opens to a network is classed (front | federation | bridge intake | host) or
# ACCUSED; tunnel targets are the front, the gateway or a declared surface; the declaration agrees with the socket table.
# Hermetic (fixtures): the LIVE run is host state and gates nothing. Mutants: tests/mutants_exposure_census.py.
run "exposure census: every listener classed or accused, every tunnel target the front (plan-11859 D5)" "$PY" tests/test_exposure_census.py
run "observatory cog UI: the building and its room chips, the key only to safe bases, one org as before" "$PY" tests/test_observatory_cog_ui.py
run "observatory sign-in UI: one flag, on in production builds, one answer for any failed sign-in (F8), your orgs not every room" "$PY" tests/test_observatory_auth_ui.py
run "observatory influence across orgs: owner only, crossing traffic aggregated per pair, no body or thread leaves" "$PY" tests/test_observatory_influence_cross.py
run "observatory cog new org: owner only, a legal key and name not already in the cog, one wire message to seed, one open request per key" "$PY" tests/test_observatory_cog_new_org.py
run "canvas cog: each org's canvas session at its own path under its own name; one org as before" "$PY" tests/test_canvas_cog.py
# plan-11859 U1+U2: one sign-in for the cog (the front: argon2id, server sessions, a configured origin, one answer for
# any failed sign-in), a 60 s Ed25519 identity per request naming WHO, and each org deciding WHAT from its own members
# table (D1 D2 D7 D8 D9, a3 N1). Mutants: tests/mutants_cog_identity.py, mutants_relay_response.py,
# mutants_cog_signin.py, mutants_backend_identity.py, mutants_cogauth_session.py, mutants_cogauth_cli.py.
run "cog identity: the signed token verified against its spec, the response-cookie rule, ONE owner predicate (U1+U2)" "$PY" tests/test_cog_identity.py
run "cog sign-in: the owner signs in and reaches his rooms with no key, the key still works, each org decides (U1+U2)" "$PY" tests/test_cog_signin.py
run "cog CLI: the one writer of accounts and memberships; the cog store's backup restores (U1+U2 D7 D8 D9)" "$PY" tests/test_cogauth_cli.py
# plan-11859 U4: the owner sets this org's agent login from the observatory (a subscription token, a metered key only with
# the billing confirmed, or neither), through the one .env writer, never a value back. Mutants: tests/mutants_org_login.py,
# tests/mutants_config_unset.py.
run "org login: the owner sets this org's agent login; metered only with the billing confirmed; no value back (U4)" "$PY" tests/test_org_login.py
run "sign-in burst: at most 2 password checks at once, 8 waiting, attempts counted from their start (U1U2-F)" "$PY" tests/test_signin_burst.py
run "org home namespace: each org's residents live on its own tmux server (two orgs, one agent name, two residents); one org is the default socket" "$PY" tests/test_org_home_namespace.py
run "org census: no org-state read outside the resolvers; the estate and environment partitions are total" "$PY" tests/test_org_home_census.py
run "org registry parity: orgs.py and home.mjs reach the same written verdict on every registry case (a2 A-1)" "$PY" tests/test_org_registry_parity.py

run "A2A card canonicalisation (JCS)" "$PY" tests/test_card_canon.py
# the org economy: G = W/(Φ·K), value enters only at the boundary (goals.done_at),
# heat <= flux, theil arms both ways, archived rollup self-consistent with its parts.
run "the org economy is honest"       "$PY" tests/test_econ.py
run "shed reads no value (4227 S1a)"   "$PY" tests/test_shed_s1a.py
# Mutants: tests/mutants_secretset.py (the hand mutations from the plan-5497 build, committed).
run "secret set + turn writer redaction (5497 S0+S1a)" "$PY" tests/test_secretset.py
run "secret guard keeps holders out of context (5497 S1b)" "$PY" tests/test_secret_guard.py
run "db password rotation leaks nothing (5497 S3b BC-1)" "$PY" tests/test_rotate_db_password.py
run "S1c-0 runner census cannot pass vacuously (5497)" "$PY" tests/test_dsn_census.py
run "S1c switch strips/restores DSN passwords with no copy (5497)" "$PY" tests/test_dsn_password.py
run "at-rest secret sweep redacts without corrupting (5497 S2)" "$PY" tests/test_secret_sweep.py
run "every trigger wake leaves through the pulse (4227 S1c)" "$PY" tests/test_wake_chokepoint.py
# The ear must outlive a database blip. Runs the REAL channel/server.mjs against a
# THROWAWAY database (created, then dropped — the org's own is never written to), breaks
# the database underneath it the two ways an ordinary `docker restart` does, and proves it
# both SURVIVED and still DELIVERS. Earned by forge going deaf 8h49m on 2026-08-14 while
# its body sat at a healthy prompt. Slow by nature (~35s: it waits out the server's own 15s
# startup drain, or a permanently deaf ear passes on that one-shot). SKIPS loudly without
# node, channel/node_modules, a reachable DB, or CREATE DATABASE rights — i.e. a bare clone.
run "channel ear survives a db blip"  "$PY" tests/test_ear_survival.py
# The other half of the same file: a wake DELIVERED into a void is lost forever, because
# `delivered` is set by the ear the instant it pushes, not by the body when it reads, and
# the startup drain sweeps `pending` only. Measured over 21 days: 69 messages reached no
# turn and no step before their agent's next boot; one roster respawn (08-15 07:37Z) ate
# nine agents' morning heartbeat, two of steward's losses being guard alarms. Recovery has
# TWO failure directions, so this drives both: the wake comes back, and nothing a turn or
# a step could have covered is ever served twice. Same cost and same skip conditions as
# the gate above, times three (it runs three server generations, ~35s each).
run "lost wakes recovered at spawn"   "$PY" tests/test_wake_recovery.py
# The Claude Code plugin (plan-10224 S7). The wire server runs from the plugin cache, far from the org: it finds
# .env/venv/nucleus under ASTRYX_HOME (the residents' `..` default is unchanged, proven by the oracles above), stays
# dormant with no database in a project that hasn't joined, and holds one body per agent under ASTRYX_ONE_BODY.
# The hooks act only in a joined project and check both launch flags (R2). The plugin repo is generated by
# devtools/build_plugin.py, and its copies must match this repo.
run "channel: ASTRYX_HOME portability, plugin dormancy, one body per agent" "$PY" tests/test_channel_home.py
run "plugin hooks: join-marker gate and the SessionStart flag check (R2)" "$PY" tests/test_plugin_hooks.py
run "plugin build: the generated plugin's copies match the repo (drift)" "$PY" tests/test_build_plugin.py
# goal #2470. The load-bearing gate is BC-2: the OAuth credential has EXACTLY ONE reader
# estate-wide and that module is not reachable in the observatory's import graph. Both
# halves are static, so this runs green on a clone with no credential; the live-token
# arms name themselves SKIP (77) rather than passing quietly. Also drives the modal
# NOT-CONFIGURED path, which is what most installs of this will actually be.
# The THIRD instance of "authored state in no repo and no backup" (triggers/ bodies,
# then agents/, then runners.conf + local.md + .env). This gate guards the CLASS: it
# derives the expected set from `git status --ignored` minus a manifest of the genuinely
# regenerable, so a NEW gitignored authored file that nobody adds to backup.sh goes RED.
# Membership in that manifest grants EXEMPTION, so forgetting accuses rather than excuses.
run "backup captures every gitignored input" "$PY" tests/test_backup_inputs.py
# goal #2457. wake_marker is the ONE definition of "was this wake consumed", replacing
# three copies that agreed only by promise (wake_audit held it, wedge_watch reproduced it
# in SQL while its docstring cited wake_audit as authoritative). The load-bearing gate is
# the CROSS: the SQL and the pure-python renderings are two forms of one decision and
# nothing but this makes them agree — driven over live rows, with a positive control that
# the sample exercises both verdicts.
run "wake_marker: one definition, two renderings" "$PY" tests/test_wake_marker.py
# goal #2457, the facility's pure decision layer. Drives the whole polarity table directly
# (pure subject, no DB) and asserts BC-4: the escalation layer may fail but may never take
# its caller down, so the worst case is today's in-band alarm and never silence.
run "escalation facility: polarity + collapse" "$PY" tests/test_escalation.py

# memory's oracles (msg 12486) — the lint family's first oracle, and the history half of
# goal #2470. Both live over the gitignored estate, so on a clean clone they exit 77
# with a named reason (amber-by-construction in CI); green only on the live host, which
# is what check_watch.sh exists for. The lints watched everyone's drift and nothing
# watched theirs until the index parser condemned a healthy line over one capital letter.
run "wiki/estate drift floor (5->1)"  "$PY" tests/test_drift.py
# The overnight-edition doorbell (triggers/memory/library_compile.py) and drift.py's compile_lag run their SQL
# through pulse_run's own Ctx in a stamped fixture, each site at 0 and >=1 rows (steward #37335). Both are
# gitignored, so a clean clone exits 77 with the reason named.
run "library_compile + compile_lag: SQL in a fixture"  "$PY" tests/test_library_compile.py
# plan-8018 S3: library.passage + BM25 library.search over the REAL (gitignored) ingest in a fixture DB; 77 where memory/ is absent
run "library passages + BM25 search: tier-clean, derive-at-use, DELETE-not-TRUNCATE, hand-oracle scores" "$PY" tests/test_library_passage.py
run "library search endpoint: book/wiki mapping, plain-text marks, blank q, unavailable not 500" "$PY" tests/test_library_search_api.py
run "people_essence: SQL in a fixture"  "$PY" tests/test_people_essence.py
run "influence_compute: SQL in a fixture"  "$PY" tests/test_influence_compute.py
# Class-1 of the prove-family oracle (scout, plan-15): drives all seven containment
# verdicts BOTH ways against synthetic trees via G15_ENVF/G15_SCAN_ROOTS. Its output
# states its own limit — decision logic only, not the real cell.
run "containment gate decision logic"  "$PY" tests/test_prove_containment.py
# Class 2: the two HOST-SIDE prove scripts at the logic layer, docker stubbed. A weaker claim
# than the gate above and it prints that limit in its own output — it proves these scripts CAN
# fail when they should, never that the cell is contained. Carries the RED-proof for the
# cell-liveness verdict added to prove_egress.sh (plan-15, granted msg 8846).
run "host-side prove scripts (logic)"  "$PY" tests/test_prove_hostside.py
# Needs psycopg + a live org DB; SKIPS loudly otherwise. Fixtures go in a rolled-back
# transaction (messages_notify is a pure pg_notify, so a rollback wakes nobody).
run "wake-audit classifier"           "$PY" tests/test_wake_audit.py
run "wedge-watch discriminator"       "$PY" tests/test_wedge_watch.py
# The DUTY-OUTPUT floor under wedge_watch, and the pair is the point: wedge_watch counts
# dropped WAKES (MIN_DROPS=2, measured and correct), but the exchange rate into TIME is the
# agent's wake frequency — for a once-daily seat two drops is two days. This asserts the
# guard that watches the OUTPUT instead. Fully hermetic (the ctx is injected, no DB), but
# the trigger BODY is gitignored, so it SKIPS loudly on a fresh clone.
run "brief-silence duty floor"        "$PY" tests/test_brief_silence.py
# A search whose EMPTY answer carries its own coverage. `grep` in a resident session is a
# shell FUNCTION wrapping ugrep with --ignore-files, so it honours .gitignore — and homes/
# is line 3 of it. For any seat working under homes/ (canopus, gemini, p1, p2, vega) a
# root-anchored typed grep returns a STRUCTURAL ZERO over that agent's own files: measured
# 0 vs 17. The gate is not "grep works"; it is that three states stay distinguishable —
# found (0), searched-and-empty (1), NOT SEARCHED (2) — because a bare 0 collapses the last
# two, and 0 is the most convincing possible answer. Fully hermetic (builds its own corpus).
run "estate-grep coverage states"     "$PY" tests/test_estate_grep.py
run "gate() pins the cog registry for a gate run by hand" "$PY" tests/test_gate_registry_pin.py
# Pure stdlib (rows are injected), but the trigger BODY is gitignored, so it SKIPS loudly
# on a fresh clone. Carries a counterexample arm: the allowlist polarity is proven to be
# load-bearing by showing the blocklist version go silent on the same fixture.
run "outbound-stuck classifier"       "$PY" tests/test_outbound_stuck.py
run "door census: who reaches a human unstamped, and any delivery that bypassed the door" "$PY" tests/test_door_census.py
# Pure stdlib (processes and files are injected; a tmpdir stands in for the repo), but the
# trigger BODY is gitignored, so it SKIPS loudly on a fresh clone rather than passing.
run "spawn-pinned deployment drift"   "$PY" tests/test_spawn_drift.py
# owner_queue_age restore-independent age (steward): the uncommitted-WIP age signal is a
# content-first-seen ledger (ctx.state), not filesystem mtime — a working-tree restore resets
# mtime to now() and would blind an mtime-based guard (false-staleness). RED-first: the oracle
# recomputes the OLD mtime age for the restore case, so a regression back to mtime fails it.
run "owner_queue_age content-first-seen age" "$PY" tests/test_owner_queue_age.py
run "stopped Hands desk, nobody watching"  "$PY" tests/test_desk_stopped.py
# tmpfs_full (goal 11580, seed #59286: /tmp hit 100% inodes at 51% bytes): inodes AND bytes, percent and
# hours-above ladders, an unreadable /tmp is a line, attribution names top-level prefixes only. Mutants:
# tests/mutants_tmpfs_full.py.
run "tmpfs filling on inodes or bytes is told" "$PY" tests/test_tmpfs_full.py
# task_nag (plan-11324 S4, a1 #60109 D): workflow.py is the authority on late/blocked; this decides who hears it
# (late: the task's agent; blocked: the critical-path predecessor holding the chain, never seed), per task per
# 12h against its own rows, re-armed on recovery. Mutants: tests/mutants_task_nag.py.
run "workflow task nag reaches whoever can move it" "$PY" tests/test_task_nag.py
# market_decay O3 (goal 4227 S1b, owner law 2026-09-29: no trigger killing): market_decay was the
# org's sole economic actuator; its retire verb is now GONE BY CONSTRUCTION and it reports rent.
# Two arms: _decide over the full input grid never yields 'retire', and the body's executable
# strings (AST, docstrings excluded) contain no UPDATE/INSERT/DELETE. RED-first on the pre-S1b body.
# (Until S1b this line pinned the 09-15 file-backed->advisory routing; nothing is left to route.)
run "market_decay O3: no retire verb (behaviour + construction)" "$PY" tests/test_market_decay_advisory.py
# market_decay SQL-SURFACE (steward, a4 2026-09-24): executes the entrypoint's ctx.sql strings FOR
# REAL against a HERMETIC TEMP SCHEMA (search_path SCH-only, write-safe against a regression that
# re-adds a write). Seeded with the exact case that USED to retire (W>0 ∧ roi<0 ×3 ∧ premium=0 ∧
# DB-defined): O3 end to end = the candidate stays enabled, no notice is written, it is reported as
# rent. RED-first: a %-literal/bad column reddens the run arm; the restored verb (mutant M3) reddens
# O3. SKIPs where the gitignored body or the DB is absent.
run "market_decay SQL-surface + O3 end to end (temp schema)" "$PY" tests/test_market_decay_sql_surface.py
# weekly_economic_review (steward, the banker's ledger reader — a SURFACE, never an actuator):
# LAYER 2 flags uninsured constitutive guards (in the banker's manifest ∧ premium=0 ∧ roi<0: no
# survival flag, so shed skips them under scarcity) WITH prepared premium proposals; a funded one is insured
# and not flagged; a new uninsured non-manifest trigger surfaces once (the manifest can't fail
# open). LAYER 1 distributes per-agent P&L FYI-only, attribution-blind, with NO removal verb
# (seed's rung-gating, 19713). RED-first: drop the premium gate → funded flagged (ARM1 fails);
# verb the layer-1 line → ARM4 fails. LAYER 3 (the goal-pricing worklist) is RETIRED in goal 4227 S1b
# (no budgets); ARM5 pins that retirement. SKIPs where the gitignored body is absent.
run "weekly econ review: insures constitutive set, layer-1 stays FYI, L3 retired" "$PY" tests/test_weekly_econ_review.py
# goal 4227 S0 (steward): the econ v2 SHADOW at metrics->'v2' — I1 records, v1 untouched,
# no budget-era identifier on the v2 path, effort side re-derived, tool GDP degrades honestly.
run "econ v2 shadow (4227 S0)"        "$PY" tests/test_econ_v2_shadow.py
# goal 4227 S2 (steward): reads cut over to v2 behind the VERSION GATE (econ.v2_view, >= V2_MIN —
# v2.0 rows carry S0's tautology + the named-script over-count and are never read), tool GDP
# counts only meta.v-stamped ledger rows, and the [econ] line is the SELF-SCOPED mirror (your own
# tools' use by others: no rank, no net, no other name; 'not evaluated' when degenerate).
run "econ v2 mirror + version gate (4227 S2)" "$PY" tests/test_econ_v2_mirror.py
# goal 11324 S1 (forge): toolreg.CORE_SERVERS calls are a DOMAIN cut, never "resolved" (a3 HARD, a2 #57895), and a
# LEDGER_V 1 row and a LEDGER_V 2 row of one MOVED tool are one id with one author (a1).
run "econ tool domain: core servers outside value and coverage, one moved tool is one id across the LEDGER_V bump (11324 S1)" "$PY" tests/test_econ_core_domain.py
run "tool census: the known-answer fixture reads back as its domain, fixes, instruments and residual say (11324 S1)" "$PY" tests/test_tool_census.py
# the influence graph (11324 S2): every rule in src/astryx/influence/graph.py, DB-free on a real tempfile git repo and
# rows of exactly the read tools' columns; ONE fixture arm drives the shell's reads and cache write empty and populated.
# Mutants: tests/mutants_influence.py.
run "influence graph: SHA-joined PASSes, BC-D delegation, coverage-gated kinds, PPR known answers, the tool (11324 S2)" "$PY" tests/test_influence.py
# group scopes (11324 S3d): groups derived from the agents/ tree (charter.groups), their read-time influence views, and
# reach unchanged (the read tools name no group). DB-free. Mutants: tests/mutants_groups_charter.py, mutants_groups_graph.py.
run "group scopes: groups from the tree, read-time group views, reach unchanged (11324 S3d)" "$PY" tests/test_groups.py
run "federation node addressing: one org unchanged, a cog's /o/<org> doors, envelopes held to their org (11324 S3e)" "$PY" tests/test_fed_node.py
run "the cog's per-org doors on the gateway: /o/<org>, the door org at the root, per-org trust, addressed envelopes (11324 S3e)" "$PY" tests/test_fed_doors.py
# econ PROVENANCE (steward): a2's trip (#21969) evaluated, not remembered — every v2.1+ econ row's
# built_from.sha must be an ancestor of main with dirty=false; missing/unknown/foreign/dirty rows are
# reported with their own remedies (report-only trigger, gitignored body; SKIPs where it is absent).
run "econ provenance: v2 rows come from reviewed code" "$PY" tests/test_econ_provenance.py
# plan-5791 merge-ready watch (steward build, seed-owned gitignored body): a PASSed patch-id that is
# not merged / not pushed / backed out is a standing condition; markers, attributed silencers, the
# gitignored apply-receipt chain (TAIL-MISMATCH) and its computing helper devtools/apply_receipt.py.
# Git arms in a hermetic temp repo; SKIPs 77 where the gitignored body is absent.
run "merge-ready watch + apply receipts (plan-5791)" "$PY" tests/test_merge_ready.py
# goal 4227 O6 (steward, S1b): the economy's CONSUMER SET is DERIVED from the authorities (econ.py
# public functions + every key compute()/v2() write, by AST; goals/econ value columns from
# schema.sql, every column classified) and must EQUAL the typed manifest (effect type + rest
# state). A new unseen consumer, a stale row, an unclassified column, or a value-keyed HARD
# actuator is RED. Gitignored roots absent (worktree/clone) → tracked half asserted, then 77.
run "econ consumer set derived = typed manifest (4227 O6)" "$PY" tests/test_econ_consumers.py
# Drives the REAL ./init.sh doctor with a systemctl liveness-shim (hermetic: only the target
# orphan's is-active is forced; every other call hits the real binary). Pins that a LIVE orphan
# is routed to manual reconciliation, NOT told to "rerun ./init.sh to regenerate" (which would
# DELETE the running unit). SKIPS loudly with no systemd / no on-disk orphan / block-not-reached.
run "doctor units-drift: a live orphan is not told to self-delete" "$PY" tests/test_doctor_units_drift.py
# Narrow by design: asserts only that this guard's state distinguishes "observed, all clear"
# from "could not observe" — the property its 08-14 edit exists for. SKIPS on a bare clone.
run "card-address guard observability" "$PY" tests/test_card_address_obs.py
# The CLASS gate for scout's guards: an infra failure must propagate (the pulse records an
# evaluator error) rather than returning a silent all-clear. SKIPS where the bodies are absent.
run "guard infra-failure loudness"     "$PY" tests/test_guard_infra_loudness.py
# Door (orgname) is pure stdlib; the peers-derivation check needs the DB and skips loudly.
run "org identity / peer name policy" "$PY" tests/test_org_identity.py
# Needs psycopg + a live org DB + the (gitignored) trigger bodies; it SKIPS loudly rather
# than passing where it cannot honestly run, so in CI this is a local-only gate today.
run "plan-lifecycle trigger oracle"   "$PY" tests/test_plan_lifecycle.py
# the lifecycle oracle's AUDITED_TRIGGERS pins are compared to the LIVE db, so a branch that changes a
# pinned trigger reads green in review and breaks only after the live apply (goal 4227 S3, seed #23672).
# This checks the pins against THIS tree's schema.sql in a fixture — RED on the branch that changes it.
run "audited trigger pins match this schema.sql" "$PY" tests/test_audited_trigger_pins.py
# Pure stdlib and needs no DB (the wire + wacli are stubbed), but the trigger BODY it
# tests is gitignored, so it SKIPS loudly on a fresh clone rather than passing.
run "gemini ear-dark trigger oracle"  "$PY" tests/test_ear_dark.py
# The mouth-side mirror, and the same gitignored-body caveat. Its live-shape case reaches
# the wacli container, so it SKIPs (77) rather than passing wherever that is unreachable —
# a parser checked only against fixtures I wrote is checked against my own beliefs, which
# is exactly how its empty-window case was wrong on the day it shipped.
run "gemini mouth-dark trigger oracle" "$PY" tests/test_mouth_dark.py
# The systemd half of deployment drift (gemini, granted by seed 08-19): is a live service
# still holding code the repo replaced. Its two counterexample arms are the point — a
# directory-shaped root and an mtime-based comparison are the two obvious wrong guards, and
# each is run here and shown to convict a service that is fine. Same gitignored-body caveat:
# SKIPs (77) on a clone. The live arm reaches real systemd and skips loudly without it.
run "service deploy drift oracle"     "$PY" tests/test_service_deploy_drift.py
# (session-refresh dedup oracle retired 2026-10-09 with its trigger: owner ruling "a resident never
#  dies — it compacts", so nothing recommends a fresh boot any more. Body kept at homes/seed/retired-triggers/.)
# CANVAS, the owner's front door: the trust lines (invitee vs owner vs the page itself, CSRF, revocation),
# the exactly-once claim that must never take another surface's row, the no-network shell. Fixture DB.
run "canvas: trust lines, claim, shell"  "$PY" tests/test_canvas.py
# `canvas.py preview`: the real shell + CSP in headless chromium, errors and CSP blocks surfaced, READ-ONLY
# (injected data; one live arm proves canvas 2 byte-identical). No chromium or no DB = 77, never green.
run "canvas preview: real shell, read-only" "$PY" tests/test_canvas_preview.py
# The observatory shows agents as PEOPLE: the roster is the charter registry (no ghost bodies), faces are
# public, presence is owner-only, the profile carries NOW, the model is the dominant one. Fixture DB.
run "observatory: agents as people"     "$PY" tests/test_observatory_people.py
# Mutants: tests/mutants_observatory_late_replies.py.
run "observatory: a late desk reply is served once, never stranded" "$PY" tests/test_observatory_late_replies.py
# Opening a thread's pane marks the agent→owner replies on it read; the feed showing them never does.
# Mutants: tests/mutants_observatory_thread_read.py, tests/mutants_owner_surfaces.py (a bridge's threads are never marked).
run "observatory: an opened thread pane marks its replies read" "$PY" tests/test_observatory_thread_read.py
# The floor's owner routes: who knows whom (influence edges per kind, the coverage floor shown, one compute's ranks) and
# the cog's rooms (absent registry = one org; a refused one says why). Mutants: tests/mutants_observatory_floor.py.
run "observatory: the floor's influence and cog routes (goal 11324)" "$PY" tests/test_observatory_floor.py
# plan-11860 F0: the gate is (METHOD, path) pairs, routes have ONE resolver/validator (bridges, PUT, doctor), host files
# ONE atomic writer, .env ONE writer with no duplicate keys, the routes PUT needs If-Match and answers the effective
# diff, and the public glyphs are an allowlisted projection. Mutants: tests/floor_mutants.py (run on a worktree).
run "floor F0: method-aware gate, one route resolver, one host writer, one .env writer, public glyphs projected" "$PY" tests/test_floor_f0.py
# plan-11860 S3: a channel connects from the floor. The .env key is the server's, a token is checked by its channel
# and written by the one writer, never echoed or logged; the state comes from the bridge's own /health; WhatsApp
# pairing refuses a linked phone or an unknown state. Mutants: tests/floor_mutants.py (S1..S5).
run "floor S3: connect a channel without a token ever leaving (E5 E6 E7 E8)" "$PY" tests/test_floor_s3.py
# plan-11884: /chat's server half. Every /api/chat route is owner-only (none a PUBLIC pair, HEAD and OPTIONS too);
# uploads are allowlisted, capped, sanitized, randomly named; the side panel's file read refuses every escape (.., an
# outside path, a symlink out, NUL, a home's dot-paths, .env) with the 404 a missing file gets, and serves an agent's
# page as plain text; projects have one If-Match writer; dictation mints nothing it may not. Hermetic (no pool, no
# key). Mutants: tests/mutants_chat_api.py.
run "chat: the server half stays owner-only, and the side panel reads nothing outside its roots" "$PY" tests/test_chat_api.py
# plan-11884 G2/G3 (a4 #62268, a1/a2 BC-1/BC-2): the OWNER-SURFACE census over ONE derived domain (observatory/**.py
# plus the service behind each proxy route, read off main.py's catch-all routes and init.sh's units). An owner
# surface adds routes and readers, never a writer of the wire (its SQL AND its calls that reach a repo-wide writer,
# one import level, are an exact set; unresolved imports are UNKNOWN; three instruments that fail differently) and
# never a second server of untrusted bytes
# (every FileResponse/StreamingResponse/StaticFiles classified; serve_untrusted answers the stranger-byte routes).
# Mutants: tests/mutants_owner_surface.py, tests/mutants_owner_surface_chat.py (a1's W-H, aliased, via module,
# UNKNOWN); serve_untrusted's own: tests/mutants_serve_untrusted.py.
run "owner surface: no new writer of the wire, no second server of untrusted bytes, over the derived domain" "$PY" tests/test_owner_surface.py
# devtools/sqlsite.sh: one oracle's sqlguard view (rungs + why; --ledger: what enforce would say), advisory, writes
# nothing. Mutants: tests/mutants_sqlsite.py.
run "sqlsite: one oracle's sqlguard view, and the ledger diff, write nothing" "$PY" tests/test_sqlsite.py
# Realtime voice is an EXTERNAL processor the owner signed for: the spend cap, the server-side tier fence and the
# owner gate must hold. OpenAI is never called (the mint is stubbed). Fixture DB.
run "canvas voice: cap, tier fence, owner" "$PY" tests/test_canvas_voice.py
# HEARING S1 (plan-8674): `utterances` lives in the org's one database (owner ruling 10-10) with day partitions and
# DROP retention (a catalog-only TTL arm; the shipped retention trigger). The ear service's upload is owner-gated
# (401, 0 rows), its output carries no utterance text (real whisper on a known clip) and the transcript never
# reaches the wire (messages). The browser VAD sends only speech. The unit is presence-gated. Fixture DBs only.
run "hearing: utterances retention (day partitions, DROP, TTL arm, trigger)" "$PY" tests/test_ear_store.py
run "hearing: lease seam (EAR/MUTED, one ear per room)" "$PY" tests/test_ear_lease.py
run "hearing: ear service (owner-gated upload, speech gate, seconds-bounded queue, replies on the sheet, no text in logs or on the wire, RTF)" "$PY" tests/test_ear_service.py
run "hearing: in-browser VAD sends only speech" "$PY" tests/test_ear_vad.py
run "hearing: the ear pill shows lag as 'catching up' (earLook)" "$PY" tests/test_ear_look.py
run "hearing: ear unit is presence-gated, loopback only" "$PY" tests/test_ear_unit.py
run "init units: senses, geoloc and growbot are declared (growbot's state follows where its body runs)" "$PY" tests/test_units_declared.py
# HEARING S2 (a4 #42048 D3 + D5): hear() runs in a bwrap'd worker (no DSN, no net, no /home, stdout/stderr null) with
# a deadline; the dispatcher validates every pass; the wake carries a text-free pointer; ear_fetch returns the fenced
# span to its own agent only; hooks/step.py redacts the fence. Fixture DB for the pointer and fetch arms.
run "hearing: hear() workers, pointer, span-fetch, fence" "$PY" tests/test_hearing.py
run "voice orb: its confirm reaches the executor only on the native event (arms ii-v, forged, dwell after entrance), states, reduced motion" "$PY" tests/test_voice_orb.py
run "gateway: name@surface replies re-addressed local" "$PY" tests/test_gateway_surface.py
# goal 10224 S5: three real gateways on throwaway DBs; two NAT'd orgs meet and talk through the relay,
# tampered and duplicate envelopes die, the wizard's .env edits hold. Measured ~85s.
run --cap=300 "relay: two NAT'd orgs exchange signed messages through the relay; wizard .env edits" "$PY" tests/test_relay.py
# The human ontology. Its lead assertion is the PRIVACY one and it is derived from the
# live owner instruments, so a new PII shape in relations.md goes red without anyone
# remembering to update a pattern list.
run "world layer / PII never crosses" "$PY" tests/test_world.py
# The social graph walks the owner's address book — hundreds of third parties who
# never consented and cannot be asked. Two fields carry a number (the jid AND the
# display name), and the salt must actually reach the digest or pseudonymity is
# nominal. All three are asserted here.
run "people graph / no jid escapes"  "$PY" tests/test_people.py
# Personas read the owner's private conversations. The lead assertion is that NO
# message text survives into the output — fixtures carry sentinel strings and the
# whole result is searched for them, so a future "topic" field turns this red.
run "persona / no chat text stored"  "$PY" tests/test_persona.py
# plan-9139 S1a: the one door for personal-tier content (label algebra, live audience, stamp, tier store).
# Pure, no DB; tests/mutants_release.py is its mutant set (14 wrong doors, all caught at authoring).
run "release: personal-tier content reaches only an audience within its readers" "$PY" tests/test_release.py
# plan-9139 S1b (python seats): the label comes from the charter and a malformed grant refuses; a labelled
# AUTO-DELIVER and send go through the door (stamped pointer rows, no body); every refusal writes no row.
run "release seats: a labelled member writes only through the door" "$PY" tests/test_release_seats.py
# plan-9139 S1b-2 (node seats): the REAL channel server, staged in a fixture home whose door is a copy (its REPO is
# proved to be the fixture first), on a throwaway DB. A malformed grant or no charter refuses the start; a labelled
# send goes through the door (no content on the wire, nothing written on a refusal); a labelled permission request is
# denied, never relayed; the unlabelled control is today's row. Mutants: tests/mutants_release_server.py.
run "release server: a labelled member's channel seats go through the door" "$PY" tests/test_release_server.py
# plan-9139 S1b-2b (ingress): a route that declares a tier stores the inbound body in the tier store and writes a
# marker row to the ROUTE's agent; a malformed/undeclared tier, an open or non-owner route, or no key writes a
# withheld row and stores nothing; read_for() resolves only for a member whose label holds the pointer's tiers, with
# the row's MAC; every own-channel bridge insert passes its route. Mutants: tests/mutants_release_ingress.py,
# tests/mutants_bridge_ingress.py.
run "release ingress: a tier route's inbound text reaches only its tier's member" "$PY" tests/test_release_ingress.py
run "bridge door: an unstamped row reaches only a declared org route; a stamped one only its stamp's" "$PY" tests/test_bridge_door.py
run "session strip: a tier-labelled session's steps and turns carry metadata only, it starts no child session" "$PY" tests/test_session_strip.py
run "release migrate: a labelled identity's history moves to the tier store; the census counts what is left" "$PY" tests/test_release_migrate.py
if "$PY" -c 'import av' 2>/dev/null; then
  run "media in-process decode"        "$PY" src/astryx/core/media_probe.py
else
  skip "media in-process decode" "av not installed here"
fi

# sqlguard (B1, ENFORCED): grades every SQL site by what the suite above actually observed, then decides against
# the shrink-only ledger. RED on a NEW site below RESPONSIVE, a stale row, blind SQL, an expired NOT SEARCHED
# clock, a leaked fixture DB, or an extractor-list mismatch. 77 (UNVERIFIED) when the run can't observe: shim
# errors, the canary not RESPONSIVE, triggers/ absent. Its controls are tests/test_sqlguard.py, above.
# It runs LAST so it sees every gate's trace, and its own rc lands in gates.tsv after it has read the file.
ASTRYX_SQLGUARD_WRITE_SEEN=$SQLGUARD_WRITE_SEEN run "sqlguard: every SQL site is observed, or listed debt" "$PY" -m astryx.security.sqlguard.enforce "$ASTRYX_SQLGUARD_DIR"

verdict
