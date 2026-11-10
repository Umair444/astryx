"""Authored mutants for scripts/org_here.sh in a cog (plan-11324 S3f S4), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_ops_cog_here.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts/org_here.sh"
ORACLE = REPO / "tests" / "test_ops_cog.py"
ENV = "OPS_HERE_SRC"
TIMEOUT = 360

MUTANTS = {
    "H1 org_here never sources org_tmux.sh (every tool on the bare default socket: an inherited $TMUX steers it)":
        ('. "$ROOT/scripts/org_tmux.sh"\n', ':\n'),
    "H2 org_here exports no ASTRYX_HOME (children resolve no org: NoHome, or the marker's)":
        ('export ASTRYX_HOME="$ORGH"\n', ':\n'),
    # H3: both refusals gone at once, since either alone is masked by the other (UKEY re-resolves the org itself)
    "H3 org_here guesses an org when none is named (the checkout and the primary's key, never a refusal)":
        ("""  || { echo "org_here: this cog runs several orgs and neither ASTRYX_HOME nor the checkout's .astryx marker names one" >&2; return 3; }
UKEY=$("$ROOT"/venv/bin/python "$ROOT"/src/astryx/orgs.py name) || { echo "org_here: $ORGH is not a registered org" >&2; return 3; }""",
         """  || ORGH=$ROOT
UKEY=$("$ROOT"/venv/bin/python "$ROOT"/src/astryx/orgs.py name) || UKEY=$("$ROOT"/venv/bin/python "$ROOT"/src/astryx/orgs.py primary)"""),
}
