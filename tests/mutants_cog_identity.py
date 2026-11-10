"""Authored mutants for src/astryx/security/identity.py (plan-11859 U1+U2, D1): each is a verifier that accepts a token
the front never issued for THIS org, or a minter that says more than WHO. Every one must be CAUGHT by
tests/test_cog_identity.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_cog_identity.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "security" / "identity.py"
ORACLE = REPO / "tests" / "test_cog_identity.py"
ENV = "IDENTITY_SRC"

MUTANTS = {
    "D1 any org's token opens this one (the aud check dropped)":
        ('        if p["aud"] != aud or not', '        if not'),
    "D2 an expired token is accepted (only the skew is checked)":
        ("(iat - SKEW <= now < exp)", "(iat - SKEW <= now)"),
    "D3 a token from the future is accepted (no skew bound)":
        ("(iat - SKEW <= now < exp)", "(now < exp)"),
    "D4 a window longer than 60 s is accepted (D1's cap dropped)":
        (" or exp - iat > TTL:", ":"),
    "D5 a key file renamed away from its kid is trusted under the new name":
        ("        if kid_of(pub) == p.stem:", "        if True:"),
    "D6 a sub with no cog id is accepted (a2 I6: never qualified)":
        (' and "@" in sub)', ")"),
    "D7 the minter carries a role (a2 I1: role is the org's fact, never the token's)":
        ('"kid": kid_of(key.verify_key)}', '"kid": kid_of(key.verify_key), "role": "owner"}'),
    "D8 the minter's window is an hour":
        ('"exp": now + TTL', '"exp": now + 3600'),
}
