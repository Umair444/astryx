"""Authored mutants for bridges/canvas.py's per-org session (plan-11324 S3c canvas, a2 #60582 A-2), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_canvas_cog.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "bridges/canvas.py"
ORACLE = REPO / "tests" / "test_canvas_cog.py"
ENV = "CANVAS_SRC"
TIMEOUT = 360

MUTANTS = {
    "N1 the cookie's path ignores the org (every org's session at /canvas: the browser sends A's to B)":
        ('PUBLIC = f"/o/{_ORG}{PREFIX}" if _ORG else PREFIX\n', 'PUBLIC = PREFIX\n'),
    "N2 the cookie's name ignores the org (one host-wide name: logging in to B replaces A's session)":
        ('COOKIE = relay.canvas_cookie(_ORG)', 'COOKIE = "cv_session"'),
    "N3 one org gets the cog's path too (/o/None/canvas: a one-org browser never sends its session)":
        ('PUBLIC = f"/o/{_ORG}{PREFIX}" if _ORG else PREFIX\n', 'PUBLIC = f"/o/{_ORG}{PREFIX}"\n'),
    "N4 one org gets the cog's name too (every one-org owner logged out)":
        ('COOKIE = relay.canvas_cookie(_ORG)', 'COOKIE = f"cv_session-{_ORG}"'),
    "N5 the cookie is SET at the routing prefix, not the public path":
        ('secure=public_base(request).startswith("https:"), path=PUBLIC)', 'secure=public_base(request).startswith("https:"), path=PREFIX)'),
    "N6 logout clears the routing prefix's cookie (the cog's session survives a logout)":
        ('    resp.delete_cookie(COOKIE, path=PUBLIC)\n', '    resp.delete_cookie(COOKIE, path=PREFIX)\n'),
    "N7 the invite link and kit URL use the routing prefix (a link that lands at the root)":
        ("{host.split(',')[0].strip()}{PUBLIC}\"", "{host.split(',')[0].strip()}{PREFIX}\""),
    "N8 the prefix is read from the request (a caller's x-forwarded-prefix moves the link)":
        ("{host.split(',')[0].strip()}{PUBLIC}\"", "{host.split(',')[0].strip()}{request.headers.get('x-forwarded-prefix', '')}{PREFIX}\""),
    "N9 the bare /canvas bounces to the routing prefix (a cog's viewer lands at the root)":
        ('"headers": [(b"location", (PUBLIC + "/").encode())]})', '"headers": [(b"location", (PREFIX + "/").encode())]})'),
}
