#!/usr/bin/env python3
"""Oracle for owner_queue_age's RESTORE-INDEPENDENT age signal (triggers/steward/owner_queue_age.py).

    venv/bin/python tests/test_owner_queue_age.py      (also run by nucleus/check.sh)

THE GAP THIS PINS (2026-09-13, my own guard). owner_queue_age flags public-destined work
that sits uncommitted past AGE_DAYS at the owner gate. It USED to age by filesystem mtime —
but mtime is a liveness surface that lies: a working-tree restore/refresh sets every mtime to
now(), zeroing the age-clock. A restart on 09-13 restored the tree at 06:18 and reset 7 files;
a ~2.5-week-old uncommitted pile then read as 16h old (< the 3d band) and the guard skipped it
for weeks. False-staleness class, biting the guard's own instrument. The fix ages from a
CONTENT-FIRST-SEEN ledger in ctx.state (DB-backed, so a working-tree restore can't touch it):
content survives the restore, mtime does not.

The oracle drives the PURE core `_age_uncommitted(entries, ledger, now)` — entries are
(path, content_hash, mtime) — so it can simulate a restore deterministically without a real
git tree or a real clock. It SKIPS (77) only if the gitignored trigger is absent (a clone),
never passes on absence.

RED-FIRST. The load-bearing arm is RESTORE-RESILIENCE: a stable-content file whose mtime was
reset to now() by a restore must STILL age from when its content was first seen. The pre-fix
mtime logic scored that gap at ~0d and skipped it — this arm fires against it. Verified by the
inline control below that recomputes the OLD mtime age for the same scenario and asserts it
WOULD have been skipped, so a regression back to mtime turns this arm red.

Exit 0 pass · 1 fail · 77 the oracle could not run (trigger absent on a clone).
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXIT_SKIP = 77
fails = []

sys.path.insert(0, str(REPO))
# Load the trigger BY PATH, not `from triggers.steward import ...`. A STATIC triggers import in
# a committed file reads as an unmanifested third-party dep in a clean clone: triggers/ is
# gitignored, so it is EMPTY there and deps.py (line ~68, rglob) no longer sees it as first-party
# → `dep manifest covers all imports` FAILS the pushed-tree gate (the try/except below cannot help
# a STATIC AST scan). Path-load is invisible to that scan and matches the real precedent
# (test_spawn_drift), while still SKIP-77-ing cleanly when the gitignored body is absent.
import importlib.util
BODY = REPO / "triggers" / "steward" / "owner_queue_age.py"
if not BODY.exists():
    print("SKIP: owner_queue_age trigger absent (gitignored body, fresh clone) — nothing asserted.")
    sys.exit(EXIT_SKIP)
try:
    _spec = importlib.util.spec_from_file_location("owner_queue_age_under_test", BODY)
    m = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(m)
except Exception as e:  # noqa: BLE001 — absent/unimportable body => SKIP, not a false pass
    print(f"SKIP: owner_queue_age not importable ({type(e).__name__}: {e}) — nothing asserted.")
    sys.exit(EXIT_SKIP)

age = m._age_uncommitted
AGE = m.AGE_DAYS
DAY = 86400.0
T = 1_000_000_000.0


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok and detail:
        print(f"        {detail}")
    if not ok:
        fails.append(name)


# ── LOAD-BEARING: a restore that resets mtime must NOT hide genuinely-old work ──────────
# run 1: first sight, content H, mtime 5d old (an aged uncommitted file).
aged1, led = age([("f.py", "H", T - 5 * DAY)], {}, T)
check("first sight seeds age from mtime (5d file flags)", any(p == "f.py" for p, _ in aged1),
      f"expected f.py aged >= {AGE}d, got {aged1}")

# run 2: a RESTORE reset mtime to now(); content is UNCHANGED (same hash).
aged2, led = age([("f.py", "H", T + 1)], led, T + 1)
restored_age = next((a for p, a in aged2 if p == "f.py"), None)
check("RESTORE resets mtime but content is stable -> STILL flagged (the gap this fix closes)",
      any(p == "f.py" for p, _ in aged2),
      "a working-tree restore zeroed mtime and the guard went blind — the 09-13 pile bug")
check("...and the age PERSISTS across the restore (~5d, not reset to 0)",
      restored_age is not None and restored_age > 4.9,
      f"age should carry from content-first-seen, got {restored_age}")

# the RED-catcher, explicit: the OLD mtime logic would have scored run-2 at ~0d and SKIPPED it.
old_mtime_age = (T + 1 - (T + 1)) / DAY
check("CONTROL: the pre-fix mtime age for run-2 is below the band (proves this is a real gap)",
      old_mtime_age < AGE,
      f"old mtime age {old_mtime_age} — if this ever >= {AGE} the scenario stopped exercising the gap")

# ── CONTROL: active WIP (content churns) must NOT trip — it is being edited, not stalled ──
led2 = {}
age([("g.py", "H1", T - 5 * DAY)], led2, T)          # seen once...
aged_edit, led2 = age([("g.py", "H2", T)], led2, T)   # ...then content CHANGED -> clock resets
check("active edit (content hash churns) resets the clock -> not flagged as stalled",
      not any(p == "g.py" for p, _ in aged_edit),
      f"a churning file is active WIP, must not read as owner-gate-stalled; got {aged_edit}")

# ── CONTROL: a file that left the tree heals out of the ledger (committed/removed) ───────
_, led3 = age([], {"gone.py": ["H", T - 9 * DAY]}, T)
check("a committed/removed file heals from the ledger", "gone.py" not in led3,
      "ledger must prune to live paths or it leaks + mis-ages a returning path")

# ── CONTROL: a fresh file under the band does not flag (no false positive) ───────────────
aged_new, _ = age([("h.py", "H", T - 0.5 * DAY)], {}, T)
check("a genuinely-fresh file (< band) does not flag", not any(p == "h.py" for p, _ in aged_new),
      f"a 12h-old file must be under the {AGE}d band; got {aged_new}")

print()
if fails:
    print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    sys.exit(1)
print("owner_queue_age ages by content-first-seen: restore-resilient, active-WIP-safe, self-healing")
sys.exit(0)
