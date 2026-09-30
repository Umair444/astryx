"""Authored mutants for bridges/geoloc.py's /recent auth gate (a3 #32078), run by
nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_geoloc_recent_auth.py

The subject is GITIGNORED (the geoloc estate), so on a clean clone these can't apply and read
NOT PROBED, never caught. X3 is the version I wrote first and caught by probing before review.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "bridges" / "geoloc.py"
ORACLE = REPO / "tests" / "test_geoloc_recent_auth.py"
ENV = "GEOLOC_SRC"

MUTANTS = {
    # The original gate: any 127.0.0.1/::1 client reads location history with no token.
    "X1 the localhost bypass restored":
        ('    if not authorized(request, {}):\n        return JSONResponse({"error": "token required"}, status_code=401)',
         '    local = request.client and request.client.host in ("127.0.0.1", "::1")\n'
         '    if not local and not authorized(request, {}):\n'
         '        return JSONResponse({"error": "token required"}, status_code=401)'),
    # A timing-leaky comparison.
    "X2 a plain == comparison":
        ("return isinstance(t, str) and bool(t) and hmac.compare_digest(t.encode(), TOKEN.encode())",
         "return bool(t) and t == TOKEN"),
    # My first hardened version: compare_digest on raw values, which raises (500) on a non-str or
    # non-ASCII token in the ingest body.
    "X3 compare_digest without the str/bytes guard (500 on a malformed token)":
        ("return isinstance(t, str) and bool(t) and hmac.compare_digest(t.encode(), TOKEN.encode())",
         "return bool(t) and hmac.compare_digest(t, TOKEN)"),
}
