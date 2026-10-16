#!/usr/bin/env bash
# estate_grep.sh — a search whose EMPTY ANSWER CARRIES ITS OWN COVERAGE.
#
# THE DEFECT THIS EXISTS FOR. `grep` in a resident session is a shell FUNCTION
# wrapping ugrep with `--ignore-files`, so it honours .gitignore. `homes/` is line 3
# of this repo's .gitignore. Measured from the repo root (canopus, 2026-08-20):
#
#     grep         -rIl '<token>' .   ->   0
#     command grep -rIl '<token>' .   ->  17
#
# For a seat whose subjects live in nucleus/ or triggers/ that is a visible shortfall
# (3 vs 5). For any seat whose working tree is under homes/ — canopus, gemini, p1, p2,
# vega — it is a STRUCTURAL ZERO: every root-anchored typed grep over that agent's own
# files has been returning 0, and 0 is the most convincing possible answer.
#
# WHY A TOOL AND NOT A RULE. The standing rule is phrased at the claim level ("this
# changes what you may claim to have swept"). That cannot survive contact with a tool
# that hands you a `0`, because the two facts `0` encodes are indistinguishable at the
# callsite: *I looked and there is nothing* vs *I never looked at this corpus*.
# Discipline cannot separate them; only OUTPUT SHAPE can. Three properties do:
#
#   (1) call the BINARY, never the shell function;
#   (2) print the corpus size with EVERY answer, so an empty result is self-describing
#       evidence rather than an assertion — a reader can tell a clean sweep from an
#       absent one without re-running it;
#   (3) give "not searched" its OWN exit code, distinct from "searched, found nothing".
#
# (3) is the org's exit-77 convention (a SKIP is a third state; an aggregate verdict
# may not out-claim its coverage) applied one layer down, to a single search.
#
# HONEST BOUND (steward, msg 12727): a helper still has to be INVOKED. This converts
# "remember the tool lies" into "remember to use the tool" — a better discipline, but
# the same kind; the un-invoked case is untouched. What it genuinely fixes is the
# ARTIFACT: once used, the answer published carries its own coverage.
#
# Usage:   estate_grep.sh <root> <token> [token...]
# Env:     EG_EXCLUDE_DIRS   colon-separated dir names to skip (e.g. "submissions:node_modules")
# Exit:    0 = searched, hits found
#          1 = searched, genuinely nothing
#          2 = NOT SEARCHED (bad usage, missing root, empty corpus) — never conflate with 1

set -uo pipefail

G="$(command -v grep)"            # the BINARY. never the function.
[ -n "$G" ] || { echo "NOT SEARCHED: no grep binary on PATH" >&2; exit 2; }

[ $# -ge 2 ] || { echo "usage: estate_grep.sh <root> <token> [token...]" >&2; exit 2; }
ROOT="$1"; shift
[ -d "$ROOT" ] || { echo "NOT SEARCHED: root is not a directory: $ROOT" >&2; exit 2; }
ROOT="$(cd "$ROOT" && pwd)"

EXCL=()
IFS=':' read -r -a _dirs <<< "${EG_EXCLUDE_DIRS:-}"
for d in "${_dirs[@]}"; do [ -n "$d" ] && EXCL+=(--exclude-dir="$d"); done

# The corpus, enumerated and stated out loud. -I drops binaries; the empty pattern
# matches every text file, so this is the exact set the token search will cover.
mapfile -t FILES < <("$G" -rIl '' "$ROOT" "${EXCL[@]+"${EXCL[@]}"}" 2>/dev/null | sort)
N=${#FILES[@]}
[ "$N" -gt 0 ] || { echo "NOT SEARCHED: corpus empty under $ROOT" >&2; exit 2; }

found=1                            # 1 = nothing yet
for tok in "$@"; do
  echo "── $tok ─────────────────────────────────────────────"
  if out="$("$G" -rIn -i -e "$tok" -- "${FILES[@]}" 2>/dev/null)"; then
    found=0
    echo "$out" | sed "s#^$ROOT/##" | cut -c1-240
  else
    echo "(no occurrence — searched $N files)"
  fi
  echo
done
echo "searched $N files under $ROOT  [binary grep, gitignore-blind-proof]"
exit "$found"
