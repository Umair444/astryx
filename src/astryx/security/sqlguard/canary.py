"""The sqlguard canary (T5a, a1's B3). One real statement, run through the REAL pulse_run.Ctx.sql and never a
stand-in, so the trace must attribute it to THIS function by walking PAST Ctx.sql, which holds no literal (V2).
Its computed bool column takes both values, so the (P) witness is exercised too.

    venv/bin/python -m astryx.security.sqlguard.canary     # exits 0 after running the statement
"""
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__)))))))
from astryx.paths import repo_root  # noqa: E402
import importlib.util
from pathlib import Path

REPO = repo_root(__file__)


def canary(ctx, floor):
    return ctx.sql("SELECT n, (mod(n, 2) = 0) AS even FROM generate_series(1, 2) AS n WHERE n > %s", (floor,))


if __name__ == "__main__":
    # A committed-only tree (pushed_tree_check, CI) has no .env and maybe no deps, and pulse_run needs both at
    # IMPORT. That's the estate being absent, not the canary failing: 77, reason named. pulse_run stays strict.
    from astryx.security.sqlguard.estate import gate
    gate("canary", REPO, deps=("psycopg", "requests"))      # pulse_run needs .env and both at import
    spec = importlib.util.spec_from_file_location("pulse_run_canary", REPO / "src" / "astryx" / "pulse" / "pulse_run.py")
    pr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pr)
    ctx = pr.Ctx({})
    assert len(canary(ctx, 0)) == 2          # the WHERE admits rows...
    assert len(canary(ctx, 9)) == 0          # ...and excludes them: (W) sees both 0 and >=1
