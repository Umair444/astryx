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

# Node for the channel gates. The pulse runs check.sh on a minimal systemd PATH with no
# mise dir, so the node the org actually spawns agents with is invisible and the channel
# gates (test_ear_survival, test_wake_recovery) silently SKIP — verified nothing — on every
# timer run while passing interactively. They resolve node via shutil.which, so put the org's
# node on PATH from the ASTRYX_NODE anchor (env first, then .env — the same host-config
# spawn.sh honors; pulse.py loads only ASTRYX_DSN, not the whole .env, so read it here).
# Harmless where ASTRYX_NODE is unset or node is already found. (seed, steward check_stamp finding 2026-09-20.)
NODE_BIN=${ASTRYX_NODE:-$(sed -n 's/^ASTRYX_NODE=//p' .env 2>/dev/null | head -1)}
[ -n "$NODE_BIN" ] && export PATH="$(dirname "$NODE_BIN"):$PATH"

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
  out=$(ASTRYX_SQLGUARD_GATE="$label" "$@" 2>&1); rc=$?
  printf '%s\n' "$out"
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

# Sourcing hook for tests/test_check_verdict.py, which drives run()/skip()/verdict()
# against SYNTHETIC gates so the accounting is proven against THIS file rather than a
# copy of it. Everything above is definitions; everything below runs the real gates.
[ -n "${CHECK_LIB_ONLY:-}" ] && return 0

# sqlguard (goal 4243): the driver shim rides every python gate as `sitecustomize`. check.sh sets
# all three ITSELF, because run_check runs this under pulse's bare systemd env (the runner-env law:
# ASTRYX_NODE/507e7ea). The run id names this run's fixture databases, so the leak arm only ever looks for
# its own prefix.
export ASTRYX_SQLGUARD_RUN="${ASTRYX_SQLGUARD_RUN:-r$(date +%s)x$$}"
export ASTRYX_SQLGUARD_DIR="${ASTRYX_SQLGUARD_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/sqlguard.XXXXXX")}"
export PYTHONPATH="$PWD/nucleus/sqlguard/shim${PYTHONPATH:+:$PYTHONPATH}"
echo "$ASTRYX_SQLGUARD_RUN" > "$ASTRYX_SQLGUARD_DIR/run_id"
# The canary proves THIS run's shim can observe: one statement through the REAL pulse_run.Ctx.sql. If it isn't
# RESPONSIVE, the whole sqlguard verdict is NOT SEARCHED (a check that can't observe says so).
run "sqlguard canary: the shim observes through the real Ctx.sql" "$PY" -m nucleus.sqlguard.canary
run "sqlguard oracle: privacy (P1) + controls"          "$PY" tests/test_sqlguard.py

run "charter resolver invariants"      "$PY" tests/test_charter.py
# org MCP write-tool role gate (t-org-grant): the genome/identity writes are governance-gated
# (cross-agent amend_charter refused for non-governance; set_persona self-only) so grant:org is
# safe to grant widely, while reads + benign writes (goals/economy/propose_goal/announce) stay
# OPEN — over-gating them would re-break abstractor read-access. DB-free; mutation-control arm.
run "org MCP write-tool role gate"     "$PY" tests/test_org_write_gate.py
run "tier floor invariants"            "$PY" tests/test_tier.py
run "dep coverage invariants"          "$PY" tests/test_deps.py
run "dep manifest covers all imports"  "$PY" nucleus/deps.py coverage
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
run "economy heat-definition (legend)" "$PY" nucleus/legend_guard.py
run "legend guard invariants"          "$PY" tests/test_legend_guard.py
# RETIRED in goal 4227 S1b (owner law 2026-09-29: no budgets): attribution_guard (credited value
# never exceeds shipped BUDGETS) and pay_the_author (resharing the shipped BUDGET to tool
# authors) conserved a quantity that no longer exists; their four lines and modules are removed,
# not left passing vacuously. The wash detector MIGRATES: v2 tool GDP already discounts
# self-use, so it now finds RINGS (A→B→…→A tool use, as strongly connected components over the
# GDP-counted edges) and reports their share of GDP — detection, never an actuator.
run "wash detector: v2 rings (live, report-only)" "$PY" nucleus/wash_detector.py
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
# the registry door's find() (steward #25795): whole-token matching (no "is" inside "list"),
# 4+ char prefixes either way (healthy/health), stopwords dropped, IDF-weighted, and a relative
# floor that drops common-word-only matches. Fixture registry, RED against the substring ranker.
run "toolreg find ranks the tool a question is about" "$PY" tests/test_toolreg_find.py
# observatory without budget economics (goal 4227 follow-up, a2 #23159): no component renders
# spent_tokens (never written: 0 means never measured), sends a budget, or draws a budget bar;
# a legacy budget_tokens is labelled "budget-era". Scans the TSX with comments stripped.
run "observatory renders no budget economics" "$PY" tests/test_observatory_no_budget_ui.py
# the registry door (goal 4227, S4): find + run, and never a new capability. run() executes
# registered SCRIPTS only, as an argv list (no shell), with a clamped timeout, and never starts
# an MCP server, because that would walk past its charter grant. Mutants: tests/mutants_tools_door.py.
run "tools door: registered scripts only, no shell, no server" "$PY" tests/test_tools_door.py
# the registry's search text (medic): a tool is described by its OWN header. The docstring regex
# ran over shell scripts too, so a `'''` in code or a heredoc template described a tool by its body
# (mcp/new.sh was registered as its template's placeholder). RED-first against the unscoped regex.
run "toolreg: a tool's search text is its own header" "$PY" tests/test_toolreg_describe.py
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
# ...and the probe MACHINERY demonstrably runs (one family, ~4s). The full battery is the
# monthly steward trigger; this edge is what keeps probe_all/mutation_probe auto-reached.
run "mutant machinery smoke (one family)" bash nucleus/probe_all.sh --smoke
# The SECOND blind spot in this file, the same shape one level down: the gate above proves
# every oracle is INVOKED; this one proves an invoked oracle actually RAN. Drives this
# file's own run()/verdict() against synthetic gates. Pure stdlib, no DB.
run "a skip is not a pass (verdict accounting)" "$PY" tests/test_check_verdict.py
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
# The guard that reads THIS suite's own live-tree result. check.sh runs automatically in
# exactly two places and both are clones, where the gitignored estate cannot exist — so
# nucleus/check_watch.sh runs it here on a timer and stamps the outcome, and the guard
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

