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
cd "$(dirname "$0")/.."
PY=${PY:-venv/bin/python}; [ -x "$PY" ] || PY=python3
EXIT_SKIP=77
fail=0
verified=0
declare -a UNVERIFIED=()
declare -a FAILED=()
declare -a LIARS=()
run() {
  local label=$1; shift
  printf '\033[36m▶\033[0m %s\n' "$label"
  local out rc
  out=$("$@" 2>&1); rc=$?
  printf '%s\n' "$out"
  # The belt. A gate that ANNOUNCES a skip and still exits 0 has broken the protocol —
  # it is the exact defect this accounting exists to catch, so it is reported as a
  # violation rather than quietly trusted. Narrow by construction: only a line whose
  # first non-space token is SKIP or ○ counts, so a passing test whose NAME contains
  # "skipped" (test_plan_lifecycle has one) can never trip it. This belt can only ever
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
  case $rc in
    0)  verified=$((verified+1)); printf '\033[32m  ✓ %s\033[0m\n' "$label" ;;
    "$EXIT_SKIP")
        UNVERIFIED+=("$label")
        printf '\033[33m  ○ %s — VERIFIED NOTHING this run\033[0m\n' "$label" ;;
    *)  fail=1; FAILED+=("$label"); printf '\033[31m  ✗ %s\033[0m\n' "$label" ;;
  esac
}
# A gate whose PREREQUISITE is absent is itself unverified — never silently omitted.
skip() { UNVERIFIED+=("$1"); printf '\033[33m○\033[0m %s — VERIFIED NOTHING (%s)\n' "$1" "$2"; }

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
  if [ "$fail" != 0 ]; then
    echo "check: FAILURES above — a committed invariant regressed"; return 1
  elif [ "${#UNVERIFIED[@]}" = 0 ]; then
    echo "check: ALL CODE INVARIANTS PASS ($verified gates verified)"; return 0
  elif [ -n "${CHECK_ALLOW_SKIP:-}" ]; then
    echo "check: $verified verified, ${#UNVERIFIED[@]} UNVERIFIED (skips allowed here) — NOT a full pass"; return 0
  else
    echo "check: $verified verified, ${#UNVERIFIED[@]} UNVERIFIED — a gate that observes nothing is RED here."
    echo "       Set CHECK_ALLOW_SKIP=1 only where the missing prerequisites are expected (a bare CI clone)."
    return 1
  fi
}

# Sourcing hook for nucleus/test_check_verdict.py, which drives run()/skip()/verdict()
# against SYNTHETIC gates so the accounting is proven against THIS file rather than a
# copy of it. Everything above is definitions; everything below runs the real gates.
[ -n "${CHECK_LIB_ONLY:-}" ] && return 0

