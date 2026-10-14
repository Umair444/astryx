"""Authored mutants for channel/server.mjs's tier-labelled seats (plan-9139 S1b-2), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_release_server.py

Each is a way the node half could fail OPEN: a label read that falls back to org, a send that skips the door, a
permission relayed anyway, a reply thread kept that this session never received.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "channel" / "server.mjs"
ORACLE = REPO / "tests" / "test_release_server.py"
ENV = "CHANNEL_SERVER_SRC"

MUTANTS = {
    "R1 an unreadable label falls back to org instead of refusing the start":
        ('  console.error(`[channel] refusing to start "${AGENT}": its tier label could not be read (${e.message})`)\n'
         '  process.exit(1)\n',
         "  LABEL = []\n"),

    "R2 a labelled send skips the door (today's raw INSERT)":
        ("    if (LABELLED) {\n      const inbound", "    if (false) {\n      const inbound"),

    "R3 a labelled member's permission request is relayed":
        ("  if (LABELLED) {\n    await mcp.notification({", "  if (false) {\n    await mcp.notification({"),

    "R4 any thread the member names is passed as the inbound one":
        ("const inbound = a.thread && seenThreads.has(a.thread) ? a.thread : null",
         "const inbound = a.thread ?? null"),
}
