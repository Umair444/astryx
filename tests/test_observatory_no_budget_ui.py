#!/usr/bin/env python3
"""Oracle: the observatory renders no budget economics (goal 4227 follow-up, a2 #23159).

    venv/bin/python tests/test_observatory_no_budget_ui.py     (also run by nucleus/check.sh)
    OBS_SRC_DIR=<dir> …                                         (the subject; mutation_probe)

There are no budgets. spent_tokens has NEVER been written (0 on every goal row), so any bar or
figure built from it reads "unused" where the truth is "never measured". A legacy goal's
budget_tokens is history, shown muted as "budget-era", never as a limit or a progress bar.

  U1 no component RENDERS spent_tokens (the API type in types.ts may still declare it)
  U2 no component SENDS a budget: no `budget_tokens:` key in any request payload
  U3 a component that reads budget_tokens labels it "budget-era" (history, not a limit)
  U4 no <Progress> remains in a component that reads budget_tokens (the bar is gone)

Scans what EXECUTES: comments (//, /* */, and JSX {/* */}) are stripped first, so an
explanatory comment that names spent_tokens can neither fail nor pass this.
"""
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("OBS_SRC_DIR") or REPO / "observatory" / "web" / "src")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def code(text: str) -> str:
    """Strip comments, but not inside strings. A small tokenizer: TS strings and template
    literals are skipped verbatim, and // and /* */ comments are removed."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in "'\"`":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


comps = sorted((SRC / "components").glob("*.tsx")) if (SRC / "components").is_dir() else []
if not comps:
    print(f"SKIP: no components under {SRC} — nothing verified.")
    sys.exit(77)

render_spent, send_budget, unlabeled, bars = [], [], [], []
for f in comps:
    c = code(f.read_text())
    if re.search(r"\bspent_tokens\b", c):
        render_spent.append(f.name)
    if re.search(r"\bbudget_tokens\s*:", c):
        send_budget.append(f.name)
    if re.search(r"\bbudget_tokens\b", c):
        if "budget-era" not in c:
            unlabeled.append(f.name)
        if re.search(r"<Progress\b", c):
            bars.append(f.name)

check("U1 no component renders spent_tokens (never written: 0 means never measured)",
      not render_spent, str(render_spent))
check("U2 no component sends a budget_tokens key", not send_budget, str(send_budget))
check("U3 every component reading budget_tokens labels it 'budget-era'", not unlabeled,
      str(unlabeled))
check("U4 no <Progress> bar in a component that reads budget_tokens", not bars, str(bars))

if fails:
    print(f"\nFAIL: {len(fails)} budget-UI invariant(s) broken")
    sys.exit(1)
print(f"\nPASS: {len(comps)} components render no budget economics")
