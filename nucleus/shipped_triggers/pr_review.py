"""astryx · pr-review — the review half of the self-healing loop (SHIPPED REFERENCE).

The medic (agents/medic.example.md) diagnoses org problems and raises PRs; this trigger
is the other half: it watches for open PRs / medic branches and wakes the REVIEWING agent
(steward — the org's immune system) with the review protocol. Proposer and reviewer are
never the same mind: gates are per-contribution, and the seam belongs to nobody.

Detection, in order of capability:
  - `gh pr list` when the repo has a GitHub remote and gh — reviews ALL open PRs
  - fallback: `medic/*` branches that are ahead of main and have no PR

Standing-condition semantics (guard-silence law): an open PR re-nags every RENAG_H until
it is merged or closed; dedup is on the SET of open items, so a new PR joining re-rings
even if an old one was already nagging; recovery (list empty) re-arms.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from astryx import trigger

REPO = Path(__file__).resolve().parents[2]
RENAG_H = 24

PROTOCOL = (
    "Review protocol (accept/reject, never rubber-stamp): (1) read the diff — does it do "
    "ONLY what its diagnosis claims? (2) verify the CLAIM against the substrate: reproduce "
    "the symptom on main, confirm the branch kills it, run nucleus/check.sh on the branch; "
    "(3) accept = merge with a one-line reason; reject = close/comment with the exact "
    "evidence that failed — a rejection teaches the medic, a silent close teaches nothing; "
    "(4) a remedy is a claim too: check what the fix TOUCHES, not just what it says.")


def _run(cmd: list[str], timeout: int = 15) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=REPO)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def _open_items() -> list[str] | None:
    """Open PRs (preferred) or unreviewed medic/* branches. None = cannot observe."""
    out = _run(["gh", "pr", "list", "--state", "open",
                "--json", "number,title,headRefName"])
    if out is not None:
        try:
            return [f"PR #{p['number']} ({p['headRefName']}): {p['title'][:80]}"
                    for p in json.loads(out)]
        except Exception:
            return None
    # no gh / no remote: medic branches ahead of main are the review queue
    out = _run(["git", "branch", "--list", "medic/*", "--format=%(refname:short)"])
    if out is None:
        return None
    items = []
    for b in out.split():
        ahead = _run(["git", "rev-list", "--count", f"main..{b}"])
        if ahead and int(ahead.strip() or 0) > 0:
            items.append(f"branch {b} ({ahead.strip()} commits ahead, no PR)")
    return items


@trigger("*/30 * * * *",
         note="pr-review: wake the reviewer for open PRs / medic branches — the accept/"
              "reject half of the self-healing loop; re-nags daily while open")
def pr_review(ctx):
    items = _open_items()
    if items is None:
        return None                       # cannot observe (no git/gh here) — stay silent
    ctx.state["last_scan"] = {"ts": round(time.time()), "open": len(items)}
    if not items:
        ctx.state.pop("nag", None)        # queue drained — re-arm
        ctx.state.pop("seen", None)
        return None
    key = sorted(items)
    seen = ctx.state.get("seen")
    fresh = key != seen
    last = ctx.state.get("nag", 0)
    if not fresh and time.time() - last < RENAG_H * 3600:
        return None
    ctx.state["nag"] = time.time()
    ctx.state["seen"] = key
    return ("review queue (" + str(len(items)) + " open): "
            + " | ".join(items[:5]) + ". " + PROTOCOL)
