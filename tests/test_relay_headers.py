"""plan-11859 U0 (D3 + D4): every relay applies ONE allowlist header policy (src/astryx/security/relay.py), and the
observatory units pin the proxy trust their client and scheme rest on.

Arms:
- the POLICY: an unnamed header is dropped (a future credential fails safe); cookies pass only by the destination's
  name; the caller's x-forwarded-* and X-Forwarded-For never pass (X1, X2); the relay's observed view is set; the
  pre-login exception (x-obs-key, authorization, x-api-key; a3 BC-2) still passes, stated as such;
- the REAL front (observatory/front.py, in process, over httpx's ASGI transport) relaying to a recording stub backend
  on a real loopback port, with a two-org fixture registry: the backend receives exactly the allowed set;
- a CENSUS: no code under observatory/, bridges/ or src/ copies a request's headers except through relay.headers();
- D4: init.sh's three observatory units pin `--proxy-headers --forwarded-allow-ips 127.0.0.1`, never a library default.

    ASTRYX_COG_REGISTRY=/nonexistent/cog.json venv/bin/python tests/test_relay_headers.py
    (RELAY_SRC / FRONT_SRC: mutation_probe's channels)
"""
import ast
import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
RELAY_SRC = Path(os.environ.get("RELAY_SRC") or REPO / "src" / "astryx" / "security" / "relay.py")
FRONT_SRC = Path(os.environ.get("FRONT_SRC") or REPO / "observatory" / "front.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


CALLER = [("Accept", "application/json"), ("x-evil", "1"), ("x-astryx-identity", "forged"),
          ("X-Forwarded-For", "9.9.9.9"), ("x-forwarded-host", "evil.example"), ("x-forwarded-proto", "gopher"),
          ("x-forwarded-prefix", "/o/other"), ("x-astryx-front-client", "6.6.6.6"),
          ("cookie", "cv_session-fxa=A; cv_session-fxb=B; astryx_org=fxa; tracker=1"),
          ("x-obs-key", "k"), ("x-astryx", "1"), ("Content-Type", "application/json")]


def policy(relay):
    out = relay.headers(CALLER, host="front.example", proto="https", cookies={"cv_session-fxa"},
                        extra=[("x-astryx-front-client", "203.0.113.9")])
    d = {}
    for k, v in out:
        d.setdefault(k.lower(), []).append(v)
    check("policy: an UNNAMED header is dropped (x-evil, a forged x-astryx-identity): an allowlist fails safe",
          "x-evil" not in d and "x-astryx-identity" not in d, str(d))
    check("policy: the caller's X-Forwarded-For never passes (X2: the backend's uvicorn would make it the client)",
          "x-forwarded-for" not in d, str(d))
    check("policy: the caller's x-forwarded-host/-proto/-prefix and client header never pass; the relay's OBSERVED "
          "view is set once (X1)", d.get("x-forwarded-host") == ["front.example"] and d.get("x-forwarded-proto") ==
          ["https"] and "x-forwarded-prefix" not in d and d.get("x-astryx-front-client") == ["203.0.113.9"], str(d))
    check("policy: cookies pass only by the DESTINATION's name (its own canvas session); the front's astryx_org, "
          "another org's session and a stray cookie are stripped", d.get("cookie") == ["cv_session-fxa=A"], str(d))
    none = dict(relay.headers([("cookie", "astryx_org=fxa")], host="h", proto="http"))
    check("policy: a Cookie header with no allowed pair is dropped whole, never sent empty", "cookie" not in none,
          str(none))
    check("policy: the KNOWN PRE-LOGIN EXCEPTION still passes (x-obs-key; a3 BC-2: it retires in U1+U2)",
          d.get("x-obs-key") == ["k"], str(d))
    check("policy: the app's named headers pass (canvas's CSRF x-astryx, content-type, accept), case-insensitively",
          d.get("x-astryx") == ["1"] and d.get("content-type") == ["application/json"] and d.get("accept"), str(d))
    check("policy: canvas_cookie() is per org in a cog and plain on one org (the name canvas.py sets)",
          relay.canvas_cookie("fxa") == "cv_session-fxa" and relay.canvas_cookie(None) == "cv_session")


class Rec(BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        Rec.seen.append([(k.lower(), v) for k, v in self.headers.items()])
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def through_front(t: Path):
    srv, other = ThreadingHTTPServer(("127.0.0.1", 0), Rec), ThreadingHTTPServer(("127.0.0.1", 0), Rec)
    for s in (srv, other):                       # a port per org: the registry refuses two orgs sharing one
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        reg = {"orgs": {}}
        for o in ("fxa", "fxb"):
            h = t / f"home-{o}"
            h.mkdir()
            (h / ".env").write_text(f"ASTRYX_ORG={o}.example\n")
            port = (srv if o == "fxa" else other).server_port
            reg["orgs"][o] = {"home": str(h), "db": f"fxrelay_{o}", "ports": {"astryx-observatory-org": port}}
        (t / "cog.json").write_text(json.dumps(reg))
        os.environ["ASTRYX_COG_REGISTRY"] = str(t / "cog.json")
        sys.path.insert(0, str(REPO / "observatory"))
        front = load(FRONT_SRC, "front_under_test")
        import httpx

        async def go():
            tr = httpx.ASGITransport(app=front.app, client=("203.0.113.9", 4242))
            async with httpx.AsyncClient(transport=tr, base_url="https://front.example") as c:
                return await c.get("/o/fxa/api/x", headers=CALLER)
        r = asyncio.run(go())
        got = {}
        for k, v in (Rec.seen[-1] if Rec.seen else []):
            got.setdefault(k, []).append(v)
        check("front: the relay reached the org's backend (anti-vacuity: the stub recorded a request)",
              r.status_code == 200 and Rec.seen, f"{r.status_code} {r.text[:120]}")
        check("front: the backend got ONLY the org's own canvas cookie", got.get("cookie") == ["cv_session-fxa=A"],
              str(got.get("cookie")))
        check("front: no caller X-Forwarded-For, x-evil or forged identity reached the backend",
              not ({"x-forwarded-for", "x-evil", "x-astryx-identity"} & set(got)), str(sorted(got)))
        check("front: the forwarded view is what the FRONT saw (its Host, its scheme, its client, its prefix), "
              "never the caller's", got.get("x-forwarded-host") == ["front.example"]
              and got.get("x-forwarded-proto") == ["https"] and got.get("x-astryx-front-client") == ["203.0.113.9"]
              and got.get("x-forwarded-prefix") == ["/o/fxa"], str({k: got.get(k) for k in (
                  "x-forwarded-host", "x-forwarded-proto", "x-astryx-front-client", "x-forwarded-prefix")}))
        check("front: the pre-login exception reaches the backend (x-obs-key; the owner's UI sends it, a3 BC-2)",
              got.get("x-obs-key") == ["k"], str(got.get("x-obs-key")))
    finally:
        srv.shutdown()
        other.shutdown()


def census():
    """Every `<x>.headers.items()` under observatory/, bridges/ and src/ that isn't relay.headers()'s first argument."""
    found = []
    for root in ("observatory", "bridges", "src"):
        for p in sorted((REPO / root).rglob("*.py")):
            if "node_modules" in p.parts or p.name.startswith("test_"):
                continue
            try:
                with warnings.catch_warnings():          # another file's invalid escapes are its own business here
                    warnings.simplefilter("ignore")
                    tree = ast.parse(p.read_text(errors="ignore"))
            except SyntaxError:
                found.append((str(p.relative_to(REPO)), 0, "unparseable"))
                continue
            ok = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "headers" \
                        and isinstance(n.func.value, ast.Name) and n.func.value.id in ("relay", "_relay") and n.args:
                    ok.add(id(n.args[0]))
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "items" \
                        and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "headers" \
                        and isinstance(n.func.value.value, ast.Name) and n.func.value.value.id in ("request", "ws") \
                        and id(n) not in ok:
                    found.append((str(p.relative_to(REPO)), n.lineno, ast.unparse(n)))
    return found


def main():
    relay = load(RELAY_SRC, "relay_under_test")
    sys.modules["astryx.security.relay"] = relay          # the front's `from astryx.security import relay` sees it
    import astryx.security
    astryx.security.relay = relay
    policy(relay)
    t = Path(tempfile.mkdtemp(prefix="relay-hdr-"))
    try:
        through_front(t)
    finally:
        shutil.rmtree(t, ignore_errors=True)
    bad = census()
    check("census: no code copies a request's headers except through relay.headers() (one policy, every relay)",
          not bad, "; ".join(f"{p}:{n} {s}" for p, n, s in bad))
    pin = "--proxy-headers --forwarded-allow-ips 127.0.0.1"
    lines = [ln for ln in (REPO / "init.sh").read_text().split("\n")
             if ln.startswith("ExecStart=") and ("uvicorn front:app" in ln or "uvicorn main:app" in ln)]
    check(f"D4: each of init.sh's {len(lines)} observatory units pins `{pin}` (never uvicorn's default)",
          len(lines) == 3 and all(ln.endswith(pin) for ln in lines), "\n".join(lines))
    print(f"\n{'FAIL' if fails else 'PASS'}: relay headers ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
