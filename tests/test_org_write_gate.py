#!/usr/bin/env python3
"""Role-gate invariants for the org MCP write tools (mcp/org/server.py) — goal t-org-grant.

seed's ask: make grant:org safe to grant WIDELY (so abstractors get read tools instead of a
raw-psql+DSN tier surface) by ensuring grant:org's WRITES don't over-grant genome/identity
power. Reading the substrate, the dangerous gate ALREADY EXISTS — amend_charter refuses a
cross-agent edit unless the caller is governance, and set_persona is self-only by construction.
So this oracle does not BUILD that gate; it LOCKS it, because the invariant was untested and a
refactor could silently drop it — and it locks BOTH directions:

  SECURITY (must stay gated): a non-governance caller CANNOT amend another agent's charter.
  USABILITY (must stay open): the reads + benign attributed writes a grant:org holder needs
    (goals, economy, propose_goal, announce) are NOT governance-gated — over-gating them would
    re-break the exact abstractor read-access this work exists to enable.

DB-free: the refusal path returns before any write, and the allowed paths are probed with a
NONEXISTENT agent so they stop at "no charter resolves" — proving they PASSED the gate without
mutating a real charter. The mutation-control arm proves the gate keys on GOVERNANCE membership
(has teeth), not on something incidental. Pure stdlib; run by check.sh.
"""
import importlib.util
import inspect
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRV = REPO / "mcp" / "org" / "server.py"


def skip(m):
    print(f"SKIP: {m}")
    sys.exit(77)


sys.path.insert(0, str(REPO / "mcp" / "org"))
try:
    spec = importlib.util.spec_from_file_location("orgsrv", SRV)
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
except Exception as e:                                              # noqa: BLE001
    skip(f"{type(e).__name__}: {e} — org server not importable")

fails: list[str] = []


def want(label, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        fails.append(label)


def as_agent(name):
    os.environ["ASTRYX_AGENT"] = name


PROBE = "__nonexistent_probe_agent__"     # resolves to no charter → allowed paths stop before any write
NONGOV = "abstractor-1"                    # a real grant:org holder that is NOT governance

# ── SECURITY: the genome gate holds ───────────────────────────────────────────────────
as_agent(NONGOV)
r = S.amend_charter("seed", "PROBE — must be refused")
want("non-governance caller CANNOT amend another agent's charter (cross-agent = governance-only)",
     r.startswith("refused:"))

# self-edit stays open: agent == me passes the gate (stops at no-charter, never 'refused')
as_agent(PROBE)
r_self = S.amend_charter(PROBE, "PROBE self-edit")
want("self-edit passes the gate (a caller may always amend its OWN charter)",
     not r_self.startswith("refused:"))

# governance may cross-agent: passes the gate (stops at no-charter, never 'refused')
as_agent("seed")
r_gov = S.amend_charter(PROBE, "PROBE governance cross-agent")
want("a governance caller passes the cross-agent gate", not r_gov.startswith("refused:"))

# ── MUTATION CONTROL: the gate keys on GOVERNANCE membership (teeth) ───────────────────
# If the caller were governance, the same cross-agent call must NO LONGER refuse. Proves the
# refusal above is caused by the GOVERNANCE check, not by something incidental — so deleting
# that check would flip the security arm RED.
_orig = set(S.GOVERNANCE)
try:
    S.GOVERNANCE.add(NONGOV)
    as_agent(NONGOV)
    r_mut = S.amend_charter(PROBE, "PROBE — now governance")
    want("MUTATION: adding the caller to GOVERNANCE lifts the refusal (gate keys on membership)",
         not r_mut.startswith("refused:"))
finally:
    S.GOVERNANCE.clear()
    S.GOVERNANCE.update(_orig)

# ── set_persona is self-only BY CONSTRUCTION (no 'agent' param to target another) ─────
want("set_persona is self-only (no 'agent' parameter — cannot touch another agent)",
     "agent" not in inspect.signature(S.set_persona).parameters)

# ── USABILITY: the reads + benign writes a grant:org holder needs stay OPEN ────────────
# Over-gating these would re-break the abstractor read-access this work enables. Assert per
# FUNCTION SOURCE that they carry no GOVERNANCE gate (checking each function body, not the
# module — GOVERNANCE is legitimately defined + used by amend_charter elsewhere in the file).
for tool in ("goals", "economy", "propose_goal", "announce"):
    src = inspect.getsource(getattr(S, tool))
    want(f"{tool} stays OPEN to any grant:org holder (no GOVERNANCE gate)", "GOVERNANCE" not in src)
# and the security tool DOES carry it (so the check above is meaningful, not vacuous)
want("amend_charter DOES carry the GOVERNANCE gate (the usability check isn't vacuous)",
     "GOVERNANCE" in inspect.getsource(S.amend_charter))

print()
if fails:
    print(f"test_org_write_gate: {len(fails)} FAIL — {fails}")
    sys.exit(1)
print("test_org_write_gate: ALL PASS — genome/identity writes gated, reads + benign writes open")
sys.exit(0)
