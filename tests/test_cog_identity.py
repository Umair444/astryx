#!/usr/bin/env python3
"""plan-11859 U1+U2, the pieces with no database (D1, D2's verify, D7's password, N1, the owner census).

The verifier side is checked against tokens THIS oracle builds byte by byte (its own json, base64 and an Ed25519 call
from `cryptography`, a library the product never imports; it uses PyNaCl), never against identity.mint, so a mint/verify pair that agree on a wrong format can't pass (a verifier must not share
code with its emitter). Mint is then checked the other way: its output decodes, by this oracle's own reader, to the
claims D1 names.

  I1 verify ACCEPTS this oracle's token (signed by a key in keys/<kid>.pub, aud = the org, inside its window)
  I2 verify REFUSES, each alone: another aud; expired; exp - iat > 60; an iat beyond the skew; a signature by a key
     not in keys/; a kid no file names; a key file renamed away from its kid; a payload edited after signing; a sub
     with no cog id; a non-integer iat
  I3 mint's token, read by this oracle: {sub, aud, iat, exp = iat + 60, kid = sha256(raw pub)[:16]}, and its
     signature verifies under the public key (no role, no nonce: a2 I1, I5)
  I4 orgs.cog: no registry → None; a registry without `cog` → None; a good block → {id, home}; a bad id, a relative
     home, or the home of an org → RegistryError (fails closed, as the rest of the file)
  I5 cogauth passwords: an argon2id PHC string (m, t, p as declared), the right password checks, a wrong one and a
     mangled string don't; two hashes of one password differ (salted)
  I6 relay.response_headers (a3 N1, a4 #62231): of a backend's Set-Cookies, the front's session, another org's canvas
     session, its own canvas cookie at Path=/ and at a sibling path /o/<org>x are dropped; its own at /o/<org>/canvas
     passes; hop-by-hop dropped, everything else passes in order; one org: the plain canvas name passes at any path
  I7 the owner census (main.py, comments and strings in docstrings stripped by the AST): the owner key is compared in
     the declared functions only (owner_call, is_owner, events' ?key=, the brain's and noVNC's own keys), so every
     handler's owner check goes through ONE predicate that also honours a signed-in owner
Seams: IDENTITY_SRC (a mutant identity.py), RELAY_SRC (a mutant relay.py), OBS_MAIN_SRC (a mutant main.py). Exit 0 · 1 ·
77 (no cryptography).
"""
import ast
import base64
import hashlib
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def load(modname, path_env, default):
    """The module under test, or a mutant of it executed in its place."""
    src = os.environ.get(path_env)
    if not src:
        return __import__(modname, fromlist=["_"])
    m = types.ModuleType(modname)
    m.__file__ = str(default)
    sys.modules[modname] = m
    exec(compile(Path(src).read_text(), str(default), "exec"), m.__dict__)
    return m


try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
except ImportError:
    print("SKIP: no cryptography (NOT SEARCHED)")
    sys.exit(77)

identity = load("astryx.security.identity", "IDENTITY_SRC", REPO / "src/astryx/security/identity.py")
relay = load("astryx.security.relay", "RELAY_SRC", REPO / "src/astryx/security/relay.py")
from astryx import cogauth, orgs  # noqa: E402


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def raw_pub(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def kid(key):
    return hashlib.sha256(raw_pub(key)).hexdigest()[:16]


def put_pub(home, key, name=None):
    """keys/<kid>.pub as the spec says: the raw public key in hex (written here, never by identity.make_keys)."""
    (home / "keys").mkdir(exist_ok=True)
    (home / "keys" / f"{name or kid(key)}.pub").write_text(raw_pub(key).hex() + "\n")


def token(key, **over):
    """THIS oracle's token: its own json and base64, signed by `key` (or `over['signer']`)."""
    now = int(time.time())
    p = {"sub": "7@fxcog-00000001", "aud": "fxorga", "iat": now, "exp": now + 60, "kid": kid(key)}
    signer = over.pop("signer", key)
    edit = over.pop("edit_after", None)
    p.update(over)
    body = json.dumps(p, separators=(",", ":")).encode()
    sig = signer.sign(body)
    if edit:
        body = json.dumps({**p, **edit}, separators=(",", ":")).encode()
    return f"{b64(body)}.{b64(sig)}"


def main():
    t = Path(tempfile.mkdtemp(prefix="astryx-cogid-")).resolve()
    try:
        run(t)
    finally:
        import shutil
        shutil.rmtree(t, True)
    print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: the cog's signed identity, its passwords, its "
          "response-cookie rule and the one owner predicate")
    return 1 if fails else 0


