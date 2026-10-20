"""Authored mutants for outbound_stuck's SUPERSEDED class (steward 10-20, #61464): a dead row whose IDENTICAL copy was
delivered later is reported once and never resent. The body is gitignored: OUTBOUND_STUCK_STAGED names a staged copy.

    venv/bin/python devtools/mutation_probe.py tests/mutants_outbound_stuck_superseded.py
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)
SUBJECT = Path(os.environ.get("OUTBOUND_STUCK_STAGED") or ESTATE / "triggers" / "steward" / "outbound_stuck.py")
ORACLE = REPO / "tests" / "test_outbound_stuck.py"
ENV = "OUTBOUND_STUCK_SRC"

MUTANTS = {
    "S1 a later copy need not be identical (any same-opening delivered row supersedes: a candidate read as a verdict)":
        ("                \"AND regexp_replace(x.body, '\\\\s+', ' ', 'g') = regexp_replace(s.body, '\\\\s+', ' ', 'g') \"",
         "                \"AND left(x.body, 20) = left(s.body, 20) \""),
    "S2 the copy need not be DELIVERED (a later dead copy supersedes too)":
        ("                \"AND x.status = 'delivered' AND x.from_agent = s.from_agent AND x.to_agent = s.to_agent \"",
         "                \"AND x.from_agent = s.from_agent AND x.to_agent = s.to_agent \""),
    "S3 a superseded row keeps its band (it re-nags at the next one)":
        ("        next_warned[mid] = SUPERSEDED_BAND", "        pass"),
    "S4 superseded rows are dropped silently (never reported, not even once)":
        ("        return (f\"OUTBOUND STUCK — SUPERSEDED ({len(sup)}): an IDENTICAL copy",
         "        return None and (f\"OUTBOUND STUCK — SUPERSEDED ({len(sup)}): an IDENTICAL copy"),
}
