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
#   3. TRANSIENT LINKS ARE PLACED, RECORDED, REMOVED AND VERIFIED GONE. The live ESTATE is linked into the scratch
#      worktree for the full check only, and only the links this script made are removed; a survivor exits 3. The set
#      is DERIVED, never hand-kept (a1 #40418: a hand list of 5 left agents/abstractors/ out, and test_plan_lifecycle
#      read 15 FAIL on main as an artifact): every gitignored path git reports, minus ESTATE_EXCLUDE (the SAME list as
#      nucleus/sqlguard/ledger.py, parity-checked by the oracle), plus the runtime necessities, minus a DECLARED skip.
#      Per ENTRY, so a gitignored subdir of a tracked dir gets its own link (a whole-dir link would nest), and an
#      entry that is a DIRECTORY is rebuilt as real directories of per-FILE links (a walker skips a linked dir).
#      AN INTERRUPT CLEANS UP TOO: INT/TERM/HUP stop the check, remove the links and the tree, exit 130. (The check
#      runs in the background and is WAITED on: bash defers a trap until a foreground child exits, so a TERM during
#      an hour-long check would otherwise clean nothing until it ended. A run stopped this way left 38 live links in
#      /tmp, a4 10-10.) SIGKILL cannot be trapped: a run starting later NAMES any scratch tree still holding live
#      links, and removes nothing (it may be someone else's run in progress).
#   4. LIVE WRITES ARE REPORTED (a1 R2): the links are LIVE, so anything changed in a linked path during the run is
#      named. It is NOT ATTRIBUTED: the estate has other writers (a resident's self_edit, memory's compile, a trigger
#      a merge installs), and a mtime cannot tell them from the run. A named path is a lead to read, not a verdict.
# Output, at the end: the base sha, the merged sha, the merged tree's FAILED set, and pushed_tree_check's rc for the
# merged tree AND for the base (the control) at the SAME sha. It judges nothing beyond that: a FAILED set still has
# to be read against main's own (a set that is "the same as every tree" is a claim; measure its members live).
#
# Env: MERGE_CHECK_FULL=0 skips the full check (pushed-tree only); MERGE_CHECK_CHECK / MERGE_CHECK_PTC override the
# two commands (the oracle's stubs). Exit: 0 ran (read the report), 2 conflict / bad ref, 3 a link survived.
set -uo pipefail
# LIVE is the MAIN working tree (it holds the estate), even when this copy runs from a linked worktree: git's common
# dir is the main repo's .git, and its parent is the live tree.
_here="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")/.." && pwd)"
_common=$(git -C "$_here" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || {
  echo "merge_check: not inside a git repository ($_here)"; exit 2; }
LIVE="$(cd "$_common/.." && pwd)"
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
git worktree list --porcelain | sed -n 's/^worktree //p' | grep '/merge-check\.[^/]*/tree$' | while IFS= read -r o; do
  n=$(find "$o" -type l -lname "$LIVE/*" 2>/dev/null | wc -l)
  [ "$n" -gt 0 ] && echo "  ORPHAN? a scratch tree holds $n live link(s): $o (a killed run, or a run in progress; not touched)"
done
if [ "${MERGE_CHECK_FULL:-1}" != 0 ]; then
  git worktree add --detach "$WT" "$T" >/dev/null 2>&1 || { echo "merge_check: worktree failed"; exit 2; }
  made=()
  ESTATE_EXCLUDE="venv/ .venv/ homes/ node_modules/ backups/ media/ observatory/web/dist/ .env"   # == ledger.py's
  RUNTIME=".env venv channel/node_modules"                     # excluded from the ESTATE, needed to RUN
  SKIP="var/"                                                   # declared: runtime state, regenerable
  estate=$(git -C "$LIVE" ls-files --others --ignored --exclude-standard --directory | while IFS= read -r p; do
    case "$p" in *__pycache__*|*.pyc) continue ;; esac
    keep=1; for e in $ESTATE_EXCLUDE $SKIP; do case "/$p" in "/$e"*|*"/$e"*) keep=0 ;; esac; [ "$p" = "$e" ] && keep=0; done
    [ "$keep" = 1 ] && echo "${p%/}"; done)
  MARK="$WT.mark"; : > "$MARK"; sleep 1
  # An estate DIRECTORY is rebuilt as REAL directories holding per-FILE links, never one link to the directory:
  # Python's rglob/os.walk (and find) don't descend a symlinked directory, so a dir link hid agents/painter/ from
  # agent_exists() and 7 gates read red here on ANY tree, main's own included (painter #42999, a4 10-10). A file
  # the run CREATES therefore stays in the scratch tree; a write THROUGH a linked file still reaches live (reported
  # below). RUNTIME stays whole-directory links: nothing walks venv or channel/node_modules.
  for e in $estate; do
    if [ -d "$LIVE/$e" ] && [ ! -L "$LIVE/$e" ]; then
      ( cd "$LIVE" && find "$e" \( -name __pycache__ -o -name node_modules \) -prune -o -type d -print ) \
        | while IFS= read -r d; do mkdir -p "$WT/$d"; done
      ( cd "$LIVE" && find "$e" \( -name __pycache__ -o -name node_modules \) -prune -o ! -type d -print )
    else echo "$e"; fi
  done > "$WT.links"
  for l in $RUNTIME; do echo "$l"; done >> "$WT.links"
  while IFS= read -r l; do
    if { [ -e "$LIVE/$l" ] || [ -L "$LIVE/$l" ]; } && [ ! -e "$WT/$l" ] && [ ! -L "$WT/$l" ]; then
      mkdir -p "$(dirname "$WT/$l")" && ln -s "$LIVE/$l" "$WT/$l" && made+=("$l"); fi
  done < "$WT.links"
  LOG="$WT.full.log"
  unlink_all() { for l in "${made[@]}"; do rm -f "${WT:?}/$l"; done; }
  interrupted() {
    kill -TERM "$cpid" 2>/dev/null; wait "$cpid" 2>/dev/null; unlink_all
    left=0; for l in "${made[@]}"; do { [ -e "$WT/$l" ] || [ -L "$WT/$l" ]; } && left=$((left + 1)); done
    [ "$left" = 0 ] && git worktree remove --force "$WT" >/dev/null 2>&1
    echo "  INTERRUPTED: check stopped, ${#made[@]} link(s) removed, $left survived"; exit 130
  }
  (cd "$WT" && exec timeout 3600 bash -c "$CHECK") > "$LOG" 2>&1 &
  cpid=$!
  trap interrupted INT TERM HUP
  wait "$cpid"; crc=$?
  trap - INT TERM HUP
  echo "  full check rc=$crc (log: $LOG)"
  unlink_all
  for l in "${made[@]}"; do
    if [ -e "$WT/$l" ] || [ -L "$WT/$l" ]; then echo "  LINK SURVIVED: $l"; rc_links=3; fi
  done
  echo "  linked ${#made[@]} estate path(s)"
  wrote=$(for l in $estate; do
    find "$LIVE/$l" -newer "$MARK" -not -path '*__pycache__*' -not -name '*.pyc' 2>/dev/null; done | head -20)
  [ -n "$wrote" ] && { echo "  LIVE WRITES during the run (a linked path is PRODUCTION; NOT ATTRIBUTED: the run OR a concurrent writer):"; echo "$wrote" | sed 's/^/    /'; }
  sed 's/\x1b\[[0-9;]*m//g' "$LOG" | tac | sed -n '/^check:/,/^FAILED (/p' | tac | sed -n '/^FAILED (/,/^UNVERIFIED/p' \
    | grep -v '^UNVERIFIED' | sed 's/^/  /'
  [ "$rc_links" = 0 ] && git worktree remove --force "$WT" >/dev/null 2>&1
fi
bash -c "$PTC \"\$1\"" _ "$T" > "$WT.ptc-merged.log" 2>&1; echo "  pushed_tree_check merged ${T:0:7} rc=$?"
bash -c "$PTC \"\$1\"" _ "$M" > "$WT.ptc-base.log" 2>&1;  echo "  pushed_tree_check base   ${M:0:7} rc=$? (the control, the SAME sha)"
exit "$rc_links"
