# org_here.sh — SOURCED, and only from a script's org-home guard once THE predicate said several orgs (`orgs.py multi`
# exit 0, the guard's own call: the census reads each guard for it) (plan-11324 S3f S4, seed
# #60804/#60805): resolve THIS org the one way (ASTRYX_HOME or the checkout's .astryx marker: paths.home), so an
# operator script acts on its own org's estate, units, residents and pulse, never another's. It sets ORGH (the org's
# HOME), UKEY (its registry key), UPRIM (non-empty for the cog's primary), COGH=1; exports ASTRYX_HOME so every child
# resolves the same org; sources org_tmux.sh (`tmux` is this org's server, the primary's named `-L default`); and
# defines org_unit <stem> <suffix> (orgs.unit, the ONE authority). One org never sources it: nothing is asked.
# Returns 3 (the caller exits 3) when no registered org is named or the registry refuses. Needs ROOT (the checkout).
ORGH=$(cd "$ROOT" && venv/bin/python -c 'import sys; sys.path.insert(0, "src"); from astryx import paths; print(paths.home())') \
  || { echo "org_here: this cog runs several orgs and neither ASTRYX_HOME nor the checkout's .astryx marker names one" >&2; return 3; }
UKEY=$("$ROOT"/venv/bin/python "$ROOT"/src/astryx/orgs.py name) || { echo "org_here: $ORGH is not a registered org" >&2; return 3; }
UPRIM=""; [ "$("$ROOT"/venv/bin/python "$ROOT"/src/astryx/orgs.py primary)" = "$UKEY" ] && UPRIM=1
COGH=1
export ASTRYX_HOME="$ORGH"
. "$ROOT/scripts/org_tmux.sh"
org_unit() { "$ROOT"/venv/bin/python "$ROOT"/src/astryx/orgs.py unit "$1" "${2:-service}"; }