run "charter resolver invariants"      "$PY" nucleus/test_charter.py
run "tier floor invariants"            "$PY" nucleus/test_tier.py
run "dep coverage invariants"          "$PY" nucleus/test_deps.py
run "dep manifest covers all imports"  "$PY" nucleus/deps.py coverage
# This suite's own blind spot: the list below is hand-maintained, so a newly committed
# nucleus/test_*.py was silently never run and this still printed ALL PASS (reproduced
# 08-13). Derives the expected set from the nucleus/test_*.py glob — a new oracle must
# be wired here or this goes RED. Pure stdlib, no DB.
run "check.sh runs every committed oracle" "$PY" nucleus/test_check_coverage.py
# The coverage gate's own trip condition, fired (its §2 predicted the case): an oracle
# outside the test_*.py glob — or any nucleus script — can land invoked-by-nothing and
# every gate stays green. This derives the population from git, parses real invocation
# syntax across tracked+out-of-tree surfaces (units, runners, triggers classified via
# check-ignore, never assumed), and fails any script neither reached nor exempted with
# a reason. Exit 77 when a surface is unreadable: it never accuses while blind.
run "every committed nucleus script is invoked" "$PY" nucleus/test_reachability.py
# The interim ratchet for the mutation estate (steward's ruling 08-15: the FULL probe run
# costs 100.6s and belongs in CI, not in the interactive loop — a gate slow enough to skip
# gets skipped). This is the sub-second structural half: every nucleus/mutants_*.py imports,
# declares SUBJECT/ORACLE/ENV/MUTANTS, points at files that exist, and still has patterns
# that apply. It asserts APPLICABILITY and never discrimination. Pure stdlib, no DB, ~0.1s.
run "mutants files still point at something real" "$PY" nucleus/test_mutants_wellformed.py
# The SECOND blind spot in this file, the same shape one level down: the gate above proves
# every oracle is INVOKED; this one proves an invoked oracle actually RAN. Drives this
# file's own run()/verdict() against synthetic gates. Pure stdlib, no DB.
run "a skip is not a pass (verdict accounting)" "$PY" nucleus/test_check_verdict.py
# The gate on the OTHER actuator. .git/hooks/pre-push is a COPY of the tracked hooks/pre-push,
# so the reviewed artifact and the executed one are two writers of one fact with no reconciler
# — and privacy_gate already rides on that copy. Proves the installed hook matches byte for
# byte AND is executable (git skips a non-executable hook silently: byte-identical and inert).
# SKIPs loudly where no hook is installed — a fresh clone or CI legitimately has none, and
# that is not a pass: it means nothing gates a push there. Pure stdlib, no DB.
run "installed pre-push hook is the reviewed one" "$PY" nucleus/test_hook_integrity.py
# The org's PII detector, gated on the two properties that failed in the field: a finding
# is silenced only by REPAIR or by an explicit ruling (warn-once let a live finding sit
# unmentioned for 22 days), and the guard never emits the shape it hunts (an unmasked
# `messages.thread` put a group JID into its own alarm, msg#344). Hermetic — synthetic
# fixtures, no DB, no live estate. SKIPs by name where triggers/ is absent, which is every
# clean checkout: there the guard is not here to be verified. ~0.3s.
run "pii_sweep cannot forget a finding or print a routing id" "$PY" nucleus/test_pii_sweep_ledger.py
run "referral opt-in + static-literal" bash nucleus/referral_guard.sh
# OKF frontmatter for the memory estate. The invariant is ADDITIVITY: attaching metadata
# must change nothing the three live lints read. Pure stdlib; the arms that touch the real
# estate skip on a clean checkout (memory/ is gitignored), and the PyYAML cross-check arm
# runs only where PyYAML happens to be importable — it is not a dependency.
run "OKF frontmatter additivity"      "$PY" nucleus/test_okf.py
# The recall-graph compiler. Its load-bearing arm is CONFORMANCE: the page-link set it
# extracts must equal link_integrity.py's edge for edge, or the graph and the lint watching
# the same files disagree with nothing to arbitrate. Pure stdlib; the estate arms skip
# loudly on a clean checkout, and the wire layer is never touched here.
run "recall-graph compiler"           "$PY" nucleus/test_memgraph.py
# The typed layer's lint. Every finding must be FALSIFIABLE and every expected field set
# DERIVED from the corpus — a hand-kept list would be the drift class this org has hit
# five ways. Named for the false positive it prevents: the lint's first version condemned
# `goal`, a type with a real shared core AND a long narrative tail, as a bucket.
run "ontology lint invariants"        "$PY" nucleus/test_ontology.py
# Every name a trigger file references must resolve. Earned when three agents edited one
# trigger file in two hours and a dropped helper left another author's function throwing
# on every tick — a defect no per-proposal oracle can see, because each tests its own
# function against its own staged copy. SKIPS where triggers/ or pyflakes is absent.
run "trigger bodies resolve"          "$PY" nucleus/test_trigger_smoke.py

