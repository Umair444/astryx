"""Authored mutants for observatory/front.py (plan-11324 S3c 3/n: the cog's observatory front), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_observatory_cog.py

Each is the front choosing an org for the viewer, leaking what it holds, adding authority, or losing a room.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "observatory/front.py"
ORACLE = REPO / "tests" / "test_observatory_cog.py"
ENV = "OBS_FRONT_SRC"
TIMEOUT = 180

MUTANTS = {
    "F1 /api/cog leaks each backend's loopback port":
        ('"orgs": [{k: r[k] for k in ("org", "name", "base")} for r in rooms()]}', '"orgs": rooms()}'),
    "F2 the root API defaults to the first org (a primary by sort order)":
        ('    if org not in _cog():\n', '    org = org or sorted(_cog())[0]\n    if org not in _cog():\n'),
    "F3 the cookie wins over the x-astryx-org header":
        ('request.headers.get("x-astryx-org") or request.cookies.get("astryx_org")',
         'request.cookies.get("astryx_org") or request.headers.get("x-astryx-org")'),
    "F4 the front's jar stores cookies (one viewer's session replayed to the next)":
        ("policy=http.cookiejar.DefaultCookiePolicy(allowed_domains=[])", "policy=http.cookiejar.DefaultCookiePolicy()"),
    "F5 the front adds an owner key of its own":
        ('                                   ("x-forwarded-prefix", f"/o/{org}"), *signed])',
         '                                   ("x-forwarded-prefix", f"/o/{org}"), *signed, ("x-obs-key", "front")])'),
    "F6 the merged stream drops the org tag":
        ('                            await q.put({**tag, "event": ev})', '                            await q.put(ev)'),
    "F7 a dead backend is never announced":
        ("            if up is not False:\n                up = False", "            if False:\n                up = False"),
    "F8 an org the registry doesn't hold falls through to some backend":
        ("    r = _cog().get(org)\n    if r is None", "    r = _cog().get(org) or next(iter(_cog().values()))\n    if r is None"),
    "F9 the stream's ?key= is not forwarded (owner rooms read as anonymous)":
        ('        params = {"key": key} if key else {}', '        params = {}'),
    "F10 the caller's own x-astryx-front-client passes through (a visitor names itself to the cap)":
        ('extra=[(CLIENT, request.client.host if request.client else ""),',
         'extra=[(CLIENT, request.headers.get(CLIENT) or (request.client.host if request.client else "")),'),
    "F11 the caller's own x-forwarded-prefix passes through (the backend reads the caller's, first, not the front's)":
        ('("x-forwarded-prefix", f"/o/{org}"), *signed])', '("x-forwarded-prefix", request.headers.get("x-forwarded-prefix") or f"/o/{org}"), *signed])'),
}
