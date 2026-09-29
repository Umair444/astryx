"""The sqlguard canary (T5a, a1's B3). One real statement, run through the REAL pulse_run.Ctx.sql and never a
stand-in, so the trace must attribute it to THIS function by walking PAST Ctx.sql, which holds no literal (V2).
Its computed bool column takes both values, so the (P) witness is exercised too.

    venv/bin/python -m nucleus.sqlguard.canary     # exits 0 after running the statement
"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def canary(ctx, floor):
    return ctx.sql("SELECT n, (mod(n, 2) = 0) AS even FROM generate_series(1, 2) AS n WHERE n > %s", (floor,))


if __name__ == "__main__":
    spec = importlib.util.spec_from_file_location("pulse_run_canary", REPO / "nucleus" / "pulse_run.py")
    pr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pr)
    ctx = pr.Ctx({})
    assert len(canary(ctx, 0)) == 2          # the WHERE admits rows...
    assert len(canary(ctx, 9)) == 0          # ...and excludes them: (W) sees both 0 and >=1