# THE INSTRUMENT, NOT THE ESTATE. nucleus/glob_vacuity.py runs the whole suite under a
# shim to find globs that match nothing and pass anyway (forge's *.json against a
# *.jsonl archive, dormant for the life of the org). That sweep is minutes long and
# needs the live estate, so it stays a manual tool — but its SELFTEST is ~1s and plants
# a dormant glob it must find. Gating the selftest keeps the instrument from rotting
# without putting a multi-minute sweep in the fast loop; a tool that can no longer find
# a planted defect reports "none dormant" in exactly the same words as a clean estate.
run "glob-vacuity can still find a planted dormant glob" "$PY" nucleus/glob_vacuity.py --selftest
run "referral opt-in + static-literal" bash nucleus/referral_guard.sh
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

run "A2A card canonicalisation (JCS)" "$PY" tests/test_card_canon.py
# the org economy: G = W/(Φ·K), value enters only at the boundary (goals.done_at),
# heat <= flux, theil arms both ways, archived rollup self-consistent with its parts.
run "the org economy is honest"       "$PY" tests/test_econ.py
run "shed reads no value (4227 S1a)"   "$PY" tests/test_shed_s1a.py
run "secret set + turn writer redaction (5497 S0+S1a)" "$PY" tests/test_secretset.py
run "secret guard keeps holders out of context (5497 S1b)" "$PY" tests/test_secret_guard.py
run "db password rotation leaks nothing (5497 S3b BC-1)" "$PY" tests/test_rotate_db_password.py
run "S1c-0 runner census cannot pass vacuously (5497)" "$PY" tests/test_dsn_census.py
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
# Pure stdlib (rows are injected), but the trigger BODY is gitignored, so it SKIPS loudly
# on a fresh clone. Carries a counterexample arm: the allowlist polarity is proven to be
# load-bearing by showing the blocklist version go silent on the same fixture.
run "outbound-stuck classifier"       "$PY" tests/test_outbound_stuck.py
# Pure stdlib (processes and files are injected; a tmpdir stands in for the repo), but the
# trigger BODY is gitignored, so it SKIPS loudly on a fresh clone rather than passing.
run "spawn-pinned deployment drift"   "$PY" tests/test_spawn_drift.py
# owner_queue_age restore-independent age (steward): the uncommitted-WIP age signal is a
# content-first-seen ledger (ctx.state), not filesystem mtime — a working-tree restore resets
# mtime to now() and would blind an mtime-based guard (false-staleness). RED-first: the oracle
# recomputes the OLD mtime age for the restore case, so a regression back to mtime fails it.
run "owner_queue_age content-first-seen age" "$PY" tests/test_owner_queue_age.py
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
# econ PROVENANCE (steward): a2's trip (#21969) evaluated, not remembered — every v2.1+ econ row's
# built_from.sha must be an ancestor of main with dirty=false; missing/unknown/foreign/dirty rows are
# reported with their own remedies (report-only trigger, gitignored body; SKIPs where it is absent).
run "econ provenance: v2 rows come from reviewed code" "$PY" tests/test_econ_provenance.py
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
# Same gitignored-body caveat: SKIPs (77) on a clone. Guards the DEDUP specifically —
# the key must carry an escalation band, or a standing condition warns once and goes
# silent (which is how p1 degraded unobserved at 59h, 2026-08-14).
run "session-refresh dedup oracle"    "$PY" tests/test_session_refresh.py
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
if "$PY" -c 'import av' 2>/dev/null; then
  run "media in-process decode"        "$PY" nucleus/media_probe.py
else
  skip "media in-process decode" "av not installed here"
fi

# sqlguard (B1, ENFORCED): grades every SQL site by what the suite above actually observed, then decides against
# the shrink-only ledger. RED on a NEW site below RESPONSIVE, a stale row, blind SQL, an expired NOT SEARCHED
# clock, a leaked fixture DB, or an extractor-list mismatch. 77 (UNVERIFIED) when the run can't observe: shim
# errors, the canary not RESPONSIVE, triggers/ absent. Its controls are tests/test_sqlguard.py, above.
# It runs LAST so it sees every gate's trace, and its own rc lands in gates.tsv after it has read the file.
run "sqlguard: every SQL site is observed, or listed debt" "$PY" -m nucleus.sqlguard.enforce "$ASTRYX_SQLGUARD_DIR"

verdict
