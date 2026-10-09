#!/usr/bin/env python3
"""Oracle: CANVAS realtime voice (bridges/canvas_voice.py) — the spend cap, the tier fence, the owner gate.

Realtime is an EXTERNAL processor the owner signed for, so three properties must never regress:
  - SPEND: sessions are counted and a day over CANVAS_VOICE_DAILY_MINUTES is refused;
  - TIER: the voice tools reach only content-public agents + the home agent, enforced SERVER-side
    (a tier-private agent is refused with a spoken explanation, whatever the browser sends);
  - OWNER: every voice route is owner-only unless CANVAS_VOICE_GUESTS=1.
OpenAI is never called: the mint is stubbed (a test must not spend money). Fixture DB, API in-process.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nucleus.sqlguard.estate import gate  # noqa: E402
gate('test_canvas_voice', REPO, deps=('psycopg', 'asyncpg', 'fastapi'))   # a committed-only tree: 77, not a crash
from nucleus.sqlguard.fixture import fixture_db  # noqa: E402

fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


class _FakeResp:
    status = 200

    def __init__(self, body):
        self._b = json.dumps(body).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def main(url):
    from fastapi.testclient import TestClient
    from nucleus import tier
    import bridges.canvas as b
    import bridges.canvas_voice as cvv
    minted = []
    cvv.urllib.request.urlopen = lambda req, timeout=20: (minted.append(req.full_url), _FakeResp(
        {"value": "ek_test", "expires_at": 9999999999}))[1]
    H = {"x-astryx": "1"}
    A = "/canvas/api"
    private = next((a for a in ("canopus", "gemini", "memory") if not tier.is_content_public(a)), None)
    public = next((a for a in ("painter", "forge", "scout") if tier.is_content_public(a)), None)
    with TestClient(b.root, base_url="http://testserver") as cl:
        jars = {}

        def who(n):
            cl.cookies.clear()
            for k, v in jars.get(n, {}).items():
                cl.cookies.set(k, v, path="/canvas")
            return cl

        def keep(n):
            jars[n] = {c.name: c.value for c in cl.cookies.jar}

        who("anon").post(f"{A}/login", json={"key": "test-owner-key"}, headers=H); keep("owner")
        t = who("owner").post(f"{A}/users", json={"name": "vguest", "agents": [public or "painter"]}, headers=H).json()
        who("anon").post(f"{A}/login", json={"key": t["token"]}, headers=H); keep("guest")

        g = who("guest")
        arm("voice is owner-only: a guest is refused on every voice ACTION route",
            all(r.status_code == 403 for r in (g.post(f"{A}/voice/session", headers=H),
                                              g.get(f"{A}/voice/agents"), g.get(f"{A}/voice/org"),
                                              g.post(f"{A}/voice/ask", json={"agent": "seed", "message": "hi"}, headers=H))))
        gs = g.get(f"{A}/voice/status").json()
        arm("…and status tells a guest voice is unavailable (so its client falls back to local whisper)",
            gs.get("available") is False and gs.get("reason"), gs)
        o = who("owner")
        bare = o.get(f"{A}/voice/org").json()
        arm("org_status on a quiet org: no busy agents, no canvases", not bare.get("canvases") and not bare.get("busy"), bare)
        st = o.get(f"{A}/voice/status").json()
        arm("status reports availability and today's minutes against the cap", st.get("available") is True and "cap" in st, st)
        s1 = o.post(f"{A}/voice/session", headers=H)
        body = s1.json()
        arm("a session is minted through OpenAI's client_secrets and counted",
            s1.status_code == 200 and body.get("value") == "ek_test" and body.get("usage_id")
            and minted and minted[-1].endswith("/v1/realtime/client_secrets"), body)
        allow = body.get("allow", [])
        arm("the session's tool allowlist excludes tier-private agents",
            (private is None or private not in allow) and (public is None or public in allow), allow)
        r = o.post(f"{A}/voice/usage", json={"id": body.get("usage_id", 0), "seconds": 90}, headers=H).json()
        arm("connected seconds are recorded (monotonic) and summed for today", r.get("minutes_today", 0) >= 1.5, r)
        o.post(f"{A}/voice/usage", json={"id": body.get("usage_id", 0), "seconds": 10}, headers=H)
        o.post(f"{A}/voice/usage", json={"id": 987654321, "seconds": 999}, headers=H)   # not a session of ours: no row
        r2 = o.get(f"{A}/voice/status").json()
        arm("a lower report never lowers the count", r2.get("minutes_today", 0) >= 1.5, r2)
        os.environ["CANVAS_VOICE_DAILY_MINUTES"] = "1"
        capped = o.post(f"{A}/voice/session", headers=H)
        arm("over the daily cap, a new session is REFUSED (429)", capped.status_code == 429, capped.text[:120])
        os.environ["CANVAS_VOICE_DAILY_MINUTES"] = "60"
        if private:
            ref = o.post(f"{A}/voice/ask", json={"agent": private, "message": "hello"}, headers=H)
            arm("the tier fence is server-side: a private agent is refused, with words to speak",
                ref.status_code == 403 and "spoken" in ref.json(), ref.text[:120])
        arm("an unknown agent is a spoken 404",
            o.post(f"{A}/voice/ask", json={"agent": "nobody-here", "message": "x"}, headers=H).status_code == 404)
        if public:
            ok = o.post(f"{A}/voice/ask", json={"agent": public, "message": "status?"}, headers=H).json()
            again = o.post(f"{A}/voice/ask", json={"agent": public, "message": "and now?", "thread": ok.get("thread")}, headers=H).json()
            arm("ask_agent puts a real wire message on one thread per agent", ok.get("thread", "").startswith("cv:")
                and again.get("thread") == ok.get("thread"), (ok, again))
        o.post(f"{A}/canvases", json={"title": "Voice probe"}, headers=H)
        import psycopg
        with psycopg.connect(url) as c:
            c.execute("INSERT INTO steps (agent, kind, content) VALUES (%s, 'tool', 'busy')", (public or "painter",))
            c.commit()
        org = o.get(f"{A}/voice/org").json()
        blob = json.dumps(org)
        arm("org_status carries counts and names, never message bodies", "status?" not in blob and "agents" in blob, blob[:200])
        arm("voice agents lists only the allowlist", set(x["name"] if isinstance(x, dict) else x
                                                         for x in (o.get(f"{A}/voice/agents").json() or [])) <= set(allow + ["seed"]))


if __name__ == "__main__":
    with fixture_db() as fx:
        os.environ["ASTRYX_DSN"] = fx["url"]
        os.environ["OBS_KEY"] = "test-owner-key"
        main(fx["url"])
    print(f"{'PASS' if not fails else 'FAIL'}: canvas voice ({fails} failing)")
    sys.exit(1 if fails else 0)
