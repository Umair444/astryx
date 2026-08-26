#!/usr/bin/env python3
"""Oracle for nucleus/legend_guard.py — the economy heat-definition drift guard (goal 3408).

Every arm that names an INVERSION was run RED first against a guard that would wave it
through; each is a real failure mode, not a restatement of the code:

  1. the DEFECT itself (Q = Φ − W, flux − budget) must be caught — the abstractor-1 finding.
  2. the FIX (Q = Φ − phi_goal_attributed, flux − flux) must PASS — conformance-to-spec.
  3. COMMENT/STRING BLINDNESS — the fix carries the words "NOT phi - W" in a comment and
     "Φ = W-attributable + Q" in a label; a guard that reads text, not code, false-fires on
     its own fix. Proven two ways: the guard is silent on comment+string-only source, AND a
     deliberately-WRONG lexical guard (shipped below as the counterexample arm) DOES fire on
     it — an assertion of silence proves nothing unless a plausible wrong guard would speak.
  4. FAIL-CLOSED — a heat output whose subtrahend is an UNKNOWN base is a violation, not OK.
  5. SAME-BASE flux−flux and NON-subtraction forms (division; a direct flux heat value) must
     NOT fire — the guard flags a unit MIX, not every arithmetic op.
  6. the guard holds the REAL live tree (the actual fixed mcp/org/server.py + econ.py) green.

Run by nucleus/check.sh. legend_guard.py is TRACKED (nucleus/), so no SKIP path — the
subject is always present.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from nucleus.legend_guard import scan_source, main as guard_main  # noqa: E402

fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        got:  {got!r}\n        want: {want!r}")
        fails.append(label)


def red(src):
    return len(scan_source(src, "t")) > 0


# ── 1. the DEFECT is caught, in each form it can take ────────────────────────────────
print("DEFECT ARMS — every flux−budget form must be caught:")
check("q = phi - w  (w bound to th['W'])",
      red("def f():\n th={}\n phi,w=th.get('phi'),th.get('W')\n q=phi-w\n return q"), True)
check("heat = phi - th.get('W')  (budget read inline)",
      red("def f():\n th={}\n phi=th.get('phi')\n heat=phi-th.get('W')\n return heat"), True)
check("bare names phi - W",
      red("def f():\n q = phi - W\n return q"), True)
check("reversed W - phi is still a unit mix",
      red("def f():\n th={}\n phi,w=th.get('phi'),th.get('W')\n x=w-phi\n return x"), True)
check("budget differenced against ATTRIBUTED flux too",
      red("def f():\n th={}\n pg,w=th.get('phi_goal_attributed'),th.get('W')\n q=pg-w\n return q"), True)

# ── 2. the FIX passes — conformance-to-spec, not to-defect ───────────────────────────
print("\nFIX ARM — the real fixed shape must PASS:")
FIX = (
    "def economy():\n"
    " th={}\n"
    " phi,w,phi_goal = th.get('phi'),th.get('W'),th.get('phi_goal_attributed')\n"
    " # NOT phi - W: W is a sum of BUDGETS (a price), phi is flux (a cost).\n"
    " glossary = {'Q':'heat = flux - goal-attributed flux'}\n"
    " label = 'first law: Phi = W-attributable + Q'\n"
    " q = (phi - phi_goal) if (phi is not None and phi_goal is not None) else None\n"
    " return q, glossary, label\n")
check("q = phi - phi_goal (flux−flux), amid comment+glossary+label", red(FIX), False)

# ── 3. COMMENT / STRING BLINDNESS — proven BOTH directions ───────────────────────────
print("\nBLINDNESS ARMS — code only, never comments or strings:")
COMMENT_STRING_ONLY = "x = 1  # the defect was q = phi - W\ns = 'Q = phi - W is the folklore'\n"
check("guard is SILENT on comment+string-only source", red(COMMENT_STRING_ONLY), False)


def lexical_wrong_guard(src: str) -> bool:
    """The WRONG guard a reasonable person writes first: grep the raw text for 'phi - W'.
    It fires on the fix's own comment — shipped here so 'the guard is silent' has a
    counterexample proving a plausible wrong guard WOULD have spoken."""
    return ("phi - W" in src) or ("phi-w" in src.replace(" ", ""))


check("the WRONG lexical guard FALSE-fires on comment+string (why AST is load-bearing)",
      lexical_wrong_guard(COMMENT_STRING_ONLY), True)
check("...and the WRONG lexical guard even false-fires on the FIX (its 'NOT phi - W' comment)",
      lexical_wrong_guard(FIX), True)
check("...while the REAL guard stays silent on that same fix", red(FIX), False)

# ── 4. FAIL-CLOSED — a heat output with an unrecognised subtrahend is a violation ─────
print("\nFAIL-CLOSED ARM — unknown subtrahend for a heat output convicts:")
check("heat = phi - mystery  (mystery base unknown) → flagged",
      red("def f():\n phi=1\n mystery=2\n heat = phi - mystery\n return heat"), True)
check("q = phi - phi_goal, phi_goal SOURCED from th['phi_goal_attributed'] (control)",
      red("def f():\n th={}\n phi,phi_goal=th.get('phi'),th.get('phi_goal_attributed')\n q = phi - phi_goal\n return q"), False)
check("...and phi_goal as a bare param (name-recognised, no binding) also passes",
      red("def f(phi, phi_goal):\n q = phi - phi_goal\n return q"), False)

# ── 5. SAME-BASE / NON-SUB forms must NOT fire ───────────────────────────────────────
print("\nNO-FIRE ARMS — the guard flags a unit MIX, not arithmetic:")
check("eta = w / phi (division of price by cost) does not fire",
      red("def f():\n th={}\n w,phi=th.get('W'),th.get('phi')\n eta=w/phi\n return eta"), False)
check("a direct flux heat value (heat_instant_phi/phi) — no subtraction — does not fire",
      red("def f():\n t={}\n frac = t.get('heat_instant_phi') / t.get('phi')\n return frac"), False)
check("phi - phi (flux−flux, both flux) does not fire",
      red("def f():\n phi=1\n d = phi - phi\n return d"), False)

# ── 6. the guard holds the REAL live tree green (substrate, not a fixture) ────────────
print("\nLIVE ARM — the real economy surfaces must be same-base:")
rc = guard_main([])
check("nucleus/legend_guard.py main() exits 0 on the live tree", rc, 0)

print()
if fails:
    print(f"test_legend_guard: {len(fails)} FAIL — {fails}")
    sys.exit(1)
print("test_legend_guard: ALL PASS")
sys.exit(0)
