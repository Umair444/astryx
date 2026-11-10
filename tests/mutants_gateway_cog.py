"""Authored mutants for bridges/gateway.py (plan-11324 S3c: the gateway is cog-scoped, routes by to_org), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_gateway_cog.py

Each is the cog's door serving the wrong org, widening a sibling, or losing a sibling's row.
The oracle runs the gateway from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "bridges/gateway.py"
ORACLE = REPO / "tests" / "test_gateway_cog.py"
ENV = "ORG_HOME_GATEWAY_SRC"
TIMEOUT = 300

MUTANTS = {
    "Q1 no loopback: a sibling's row takes the peer path (url NULL: it waits for a pickup that never comes)":
        ("    if sib is not None and sib is not ctx:\n", "    if False:\n"),
    "Q2 siblings are never seeded (B's door has no A: every sibling row dies)":
        ("    if len(ctxs) < 2:\n        return\n", "    if True:\n        return\n"),
    "Q3 seeding overwrites a local grant (an org's own trust decision reset to introduced)":
        ("                       ON CONFLICT (org) DO NOTHING\"\"\", s.name, s.pub)",
         "                       ON CONFLICT (org) DO UPDATE SET status='introduced', caps_granted='[]'\"\"\", s.name, s.pub)"),
    "Q4 the envelope's from is not the sending org's federation name":
        ("        \"from\": f\"{row['from_agent']}@{ctx.name}\",", "        \"from\": f\"{row['from_agent']}@local\","),
    "Q5 a cog org's DSN is read environment-first (the cog process's DSN becomes every org's)":
        ("dsn=config.dsn(f, env_first=False)", "dsn=config.dsn(f)"),
    "Q6 the bare root serves the first org of a cog (a primary by dict order)":
        ("    return next((x for x in c.values() if x.org == _DOOR), None) if _DOOR else None\n",
         "    return next(iter(c.values()))\n"),   # re-anchored on S3e 2/n's door root (memory)
    "Q7 a sibling's 429 kills the row (a rate cap read as a refusal)":
        ("        if r.status_code == 429:\n            return False", "        if False:\n            return False"),
    "Q8 cog() keyed by REGISTRY name (to_org is the federation name: no sibling is ever found)":
        ("                out[c.name] = c\n", "                out[org] = c\n"),
    "Q9 two cog orgs may share a federation name (the second silently replaces the first)":
        ("                if c.name in out:\n", "                if False:\n"),
    "Q10 an org with no ASTRYX_ORG is served under a guessed name":
        ("    if not name or not sk:\n", "    name = name or org\n    if not sk:\n"),
    "Q11 a raise at the sibling's door escapes push (the sender's whole drain stalls on that row, a2 #60413 R-1)":
        ("        except Exception as ex:\n            print(f\"gateway: sibling", "        except ZeroDivisionError as ex:\n            print(f\"gateway: sibling"),
    "Q12 a to_agent past the doorbell's channel name is not refused":
        ("    if len(req_to.encode()) > AGENT_MAX:\n", "    if False:\n"),
}
