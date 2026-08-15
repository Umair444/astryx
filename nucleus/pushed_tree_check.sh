#!/usr/bin/env bash
# Contributed by abstractor-2 (night-review 2026-08-16, msg 10000); adopted by seed.
#
# WHAT IT ANSWERS: "will check.sh pass on a machine that is not mine?"
#
# THE DEFECT CLASS IT CLOSES. An oracle is committed; the SUBJECT it reads is left
# uncommitted. On the authoring machine the working tree holds both, so the oracle is
# green. Everywhere else — CI, a fresh clone, another operator — the subject is present
# but at its OLD version, so the oracle runs and legitimately FAILS. Two properties make
# this class nasty:
#   1. The existing absent-subject classifiers cannot see it. `p.exists()` is TRUE; the
#      file is there. Stale-but-present is a THIRD state between present and absent, and
#      every guard in the family classifies only the two.
#   2. It fails LOUD, but only in an environment nobody runs — so the loudness buys
#      nothing, and the red surfaces later as "CI is broken" rather than as its real
#      cause, at exactly the moment the org is trying to establish trust in CI.
#   Live instance: HEAD bd1e026 is RED in a clean clone. nucleus/test_prove_hostside.py
#   landed in 50ccc61 ("host-side oracle lands with it") but harness/cell/prove.sh's
#   update did not land with it — 8 assertions fail on any other machine, 7 commits deep.
#
# WHY THIS SHAPE. No manifest of which-oracle-reads-which-subject: such a set would be
# hand-maintained, would drift, and its unknown member would default to unchecked. This
# derives the answer from the authority instead — it runs the REAL suite against the
# REAL bytes that HEAD carries. Anything check.sh ever learns to check, this inherits.
#
# GRADE, stated not implied. This is the CI environment previewed locally; it is not a
# substitute for CI. It proves what HEAD's tree does on a machine with no gitignored
# estate. It cannot prove anything about the estate itself (triggers/, memory/ are
# absent here by construction — check.sh names each one it therefore did not verify).
#
# WHY A CLONE AND NOT `git archive`. Learned the hard way while building this: an
# archive export drops the .git directory, and the org's absent-subject classifiers
# (mutants_wellformed's ratchet, f478495) call `git check-ignore` to decide whether a
# missing subject is legitimately-gitignored or genuinely lost. With no .git they cannot
# classify, so they correctly refuse to skip and go RED. That red is the gate working;
# it is my SIMULATION that was wrong. .git is part of the environment under test — a
# faithful preview must be a real checkout, exactly as actions/checkout produces one.
# (This instrument's first run reported that phantom as a second defect. Read the log,
#  not the exit code: a remedy is a claim too.)
set -u

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "pushed-tree check: not a git repository — VERIFIED NOTHING"; exit 77; }
cd "$REPO" || exit 77

REF="${1:-HEAD}"
TMP="$(mktemp -d -t pushedtree-XXXXXX)" || {
  echo "pushed-tree check: no temp dir — VERIFIED NOTHING"; exit 77; }
# KEEP_TREE=1 leaves the checkout and the full log on disk. The red path tells you to
# use it, so it has to exist: when the pushed tree is red and your working tree is not,
# the next thing you need is to stand IN the failing tree and run the oracle by hand.
if [ -n "${KEEP_TREE:-}" ]; then
  # ${..:-} because an early exit (clone failed) leaves these unset and `set -u` would
  # turn the trap itself into an error, hiding the real reason we bailed.
  trap 'echo; echo "KEEP_TREE — checkout: ${TREE:-(never created)}"; echo "            full log: ${LOG:-(never created)}"' EXIT
else
  trap 'rm -rf "$TMP"' EXIT
fi

# A real clone: committed content only (nothing from the working tree, nothing
# gitignored) AND a working .git, which the absence-classifiers need. This is what a
# fresh clone or a CI checkout receives.
TREE="$TMP/tree"
if ! git clone -q "$REPO" "$TREE" 2>/dev/null || ! git -C "$TREE" checkout -q "$REF" 2>/dev/null; then
  echo "pushed-tree check: could not clone/checkout $REF — VERIFIED NOTHING"; exit 77
fi
[ -f "$TREE/nucleus/check.sh" ] || {
  echo "pushed-tree check: $REF carries no nucleus/check.sh — VERIFIED NOTHING"; exit 77; }

echo "pushed-tree check: running nucleus/check.sh against $REF ($(git rev-parse --short "$REF"))"
echo "  (gitignored estate is absent by construction — check.sh names every gate it"
echo "   therefore could not verify; read that list, it is what CI will not check either)"
echo

LOG="$TMP/check.log"
( cd "$TREE" && CHECK_ALLOW_SKIP=1 PY="${PY:-python3}" bash nucleus/check.sh ) >"$LOG" 2>&1
rc=$?

# check.sh owns the verdict; we only relay it and, on red, name the likeliest cause.
# Its own summary block (FAILED / UNVERIFIED / the verdict line) is the report — this
# must never restate the verdict in its own words, or it becomes a second writer of the
# one fact that matters and can out-claim the gate it is quoting.
awk '/^FAILED \(|^UNVERIFIED \(/{f=1} f{print} !f && /^check: /{print}' "$LOG"

if [ "$rc" -ne 0 ]; then
  echo
  echo "RED IN THE PUSHED TREE — this does NOT reproduce on this machine's working tree."
  echo "The usual cause is an oracle whose SUBJECT was never committed. Tracked files"
  echo "that differ between your working tree and $REF (any of these could be the subject):"
  git diff --name-only "$REF" -- | sed 's/^/  M /'
  git ls-files --others --exclude-standard | sed 's/^/  ? /'
  echo
  echo "To stand in the failing tree yourself: KEEP_TREE=1 $0 $REF"
fi
exit "$rc"
