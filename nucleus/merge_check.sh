#!/usr/bin/env bash
# merge_check.sh <branch> [<base>]: "what will main look like AFTER this merges?", run on that exact tree.
#
# The chain every builder hand-rolls before a merge request (CLAUDE-org rule: full check.sh on the MERGED tree AND
# pushed_tree_check), written once so its three hand-rolled failures can't recur (a4 night-review 10-10):
#   1. THE BASE IS RESOLVED ONCE. `main` is read to a sha a single time, and that sha is the merge parent AND the
#      control's tree. A chain that read the ref twice let main move in between: the merged trees carried a newer
#      main than the "control", and three unrelated branches looked like they regressed main's own gate.
#   2. A CONFLICT IS A REFUSAL, never a wrong tree. `git merge-tree` exits 1 on a conflict; if its first line were
#      fed to commit-tree anyway, an empty tree argument made the "merged" check silently run something else.
#      Exit 2, naming the conflicting paths.
#   3. TRANSIENT LINKS ARE PLACED, RECORDED, REMOVED AND VERIFIED GONE. The live estate (.env, triggers, local.md,
#      channel/node_modules, venv) is linked into the scratch worktree for the full check only; only the links this
#      script made are removed, and any survivor is reported (exit 3).
# Output, at the end: the base sha, the merged sha, the merged tree's FAILED set, and pushed_tree_check's rc for the
# merged tree AND for the base (the control) at the SAME sha. It judges nothing beyond that: a FAILED set still has
# to be read against main's own (a set that is "the same as every tree" is a claim; measure its members live).
#
# Env: MERGE_CHECK_FULL=0 skips the full check (pushed-tree only); MERGE_CHECK_CHECK / MERGE_CHECK_PTC override the
# two commands (the oracle's stubs). Exit: 0 ran (read the report), 2 conflict / bad ref, 3 a link survived.
set -uo pipefail
LIVE="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")/.." && pwd)"
BR=${1:?usage: merge_check.sh <branch> [<base>]}
BASE_REF=${2:-main}
cd "$LIVE" || exit 2
M=$(git rev-parse --verify -q "$BASE_REF^{commit}") || { echo "merge_check: no such base: $BASE_REF"; exit 2; }
B=$(git rev-parse --verify -q "$BR^{commit}") || { echo "merge_check: no such branch: $BR"; exit 2; }
if ! out=$(git merge-tree --write-tree --name-only "$M" "$B" 2>&1); then
  echo "merge_check: $BR CONFLICTS with $BASE_REF@${M:0:7}, refusing (no tree is checked):"
  echo "$out" | sed -n '2,/^$/p' | sed '/^$/d; s/^/  /'
  exit 2
fi
TREE=$(echo "$out" | head -1)
T=$(git commit-tree "$TREE" -p "$M" -p "$B" -m "merge_check: $BR into $BASE_REF@${M:0:7}") || exit 2
echo "merge_check: base $BASE_REF=$M  branch $BR=$B  merged=$T"
WT=$(mktemp -d "${TMPDIR:-/tmp}/merge-check.XXXXXX")/tree
CHECK=${MERGE_CHECK_CHECK:-"bash nucleus/check.sh"}
PTC=${MERGE_CHECK_PTC:-"bash $LIVE/nucleus/pushed_tree_check.sh"}
rc_links=0
if [ "${MERGE_CHECK_FULL:-1}" != 0 ]; then
  git worktree add --detach "$WT" "$T" >/dev/null 2>&1 || { echo "merge_check: worktree failed"; exit 2; }
  made=()
  for l in .env triggers local.md channel/node_modules venv; do
    if [ -e "$LIVE/$l" ] && [ ! -e "$WT/$l" ] && [ ! -L "$WT/$l" ]; then ln -s "$LIVE/$l" "$WT/$l" && made+=("$l"); fi
  done
  LOG="$WT.full.log"
  (cd "$WT" && timeout 3600 bash -c "$CHECK" > "$LOG" 2>&1); echo "  full check rc=$? (log: $LOG)"
  for l in "${made[@]}"; do rm -f "${WT:?}/$l"; done
  for l in "${made[@]}"; do
    if [ -e "$WT/$l" ] || [ -L "$WT/$l" ]; then echo "  LINK SURVIVED: $l"; rc_links=3; fi
  done
  sed 's/\x1b\[[0-9;]*m//g' "$LOG" | tac | sed -n '/^check:/,/^FAILED (/p' | tac | sed -n '/^FAILED (/,/^UNVERIFIED/p' \
    | grep -v '^UNVERIFIED' | sed 's/^/  /'
  [ "$rc_links" = 0 ] && git worktree remove --force "$WT" >/dev/null 2>&1
fi
bash -c "$PTC \"\$1\"" _ "$T" > "$WT.ptc-merged.log" 2>&1; echo "  pushed_tree_check merged ${T:0:7} rc=$?"
bash -c "$PTC \"\$1\"" _ "$M" > "$WT.ptc-base.log" 2>&1;  echo "  pushed_tree_check base   ${M:0:7} rc=$? (the control, the SAME sha)"
exit "$rc_links"
