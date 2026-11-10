"""The ONE request-header policy every relay in the tree applies (plan-11859 U0, D3; a2 I2, a1 F2, a4 X1/X2).

A relay is a credential boundary. It forwards only what the caller may say to the destination, and sets the headers
that describe what the RELAY observed. The rule, from the consolidation (#61882): a fact travels only in a token its
authority issued, and every hop strips what it didn't mint.

- ALLOWLIST, never a denylist: a header not named here is dropped, so a future credential header fails safe.
- COOKIES are filtered by issuer: only a cookie the DESTINATION itself set passes (canvas's per-org session, whose
  name is canvas_cookie(org) below, the one source canvas.py reads too). The front's own cookies (astryx_org; U1's
  session) and another org's sessions never reach a backend.
- The forwarded view (x-forwarded-host / -proto) is what the relay OBSERVED: the Host it was reached at and the scheme
  its server resolved (uvicorn applies X-Forwarded-Proto only from its pinned trusted peer). The caller's own
  x-forwarded-* are dropped (X1: ear.py's Origin check and canvas's public_base were built on them). So is
  X-Forwarded-For (X2: a backend's uvicorn trusts its 127.0.0.1 peer, the front, so a forwarded caller XFF became the
  backend's client address and outranked the front's own client header).
- THE OWNER KEY STAYS (owner ruling 10-21, seed #61925, narrowing a3 BC-2): x-obs-key, authorization and x-api-key
  still pass. U1+U2 add the sign-in ALONGSIDE the key; it leaves this list only with U7 ("OBS_KEY retire", seed
  #61943), whose arm is that every backend refuses x-obs-key. Until then outsider prevention also rests on the key's
  secrecy (a3 #61941).
- The front's SIGNED IDENTITY (x-astryx-identity, U1+U2) is not on this list, so a caller's copy never passes: the
  front adds its own through `extra`, minted from the session it verified (src/astryx/security/identity.py).

RESPONSES (plan-11859 U1+U2, a3 #62226 N1 via a4 #62231): the mirror of the cookie rule. Once the front mints its own
session cookie, a backend that could set it could fix a viewer's session (session fixation through a compromised or
hosted org). So a backend's Set-Cookie passes ONLY for its own canvas_cookie(org), path-scoped to /o/<org>; every
other one, the front's session included, is dropped. `response_headers` is that rule, and every relay calls it.
"""

# what a caller may send through a relay: standard request semantics, plus the app's own named headers
FORWARD = frozenset({
    "accept", "accept-encoding", "accept-language", "cache-control", "pragma", "content-type", "content-length",
    "if-match", "if-none-match", "if-modified-since", "if-unmodified-since", "if-range", "range", "last-event-id",
    "origin", "referer", "user-agent",
    "x-astryx", "x-kind", "x-filename",            # canvas: its CSRF header (canvas.py:324) and an upload's metadata
    "x-obs-key", "authorization", "x-api-key",     # the owner key stays (owner ruling 10-21): retired in U7
})
# the headers a relay SETS from its own observation (the caller's copies never pass)
SET = ("x-forwarded-host", "x-forwarded-proto")


def canvas_cookie(org: str | None) -> str:
    """The name of an org's canvas session cookie: per org in a cog (its registry name), plain on one org."""
    return f"cv_session-{org}" if org else "cv_session"


def _cookies(value: str, allowed: frozenset) -> str:
    """The Cookie header with only the pairs whose name is in `allowed`, in their order."""
    keep = []
    for part in value.split(";"):
        name = part.split("=", 1)[0].strip()
        if name and name in allowed:
            keep.append(part.strip())
    return "; ".join(keep)


def headers(incoming, *, host: str, proto: str, cookies=(), extra=()) -> list:
    """The headers a relay sends upstream: the ALLOWED caller headers, the cookies the destination issued, then the
    relay's own observed view (`host`, `proto`) and any `extra` it sets (the front's client header and prefix).
    `incoming` is (name, value) pairs; names compare case-insensitively."""
    allowed = frozenset(cookies)
    out = []
    for k, v in incoming:
        lk = k.lower()
        if lk == "cookie":
            v = _cookies(v, allowed)
            if v:
                out.append(("cookie", v))
        elif lk in FORWARD:
            out.append((k, v))
    out += [("x-forwarded-host", host), ("x-forwarded-proto", proto)]
    out += list(extra)
    return out


# a response header no relay passes back (hop-by-hop, RFC 9110 §7.6.1, plus host)
HOP = frozenset({"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization",
                 "proxy-authenticate", "host"})


def _cookie_scope(value: str) -> tuple[str, str | None]:
    """A Set-Cookie value's (name, Path attribute or None)."""
    parts = value.split(";")
    name = parts[0].split("=", 1)[0].strip()
    path = None
    for a in parts[1:]:
        k, _, v = a.partition("=")
        if k.strip().lower() == "path":
            path = v.strip()
    return name, path


def response_headers(raw, org: str | None) -> list:
    """The headers a relay passes back from `org`'s backend: every one but the hop-by-hop, and a Set-Cookie ONLY when
    it names that org's own canvas_cookie(org) with a Path inside /o/<org> (one org: the plain name, any path). `raw`
    is (name, value) pairs, bytes or str, returned in their own type and order."""
    out = []
    mine = canvas_cookie(org)
    base = f"/o/{org}" if org else ""
    for k, v in raw:
        lk = (k.decode("latin-1") if isinstance(k, bytes) else k).lower()
        if lk in HOP:
            continue
        if lk == "set-cookie":
            name, path = _cookie_scope(v.decode("latin-1") if isinstance(v, bytes) else v)
            if name != mine or (base and not (path == base or (path or "").startswith(base + "/"))):
                continue
        out.append((k, v))
    return out
