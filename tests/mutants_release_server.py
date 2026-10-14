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
    "R1 a malformed grant falls back to org instead of refusing the start":
        ('  console.error(`[channel] refusing to start "${AGENT}": its tier label could not be read (${e.message})`)\n'
         '  process.exit(1)\n',
         "  LABEL = []\n"),

    "R0 UNKNOWN (no charter, or no door) is treated as org":
        ("const labelled = lbl => lbl === null || lbl.length > 0", "const labelled = lbl => lbl !== null && lbl.length > 0"),

    "R2 a labelled send skips the door (today's raw INSERT)":
        ("    if (labelled(lbl)) {\n      const inbound", "    if (false) {\n      const inbound"),

    "R3 a labelled member's permission request is relayed":
        ("  if (labelled(lbl)) {\n    await mcp.notification({", "  if (false) {\n    await mcp.notification({"),

    "R4 any thread the member names is passed as the inbound one":
        ("const inbound = a.thread && seenThreads.has(a.thread) ? a.thread : null",
         "const inbound = a.thread ?? null"),

    "R5 an UNKNOWN label is never read again (frozen at spawn)":
        ("  if (LABEL !== null) return LABEL\n  LABEL = await readLabel(AGENT)\n", "  return LABEL\n"),
}
