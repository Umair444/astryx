#!/usr/bin/env python3
"""Live smoke for CANVAS at the URL a viewer uses — run after any deploy of canvas or the observatory.

    venv/bin/python tests/smoke_canvas_live.py [base ...]    # default: the proxy and the direct port

Each arm is a property the viewer depends on, checked against the RUNNING services (a stub can't
see a proxy that remembers cookies — the bug this file was born from, 2026-10-09: one shared httpx
jar in the observatory proxy replayed the owner's session to every anonymous visitor).
"""
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
KEY = next((l.split("=", 1)[1].strip() for l in (REPO / ".env").read_text().splitlines()
            if l.startswith("OBS_KEY=")), "")
BASES = sys.argv[1:] or ["http://127.0.0.1:8090/canvas", "http://127.0.0.1:8091/canvas"]
fails = 0


def arm(ok: bool, what: str):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {what}")


for base in BASES:
    print(base)
    try:
        anon = httpx.get(f"{base}/api/me", timeout=10)
    except httpx.HTTPError as e:
        arm(False, f"reachable ({e})")
        continue
    arm(anon.status_code == 401, f"anonymous /api/me → 401 (got {anon.status_code})")
    arm(httpx.post(f"{base}/api/login", json={"key": KEY}, timeout=10).status_code == 403,
        "a write without x-astryx is refused (CSRF)")
    arm(httpx.post(f"{base}/api/login", json={"key": "wrong"}, headers={"x-astryx": "1"},
                   timeout=10).status_code == 401, "a wrong key is refused")
    with httpx.Client(timeout=10) as owner:
        r = owner.post(f"{base}/api/login", json={"key": KEY}, headers={"x-astryx": "1"})
        set_cookie = r.headers.get("set-cookie", "")
        arm(r.status_code == 200 and "httponly" in set_cookie.lower() and "samesite=strict" in set_cookie.lower()
            and "path=/canvas" in set_cookie.lower(), "owner login → HttpOnly SameSite=Strict cookie scoped to /canvas")
        arm(owner.get(f"{base}/api/me").json().get("owner") is True, "the owner session is the owner")
        cvs = owner.get(f"{base}/api/canvases").json()
        painted = next((c for c in cvs if c["version"]), None)
        if painted:
            html = owner.get(f"{base}/api/canvases/{painted['id']}/render").json()["html"]
            arm("connect-src &#x27;none&#x27;" in html or "connect-src 'none'" in html,
                f"canvas {painted['id']} renders inside the no-network CSP")
        owner.post(f"{base}/api/logout", headers={"x-astryx": "1"})
    # THE regression: after someone logged in through this base, a stranger is still a stranger
    after = httpx.get(f"{base}/api/me", timeout=10)
    arm(after.status_code == 401, f"anonymous AFTER an owner login → still 401 (got {after.status_code})")
    kit = httpx.get(f"{base}/kit/inter.woff2", timeout=10)
    arm(kit.status_code == 200 and kit.headers.get("access-control-allow-origin") == "*",
        "the kit serves fonts to sandboxed (null-origin) frames")

print(f"{'PASS' if not fails else 'FAIL'}: canvas live smoke ({fails} failing)")
sys.exit(1 if fails else 0)