def run(t):
    home = t / "cog"
    home.mkdir()
    k, stranger, renamed = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    put_pub(home, k)
    put_pub(home, renamed, name="0" * 16)                   # a file whose name is not its key's kid
    v = identity.load_verifiers(home)

    print("I1 THE ORACLE'S TOKEN IS ACCEPTED")
    check("a token signed by a key in keys/, aud = the org, inside its window: its sub",
          identity.verify(token(k), v, "fxorga") == "7@fxcog-00000001")

    print("\nI2 EACH FLAW ALONE IS REFUSED")
    now = int(time.time())
    bad = {
        "another org's aud": token(k, aud="fxorgb"),
        "expired": token(k, iat=now - 120, exp=now - 60),
        "a window longer than 60 s": token(k, iat=now, exp=now + 61),
        "an iat beyond the skew": token(k, iat=now + 30, exp=now + 90),
        "signed by a key not in keys/": token(k, signer=stranger),
        "a kid no key file names": token(stranger, kid=kid(stranger)),
        "a key file renamed away from its kid": token(renamed, kid="0" * 16),
        "a payload edited after signing (aud swapped in)": token(k, aud="fxorgb", edit_after={"aud": "fxorga"}),
        "a sub with no cog id": token(k, sub="7"),
        "a non-integer iat": token(k, iat=float(now)),
        "not a token": "nonsense",
    }
    for name, tok in bad.items():
        check(f"refused: {name}", identity.verify(tok, v, "fxorga") is None)

    print("\nI3 MINT, READ BY THIS ORACLE")
    priv = Ed25519PrivateKey.generate()          # this oracle's library; the product's key is made from its seed
    seed = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                              serialization.NoEncryption())
    sh = t / "signer"
    sh.mkdir()
    (sh / "identity.key").write_text(seed.hex() + "\n")
    tok = identity.mint(identity.load_signer(sh), "9@fxcog-00000001", "fxorga")
    b, s = tok.split(".")
    p = json.loads(unb64(b))
    try:
        priv.public_key().verify(unb64(s), unb64(b))
        sig_ok = True
    except Exception:  # noqa: BLE001
        sig_ok = False
    check("its claims are exactly {sub, aud, iat, exp, kid}: no role, no nonce (a2 I1, I5)",
          set(p) == {"sub", "aud", "iat", "exp", "kid"}, str(sorted(p)))
    check("sub and aud as asked; exp = iat + 60; kid = sha256(raw pub)[:16]",
          p.get("sub") == "9@fxcog-00000001" and p.get("aud") == "fxorga" and p.get("exp") == p.get("iat", 0) + 60
          and p.get("kid") == kid(priv), str(p))
    check("its signature verifies under the public key, over the payload bytes", sig_ok)

    print("\nI4 THE REGISTRY'S COG BLOCK")
    ha, hb = t / "orga", t / "orgb"
    ha.mkdir()
    hb.mkdir()
    o = {"fxorga": {"home": str(ha), "db": "fxid_a"}, "fxorgb": {"home": str(hb), "db": "fxid_b"}}

    def reg(extra):
        f = t / f"cog-{len(list(t.glob('cog-*.json')))}.json"
        f.write_text(json.dumps({"orgs": o, **extra}))
        return {orgs.ENV: str(f)}

    def raises(env):
        try:
            orgs.cog(env)
            return False
        except orgs.RegistryError:
            return True
    check("no registry: None (one org, no sign-in)", orgs.cog({orgs.ENV: str(t / "absent.json")}) is None)
    check("a registry without a cog block: None", orgs.cog(reg({})) is None)
    got = orgs.cog(reg({"cog": {"id": "fxcog-00000001", "home": str(home)}}))
    check("a good block: {id, home}", got == {"id": "fxcog-00000001", "home": home}, str(got))
    check("a short id raises", raises(reg({"cog": {"id": "fx", "home": str(home)}})))
    check("a relative home raises", raises(reg({"cog": {"id": "fxcog-00000001", "home": "cog"}})))
    check("an org's HOME as the cog's raises", raises(reg({"cog": {"id": "fxcog-00000001", "home": str(ha)}})))
    check("a block that isn't an object raises", raises(reg({"cog": "fxcog-00000001"})))

    print("\nI5 PASSWORDS")
    pw = "fx-dummy-pass-0005"
    ph = cogauth.hash_password(pw)
    parts = ph.split("$")
    check("an argon2id PHC string with the declared m, t, p",
          parts[1:4] == ["argon2id", "v=19", f"m={cogauth.M},t={cogauth.T},p={cogauth.P}"], "the string's head differs")
    check("the right password checks", cogauth.check_password(pw, ph))
    check("a wrong one does not", not cogauth.check_password(pw + "x", ph))
    check("a mangled string does not (and does not raise)", not cogauth.check_password(pw, ph.replace("argon2id", "argon2i"))
          and not cogauth.check_password(pw, "garbage"))
    check("two hashes of one password differ (salted)", cogauth.hash_password(pw) != ph)

    print("\nI6 A BACKEND'S SET-COOKIE (a3 N1)")
    raw = [(b"content-type", b"application/json"),
           (b"set-cookie", b"astryx_session=fx-evil; Path=/; HttpOnly"),
           (b"set-cookie", b"cv_session-fxorgb=fx-other; Path=/o/fxorgb/canvas"),
           (b"set-cookie", b"cv_session-fxorga=fx-root; Path=/"),
           (b"set-cookie", b"cv_session-fxorga=fx-sibling; Path=/o/fxorgax/canvas"),
           (b"set-cookie", b"cv_session-fxorga=fx-own; Path=/o/fxorga/canvas; HttpOnly"),
           (b"connection", b"keep-alive"), (b"x-kept", b"1")]
    rh = getattr(relay, "response_headers", lambda raw, org: list(raw))    # absent: every header passes (the old relay)
    got = rh(raw, "fxorga")
    cookies = [v for k, v in got if k.lower() == b"set-cookie"]
    check("only its own canvas cookie, at its own path, passes",
          cookies == [b"cv_session-fxorga=fx-own; Path=/o/fxorga/canvas; HttpOnly"], str(cookies))
    check("hop-by-hop dropped; the rest pass in order",
          [k for k, _ in got if k != b"set-cookie"] == [b"content-type", b"x-kept"], str([k for k, _ in got]))
    one = rh([("set-cookie", "cv_session=fx-one; Path=/canvas"),
                                  ("set-cookie", "astryx_session=fx-evil; Path=/")], None)
    check("one org: the plain canvas name passes, the front's session never", one == [("set-cookie",
                                                                                        "cv_session=fx-one; Path=/canvas")],
          str(one))

    print("\nI7 ONE OWNER PREDICATE (main.py)")
    src = Path(os.environ.get("OBS_MAIN_SRC") or REPO / "observatory/api/main.py").read_text()
    tree = ast.parse(src)
    allowed = {"owner_call", "is_owner", "events", "_brain_gate", "hands_vnc"}
    where = []

    def walk(node, fn):
        for ch in ast.iter_child_nodes(node):
            name = ch.name if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            if isinstance(ch, ast.Compare) and any(isinstance(x, ast.Name) and x.id == "OBS_KEY"
                                                   for x in [ch.left, *ch.comparators]):
                where.append((name, ch.lineno))
            if isinstance(ch, ast.Call) and any(isinstance(a, ast.Name) and a.id == "OBS_KEY" for a in ch.args):
                where.append((name, ch.lineno))
            walk(ch, name)
    walk(tree, "<module>")
    stray = sorted({w for w in where if w[0] not in allowed})
    check("the owner key is compared only in the declared functions", not stray and where, f"elsewhere: {stray}")
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    body = ast.unparse(fns["owner_call"]) if "owner_call" in fns else ""
    check("owner_call honours the signed-in owner as well as the key", "_signed_owner(request)" in body and "x-obs-key"
          in body, body[-200:])
    gate = ast.unparse(fns.get("privacy_gate", ast.Pass()))
    check("the gate reads the viewer's identity before it judges (privacy_gate calls _who first)",
          gate.find("_who(request)") != -1 and gate.find("_who(request)") < gate.find("is_owner(request)"), gate[:300])
    return 0


if __name__ == "__main__":
    os.environ.setdefault(orgs.ENV, "/nonexistent/cog.json")
    sys.exit(main())
