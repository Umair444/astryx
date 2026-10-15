#!/usr/bin/env bash
# sqlsite.sh — what sqlguard will say about the SQL sites ONE oracle drives, in seconds instead of a full check.
#
#   devtools/sqlsite.sh tests/test_x.py [site-substring]           # per site: rung, and WHY (rows seen, stamped, p)
#   devtools/sqlsite.sh --ledger tests/test_x.py <prefix> [...]    # + what enforce would say against ledger.json
#
# Default mode (medic's probe, homes/medic/probes/sqlsite.sh, night-review 10-15): a passing test is not a site the
# gate credits. RESPONSIVE needs (W) a WHERE that returned both 0 and ≥1 rows on a STAMPED fixture, and asyncpg
# fetchval records no row count at all (rows=-1), so a site read through it never climbs.
# --ledger (painter, 10-16, after obs-late-replies spent three ~13-minute merge_check rounds on this): for every
# site under a prefix (path::function, e.g. observatory/api/main.py::memory_), including UNEXECUTED ones:
#   ok             RESPONSIVE and unlisted, or below it and listed (admitted debt)
#   R-NEW          below RESPONSIVE and unlisted: add the arm it lacks, or `ledger admit`
#   R-STALE        listed, now RESPONSIVE: `ledger shrink` is due
#   R-STALE absent a listed key under the prefix that this run never saw (re-texted or deleted)
# It also warns when the oracle has no run line in devtools/check.sh.
#
# ADVISORY. One oracle sees only its own sites: a site another gate drives can grade lower here than in the full
# run, and enforce's run-level rules (EX3 extractors, R-CLOCK, R-LEAK) aren't modelled. merge_check is the verdict.
# Writes nothing outside its temp dir: no admit, no shrink, no sqlguard_seen (judge only, never enforce).
# Records are attributed to sites by judge's own frame rule (judge.attribute), never by text substring.
#
# rc: 0 clean · 1 a finding (--ledger) or the oracle failed · 2 usage · 77 SKIP (no .env: fixture_db can't run)
# SQLSITE_ROOT picks the checkout (default: this script's); SQLGUARD_LEDGER overrides the ledger file (tests).
set -euo pipefail
LEDGER_MODE=0
[ "${1:-}" = "--ledger" ] && { LEDGER_MODE=1; shift; }
T="${1:-}"
[ -n "$T" ] && { [ "$LEDGER_MODE" = 0 ] || [ $# -ge 2 ]; } || { sed -n 4,5p "$0"; exit 2; }
shift
cd "${SQLSITE_ROOT:-$(dirname "$0")/..}"
ROOT=$PWD
[ -e .env ] || { echo "SKIP: no .env in $ROOT (fixture_db reads the DSN from it; in a worktree, link it for the run)"; exit 77; }
PY=${PY:-$ROOT/venv/bin/python}
if [ ! -x "$PY" ]; then                                  # a worktree has no venv: use the main checkout's
  PY="$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)/venv/bin/python"
fi
D="$(mktemp -d "${TMPDIR:-/tmp}/sqlsite.XXXXXX")"; trap 'rm -rf "$D"' EXIT
export ASTRYX_RUNSCOPE_TEST=1 ASTRYX_SQLGUARD_RUN="rsqlsite$$" ASTRYX_SQLGUARD_DIR="$D" PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT/src/astryx/security/sqlguard/shim${PYTHONPATH:+:$PYTHONPATH}"
echo "$ASTRYX_SQLGUARD_RUN" > "$D/run_id"
if [ "$LEDGER_MODE" = 1 ] && ! command grep -qF " $T" devtools/check.sh; then
  echo "! $T has no run line in devtools/check.sh (the coverage gate goes red, and nothing drives its sites)"
fi
rc=0; env -u ASTRYX_AGENT "$PY" "$T" >"$D/test.out" 2>&1 || rc=$?
echo "test $T rc=$rc"
[ "$rc" = 0 ] || { echo "test FAILED: the grades below are not evidence. Its tail:"; tail -5 "$D/test.out" | sed 's/^/  | /'; }
"$PY" -W ignore::SyntaxWarning - "$D" "$LEDGER_MODE" "${SQLGUARD_LEDGER:-$ROOT/src/astryx/security/sqlguard/ledger.json}" "$rc" "$@" <<'EOF'
import collections, json, sys
from astryx.security.sqlguard import inventory, judge
from astryx.security.sqlguard.privacy import ledger_key
d, ledger_mode, ledger_path, test_rc, args = sys.argv[1], sys.argv[2] == "1", sys.argv[3], int(sys.argv[4]), sys.argv[5:]
inv = inventory.build()
rep = judge.judge(d, inv=inv)
seen = collections.defaultdict(list)                     # site key -> its records, by judge's own attribution
for r in judge.load_traces(d)[0]:
    if not judge.is_site(r["t"], form="statement"):
        continue
    key, text, kind = judge.attribute(r, inv["functions"], inv.get("oracle"))
    if kind in ("site", "fallback"):
        seen[f"{key}\x1f{text}"].append(r)
show = lambda k: k.replace("\x1f", " :: ")[:150]
def why(k):
    recs = seen.get(k, [])
    rows = sorted({r.get("rows") for r in recs}, key=str)
    stamped = sorted({str(r.get("stamped")) for r in recs})
    pcols = sorted({c for r in recs for c in (r.get("p") or {})})
    return f"rows={rows} stamped={stamped} p={pcols}"
if not ledger_mode:
    pat = args[0] if args else ""
    for k, s in sorted(rep["sites"].items()):
        if s["rung"] == "UNEXECUTED" or (pat and pat not in k):
            continue
        flag = "" if s["rung"] == "RESPONSIVE" else "   <- below RESPONSIVE: a NEW site here is RED R-NEW"
        print(f"{s['rung']:<11} {show(k)}  {why(k)}{flag}")
    sys.exit(1 if test_rc else 0)
rows = json.load(open(ledger_path))["rows"]
mine = lambda k: any(k.startswith(p) for p in args)
bad, live = 0, set()
for k, s in sorted(rep["sites"].items()):
    if not mine(k):
        continue
    lk = ledger_key(k)
    live.add(lk)
    listed, resp = lk in rows, s["rung"] == "RESPONSIVE" and not s.get("live_only")
    v = "R-STALE" if listed and resp else "R-NEW" if not listed and not resp else "ok"
    bad += v != "ok"
    print(f"{v:<15} {s['rung']:<20} {show(k)}  {why(k)}")
for lk in sorted(rows):
    if mine(lk) and lk not in live:
        bad += 1
        print(f"{'R-STALE absent':<15} {'(key not seen)':<20} {show(lk)}")
print(f"{'clean' if not bad else f'{bad} finding(s)'} under {args}. ADVISORY: one oracle's view; merge_check is the verdict")
sys.exit(1 if bad or test_rc else 0)
EOF
