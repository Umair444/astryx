"""Authored mutants for channel/server.mjs's plugin seams (plan-10224 S7), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_channel_home.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "channel/server.mjs"
ORACLE = REPO / "tests" / "test_channel_home.py"
ENV = "CHANNEL_SERVER_SRC"
TIMEOUT = 400

MUTANTS = {
    "the one-body lock is never taken again after its connection drops (abstractor-2 R1)":
        ("  c.on('error', rearm)\n  c.on('end', rearm)\n",
         "  c.once('error', () => {})\n"),
    # SURVIVES (10-14, measured): node-pg emits 'error' (57P01, or "Connection terminated unexpectedly") on every
    # unexpected close this oracle can produce, so the 'end' listener is a belt no reachable fault exercises alone.
    "the re-arm listens to 'error' only (a bare 'end' never re-arms)":
        ("  c.on('end', rearm)\n",
         ""),
    "the re-arm retakes nothing":
        ("    setTimeout(() => holdBody(false), 3000)\n  }\n  c.on('error', rearm)",
         "  }\n  c.on('error', rearm)"),
    "repo mode renders the plugin's channel tag (abstractor-2 N1)":
        ("const SOURCE = JOIN.mode === 'joined' ? 'plugin:astryx:astryx' : 'astryx'",
         "const SOURCE = 'plugin:astryx:astryx'"),
    "joined mode renders the repo's tag":
        ("const SOURCE = JOIN.mode === 'joined' ? 'plugin:astryx:astryx' : 'astryx'",
         "const SOURCE = 'astryx'"),
    "residents go dormant: the plugin gate ignores the repo mode":
        ("if (JOIN.mode === 'dormant') {", "if (JOIN.mode !== 'joined') {"),
    "the second body is let through":
        ("  if (!ok) {\n    console.error(`[channel] ANOTHER BODY", "  if (false) {\n    console.error(`[channel] ANOTHER BODY"),
    "ASTRYX_ONE_BODY is ignored":
        ("if (ONE_BODY) await holdBody(true)", ""),
}
