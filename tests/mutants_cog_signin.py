"""Authored mutants for observatory/front.py's sign-in (plan-11859 U1+U2: D1, D3, D7, a3 N1): each is a front that
signs in where it shouldn't, says more than the outcome, or carries an identity the viewer didn't earn. Every one must
be CAUGHT by tests/test_cog_signin.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_cog_signin.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "observatory" / "front.py"
ORACLE = REPO / "tests" / "test_cog_signin.py"
ENV = "OBS_FRONT_SRC"

MUTANTS = {
    "F1 sign-in from any Origin (D7's configured-origin check dropped)":
        ("    o = _origin(request, a)\n    if o is None:\n        return _nope(403,",
         "    o = _origin(request, a) or 'http://fx-any.invalid'\n    if o is None:\n        return _nope(403,"),
    "F2 no rate limit":
        ("    if _limited(ck, ak):", "    if False:"),
    "F3 failures counted per client only (an account is guessed from many addresses)":
        ("    _fails[ak].append(now)\n    _inflight += 1\n", "    _inflight += 1\n"),
    "F4 the session cookie is never Secure":
        ('secure=o.startswith("https://")', "secure=False"),
    "F5 the session cookie is SameSite=Lax":
        ('samesite="strict", secure=o', 'samesite="lax", secure=o'),
    "F6 the session cookie is readable by script":
        ('path="/", httponly=True,\n                 samesite="strict", secure=o', 'path="/", httponly=False,\n                 samesite="strict", secure=o'),
    "F7 a state-changing request from a foreign Origin still carries the identity":
        ('and _origin(request, a) is None:\n        return None', 'and False:\n        return None'),
    "F8 the response filter is not called (a4 #62231: a backend's Set-Cookie fixes the front's session)":
        ("    out.raw_headers = relay.response_headers(resp.headers.raw, org)",
         "    out.raw_headers = [(k, v) for k, v in resp.headers.raw if k.decode().lower() not in relay.HOP]"),
    "F9 the identity is minted for another org than the one routed to":
        ("identity.mint(a.key, who, org))] if who else []", "identity.mint(a.key, who, org + 'x'))] if who else []"),
    "F10 /auth/me holds the role itself (every room, as owner): a2 I1's authority moved to the front":
        ('return {"org": r["org"], "name": r["name"], "role": got} if got in cogauth.ROLES else None',
         'return {"org": r["org"], "name": r["name"], "role": "owner"}'),
    "F11 the cog stream asks the session once, not at every connect (a signed-out stream keeps its identity)":
        ("                who = await viewer(request, a)    # asked again at EVERY connect",
         "                who = getattr(request.state, 'fx_who', None) or await viewer(request, a); request.state.fx_who = who  #"),
    "F12 sign-out clears the cookie and keeps the session row live":
        ("            await a.db(cogauth.sign_out, tok)", "            pass"),
    "F13 the identity rides with no session (a caller's own x-astryx-identity is relayed)":
        ("    signed = [(identity.HEADER, identity.mint(a.key, who, org))] if who else []",
         "    signed = [(identity.HEADER, identity.mint(a.key, who, org))] if who else [(identity.HEADER, request.headers.get(identity.HEADER, ''))]"),
    "F14 a same-site page's request is signed in (a2 #62390 R-1: SameSite=Strict is a site rule; a writing GET runs)":
        ('    if request.headers.get("sec-fetch-site") not in ("same-origin", "none"):\n        return None\n', ""),
    "F15 a typed URL or a bookmark (Sec-Fetch-Site none) is not signed in (the owner's own navigation refused)":
        ('not in ("same-origin", "none"):', 'not in ("same-origin",):'),
}
