"""Authored mutants for src/astryx/security/relay.py (plan-11859 U0, D3): each is a relay that lets through what the
destination didn't mint. Every one must be CAUGHT by tests/test_relay_headers.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_relay_headers.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "security" / "relay.py"
ORACLE = REPO / "tests" / "test_relay_headers.py"
ENV = "RELAY_SRC"

MUTANTS = {
    "H1 a denylist after all: every caller header not named Cookie passes (a future credential rides through)":
        ("        elif lk in FORWARD:", "        else:"),
    "H2 cookies pass unfiltered (the front's astryx_org, U1's session and another org's session reach a backend)":
        ("        if name and name in allowed:", "        if name:"),
    "H3 X-Forwarded-For is allowed (X2: the backend's uvicorn makes the caller's value its client address)":
        ('    "origin", "referer", "user-agent",', '    "origin", "referer", "user-agent", "x-forwarded-for",'),
    "H4 an empty Cookie header is sent when no pair is allowed":
        ('            if v:\n                out.append(("cookie", v))', '            out.append(("cookie", v))'),
    "H5 the caller's x-forwarded-* pass beside the relay's own (X1: a backend reads the first copy)":
        ("        elif lk in FORWARD:", "        elif lk in FORWARD or lk.startswith(\"x-forwarded-\"):"),
}
