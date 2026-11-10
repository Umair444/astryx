"""Authored mutants for src/astryx/security/relay.py's RESPONSE rule (plan-11859 U1+U2; a3 #62226 N1, a4 #62231): each
lets a backend set a cookie that isn't its own canvas session at its own path. Every one must be CAUGHT by
tests/test_cog_identity.py (I6).

    venv/bin/python devtools/mutation_probe.py tests/mutants_relay_response.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "security" / "relay.py"
ORACLE = REPO / "tests" / "test_cog_identity.py"
ENV = "RELAY_SRC"

MUTANTS = {
    "R1 the response filter dropped: every Set-Cookie passes (a backend fixes the front's session)":
        ('        if lk == "set-cookie":', '        if False:'),
    "R2 the path scope dropped: its own cookie name at Path=/ passes (it rides every org's requests)":
        ('            if name != mine or (base and not (path == base or (path or "").startswith(base + "/"))):',
         '            if name != mine:'),
    "R3 a prefix without its slash: a sibling org's path /o/<org>x passes":
        ('(path or "").startswith(base + "/")', '(path or "").startswith(base)'),
    "R4 hop-by-hop headers pass back":
        ("        if lk in HOP:\n            continue\n", ""),
}