# tokenwatch + shipped context-compact: the usage layer that keeps the fleet from
# burning its window blind (owner directive 2026-08-15) — window inference, tail
# parsing, and the actuator's fire/cooldown/wedge/re-arm decisions.
run "usage meter + context-compact"   "$PY" nucleus/test_tokenwatch.py
run "A2A card canonicalisation (JCS)" "$PY" nucleus/test_card_canon.py
# The ear must outlive a database blip. Runs the REAL channel/server.mjs against a
# THROWAWAY database (created, then dropped — the org's own is never written to), breaks
# the database underneath it the two ways an ordinary `docker restart` does, and proves it
# both SURVIVED and still DELIVERS. Earned by forge going deaf 8h49m on 2026-08-14 while
# its body sat at a healthy prompt. Slow by nature (~35s: it waits out the server's own 15s
# startup drain, or a permanently deaf ear passes on that one-shot). SKIPS loudly without
# node, channel/node_modules, a reachable DB, or CREATE DATABASE rights — i.e. a bare clone.
run "channel ear survives a db blip"  "$PY" nucleus/test_ear_survival.py
# Class-1 of the prove-family oracle (scout, plan-15): drives all seven containment
# verdicts BOTH ways against synthetic trees via G15_ENVF/G15_SCAN_ROOTS. Its output
# states its own limit — decision logic only, not the real cell.
run "containment gate decision logic"  "$PY" nucleus/test_prove_containment.py
# Class 2: the two HOST-SIDE prove scripts at the logic layer, docker stubbed. A weaker claim
# than the gate above and it prints that limit in its own output — it proves these scripts CAN
# fail when they should, never that the cell is contained. Carries the RED-proof for the
# cell-liveness verdict added to prove_egress.sh (plan-15, granted msg 8846).
run "host-side prove scripts (logic)"  "$PY" nucleus/test_prove_hostside.py
# Needs psycopg + a live org DB; SKIPS loudly otherwise. Fixtures go in a rolled-back
# transaction (messages_notify is a pure pg_notify, so a rollback wakes nobody).
run "wake-audit classifier"           "$PY" nucleus/test_wake_audit.py
run "wedge-watch discriminator"       "$PY" nucleus/test_wedge_watch.py
# Pure stdlib (rows are injected), but the trigger BODY is gitignored, so it SKIPS loudly
# on a fresh clone. Carries a counterexample arm: the allowlist polarity is proven to be
# load-bearing by showing the blocklist version go silent on the same fixture.
run "outbound-stuck classifier"       "$PY" nucleus/test_outbound_stuck.py
# Pure stdlib (processes and files are injected; a tmpdir stands in for the repo), but the
# trigger BODY is gitignored, so it SKIPS loudly on a fresh clone rather than passing.
run "spawn-pinned deployment drift"   "$PY" nucleus/test_spawn_drift.py
# Narrow by design: asserts only that this guard's state distinguishes "observed, all clear"
# from "could not observe" — the property its 08-14 edit exists for. SKIPS on a bare clone.
run "card-address guard observability" "$PY" nucleus/test_card_address_obs.py
# The CLASS gate for scout's guards: an infra failure must propagate (the pulse records an
# evaluator error) rather than returning a silent all-clear. SKIPS where the bodies are absent.
run "guard infra-failure loudness"     "$PY" nucleus/test_guard_infra_loudness.py
# Door (orgname) is pure stdlib; the peers-derivation check needs the DB and skips loudly.
run "org identity / peer name policy" "$PY" nucleus/test_org_identity.py
# Needs psycopg + a live org DB + the (gitignored) trigger bodies; it SKIPS loudly rather
# than passing where it cannot honestly run, so in CI this is a local-only gate today.
run "plan-lifecycle trigger oracle"   "$PY" nucleus/test_plan_lifecycle.py
# Pure stdlib and needs no DB (the wire + wacli are stubbed), but the trigger BODY it
# tests is gitignored, so it SKIPS loudly on a fresh clone rather than passing.
run "gemini ear-dark trigger oracle"  "$PY" nucleus/test_ear_dark.py
# Same gitignored-body caveat: SKIPs (77) on a clone. Guards the DEDUP specifically —
# the key must carry an escalation band, or a standing condition warns once and goes
# silent (which is how p1 degraded unobserved at 59h, 2026-08-14).
run "session-refresh dedup oracle"    "$PY" nucleus/test_session_refresh.py
# The human ontology. Its lead assertion is the PRIVACY one and it is derived from the
# live owner instruments, so a new PII shape in relations.md goes red without anyone
# remembering to update a pattern list.
run "world layer / PII never crosses" "$PY" nucleus/test_world.py
# The social graph walks the owner's address book — hundreds of third parties who
# never consented and cannot be asked. Two fields carry a number (the jid AND the
# display name), and the salt must actually reach the digest or pseudonymity is
# nominal. All three are asserted here.
run "people graph / no jid escapes"  "$PY" nucleus/test_people.py
# Personas read the owner's private conversations. The lead assertion is that NO
# message text survives into the output — fixtures carry sentinel strings and the
# whole result is searched for them, so a future "topic" field turns this red.
run "persona / no chat text stored"  "$PY" nucleus/test_persona.py
if "$PY" -c 'import av' 2>/dev/null; then
  run "media in-process decode"        "$PY" nucleus/media_probe.py
else
  skip "media in-process decode" "av not installed here"
fi

verdict
