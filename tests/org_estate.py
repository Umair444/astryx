"""The ONE way a test or mutants file reaches astryx.paths / astryx.config from ITS OWN tree (plan-11324 S3a).

    sys.path.insert(0, str(REPO / "tests")); from org_estate import astryx_call
    ESTATE = astryx_call(REPO, "paths", "estate", __file__)   # this tree on one org, its HOME on several

Side-effect free: no `astryx` module stays imported and no path stays on sys.path, so a later import in the caller
(or one from a temp tree, as test_tool_ledger loads toolreg from its subject copy) never gets this one.
"""
import importlib
import sys


def astryx_call(repo, mod, fn, *args):
    """astryx.<mod>.<fn>(*args), imported from `repo`'s tree (its astryx.py shim / src), then forgotten."""
    had = {k for k in sys.modules if k == "astryx" or k.startswith("astryx.")}
    sys.path.insert(0, str(repo))
    try:
        return getattr(importlib.import_module("astryx." + mod), fn)(*args)
    finally:
        sys.path.remove(str(repo))
        for k in [k for k in sys.modules if (k == "astryx" or k.startswith("astryx.")) and k not in had]:
            del sys.modules[k]
