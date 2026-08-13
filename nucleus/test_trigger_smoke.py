#!/usr/bin/env python3
"""No trigger file references a name that does not exist.

THE INCIDENT THAT EARNED THIS (2026-08-14, 22:13-22:17). Three agents wrote into
triggers/seed/tool_ship_watch.py within two hours. Every individual gate held —
abstractor-1's dryrun 11/11, abstractor-3's oracle green, both reviewed before deploy.
The break was in the SEAM: abstractor-1's rewrite dropped a module-level helper
`_mentions` while abstractor-3's trigger_ship_watch, untouched in the same file, still
called it. NameError on every tick, and a dead trigger presents as SILENCE — so the
watcher built to say "blind looks exactly like quiet" went blind quietly.

No per-proposal oracle could catch it: each legitimately tests ITS OWN function against
ITS OWN staged copy. Whether the MERGED file still resolves every name it references is a
property of the file after integration, belonging to no contributor.

WHY STATIC AND NOT A RUNTIME SMOKE TEST — I built the runtime version first and it failed
in BOTH directions, which is worth recording so nobody rebuilds it:
  - It MISSED the motivating bug. Driving each @trigger with a stub ctx whose queries
    return empty makes most triggers return early, so the line calling `_mentions` was
    never reached. Removing the helper produced no new failure. A check that cannot reach
    the defect cannot observe it.
  - It went RED ON CORRECT CODE. steward's pii_sweep does `row[0]["m"]` after
    `SELECT COALESCE(MAX(id),0)` — an aggregate without GROUP BY always returns exactly
    one row, so it is safe in production and only the stub's empty list broke it. A gate
    that reddens on healthy code trains people to ignore it, which is worse than the gap.
Static undefined-name analysis has neither problem: it does not execute, so no code path
can hide a bad reference, and it has no stub to be wrong about the substrate.

SCOPE, deliberately narrow: this asserts REACHABILITY, never behaviour. A trigger's logic
is its author's oracle's job. Shallow is what lets it cover every agent's directory
without knowing anything about any of them.

pyflakes is a `dev`-group dependency — never installed by init, never checked by doctor —
so this SKIPS (77) where it is absent, per nucleus/check.sh's convention. Skipping loudly
beats passing vacuously.

Run: venv/bin/python nucleus/test_trigger_smoke.py
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRIGGERS = REPO / "triggers"


def main() -> int:
    if not TRIGGERS.is_dir():
        print("SKIP: triggers/ absent (gitignored — a clean clone has no bodies to check). "
              "Nothing was verified here.")
        return 77

    files = [f for f in sorted(TRIGGERS.glob("*/*.py")) if "__pycache__" not in f.parts]
    if not files:
        print("SKIP: triggers/ present but holds no python bodies. Nothing was verified.")
        return 77

    try:
        import pyflakes  # noqa: F401
    except ImportError:
        print("SKIP: pyflakes not installed (dev group, never installed by init). "
              "Nothing was verified here — `venv/bin/pip install pyflakes` to run it.")
        return 77

    r = subprocess.run([sys.executable, "-m", "pyflakes", *[str(f) for f in files]],
                       capture_output=True, text=True)

    # ONLY undefined names. pyflakes also reports unused imports and shadowing, which are
    # style, not reachability — failing a guard on those would make this gate an opinion
    # and get it disabled. A name that does not resolve is not an opinion.
    bad = [ln for ln in (r.stdout + r.stderr).splitlines() if "undefined name" in ln]
    if bad:
        for ln in bad:
            print(f"  \033[31m✗\033[0m {ln}")
        print(f"\n{len(bad)} unresolved reference(s) across {len(files)} trigger file(s). "
              f"Each one is a trigger that throws on the tick that reaches it — and a dead "
              f"trigger presents as SILENCE, so its guard is off until this is fixed.")
        return 1

    print(f"  {len(files)} trigger file(s): every referenced name resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
