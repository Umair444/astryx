#!/usr/bin/env python3
"""Oracle: plan-11884, /chat's server half (observatory/api/chat.py). In-process and hermetic: the estate is a temp
dir (chat.bind), the app is never started (no lifespan, no pool), no OpenAI key is set, so nothing leaves the host.
  - R1 GATE: every /api/chat/* (method, path) the app SERVES, HEAD and OPTIONS included, is 403 without the owner key;
    none is a PUBLIC pair.
  - R2 UPLOAD: a type off the allowlist is 415, an empty body 400, an oversize body 413; a stored file lands under
    media/chat/ with a random 24-hex token and a sanitized name, written whole; the answer names no other path.
  - R3 FILE: a file under media/ or an agent home is served (an allowlisted type as itself, anything else as plain
    text, nosniff); a '..' escape, an absolute path outside, a symlink out of a root, a NUL byte, a dot-path inside a
    home (its .claude/) and an .env are all 404, the same answer as a missing file.
  - R5 PROJECTS: no If-Match is 428, a stale one 409 (file untouched), an invalid project 400, a good write round-trips
    with its new etag.
  - R6 DICTATE: with no OpenAI key the session route refuses (503) and mints nothing; no response carries a key.
  - COMMANDS: the / list is the org's real skills (skills/*/SKILL.md).
CHAT_SRC names another chat.py to judge (devtools/mutation_probe.py: tests/mutants_chat_api.py)."""
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_chat_api", REPO, deps=("fastapi", "httpx", "asyncpg"), env=False)

SUBJECT = Path(os.environ.get("CHAT_SRC") or REPO / "observatory" / "api" / "chat.py")
O = {"x-obs-key": "test-owner-key"}
fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def main(tmp: Path):
    import observatory.api  # noqa: F401 — the package first, so the subject can stand in for its chat module
    spec = importlib.util.spec_from_file_location("observatory.api.chat", SUBJECT)
    chat = importlib.util.module_from_spec(spec)
    sys.modules["observatory.api.chat"] = chat
    spec.loader.exec_module(chat)
    mspec = importlib.util.spec_from_file_location("main", REPO / "observatory" / "api" / "main.py")
    obs = importlib.util.module_from_spec(mspec)
    sys.modules["main"] = obs
    mspec.loader.exec_module(obs)
    from fastapi.testclient import TestClient
    from fastapi.routing import APIRoute

    estate = tmp / "estate"
    media = estate / "media"
    (estate / "homes" / "fixture-agent" / ".claude").mkdir(parents=True)
    media.mkdir(parents=True)
    chat.bind(lambda: None, estate, media, REPO)
    cl = TestClient(obs.app, raise_server_exceptions=False)   # a handler that throws is a 500 the arms judge, not a crash

    # ── R1 the gate ──────────────────────────────────────────────────────────────────────────────────────────
    served = [(m, r.path) for r in chat.router.routes if isinstance(r, APIRoute) for m in sorted(r.methods)]
    arm("R1 the subject serves the seven /api/chat routes", len(served) >= 7 and all(p.startswith("/api/chat/") for _, p in served), served)
    pub = [(m, p) for m, p in served if (m, p) in obs.PUBLIC]
    arm("R1 no /api/chat route is a PUBLIC pair", not pub, pub)
    leaks = []
    for m, p in served + [("HEAD", p) for _, p in served] + [("OPTIONS", p) for _, p in served]:
        code = cl.request(m, p).status_code
        if code != 403:
            leaks.append(f"{m} {p} -> {code}")
    arm("R1 every /api/chat (method, path), HEAD and OPTIONS included, is 403 to a visitor", not leaks, leaks)

    # ── R2 upload ────────────────────────────────────────────────────────────────────────────────────────────
    r = cl.post("/api/chat/upload?name=run.sh", content=b"echo hi", headers=O)
    arm("R2 a type off the allowlist is 415", r.status_code == 415, r.status_code)
    r = cl.post("/api/chat/upload?name=a.png", content=b"", headers=O)
    arm("R2 an empty body is 400", r.status_code == 400, r.status_code)
    r = cl.post("/api/chat/upload?name=a.txt", content=b"x" * (chat.MAX_UPLOAD + 1), headers=O)
    arm("R2 a body over the cap is 413", r.status_code == 413, r.status_code)
    r = cl.post("/api/chat/upload?name=" + "../../evil name!.png", content=b"\x89PNGfixture", headers=O)
    j = r.json() if r.status_code == 200 else {}
    p = Path(j.get("path", "/nonexistent"))
    arm("R2 a good upload is 200 and lands under media/chat/", r.status_code == 200 and p.parent == media / "chat" and p.is_file(), (r.status_code, j))
    arm("R2 its name carries a random 24-hex token and a sanitized name (no '..', no space)",
        bool(re.fullmatch(r"chat-[0-9a-f]{24}-[A-Za-z0-9._-]+", p.name)) and ".." not in p.name and " " not in p.name, p.name)
    arm("R2 the bytes are written whole", p.is_file() and p.read_bytes() == b"\x89PNGfixture")
    r2 = cl.post("/api/chat/upload?name=a.png", content=b"two", headers=O)
    arm("R2 two uploads of one name never collide", r2.status_code == 200 and r2.json()["path"] != j.get("path"))
    arm("R2 the answer names only the stored file", set(j) == {"path", "name", "size", "type", "url"}, sorted(j))

    # ── R3 the file read ─────────────────────────────────────────────────────────────────────────────────────
    ok = cl.get("/api/chat/file", params={"path": str(p)}, headers=O)
    arm("R3 an uploaded file is served as its type", ok.status_code == 200 and ok.headers["content-type"] == "image/png"
        and ok.headers.get("x-content-type-options") == "nosniff", (ok.status_code, dict(ok.headers)))
    page = estate / "homes" / "fixture-agent" / "report.html"
    page.write_text("<script>alert(1)</script>")
    h = cl.get("/api/chat/file", params={"path": str(page)}, headers=O)
    arm("R3 an agent's .html is served as PLAIN TEXT, never as a page", h.status_code == 200 and h.headers["content-type"].startswith("text/plain"),
        (h.status_code, h.headers.get("content-type")))
    outside = tmp / "outside.txt"
    outside.write_text("secret")
    (media / "link.txt").symlink_to(outside)
    (estate / "homes" / "fixture-agent" / ".claude" / "session.json").write_text("{}")
    (estate / "homes" / "fixture-agent" / "org.env").write_text("K=V")
    probes = {
        "a '..' escape": str(media / ".." / ".." / "outside.txt"),
        "an absolute path outside": str(outside),
        "a symlink out of a root": str(media / "link.txt"),
        "a NUL byte": str(p) + "\x00.png",
        "a dot-path inside a home": str(estate / "homes" / "fixture-agent" / ".claude" / "session.json"),
        "an .env file": str(estate / "homes" / "fixture-agent" / "org.env"),
        "a directory": str(media),
        "a missing file": str(media / "nope.png"),
    }
    bad = {k: cl.get("/api/chat/file", params={"path": v}, headers=O).status_code for k, v in probes.items()}
    arm("R3 every escape is 404, the same answer as a missing file", all(c == 404 for c in bad.values()), bad)

    # ── R5 projects ──────────────────────────────────────────────────────────────────────────────────────────
    g = cl.get("/api/chat/projects", headers=O).json()
    arm("R5 no projects yet: an empty list and the empty etag", g == {"etag": "", "projects": []}, g)
    one = [{"id": "zeta", "name": "Zeta launch", "brief": "", "agents": ["fixture-agent"], "threads": ["chat:20990101-abc123"]}]
    arm("R5 no If-Match is 428", cl.put("/api/chat/projects", json=one, headers=O).status_code == 428)
    w = cl.put("/api/chat/projects", json=one, headers={**O, "if-match": ""})
    arm("R5 a write with the current etag is 200 and returns the new one", w.status_code == 200 and len(w.json().get("etag", "")) == 64, w.text)
    before = chat.projects_file().read_text()
    stale = cl.put("/api/chat/projects", json=[], headers={**O, "if-match": ""})
    arm("R5 a stale If-Match is 409 and the file is untouched", stale.status_code == 409 and chat.projects_file().read_text() == before, stale.status_code)
    tag = w.json().get("etag", "")
    for label, bad_list in (("an id with capitals", [{**one[0], "id": "Zeta"}]), ("two projects, one id", one + one),
                            ("a non-chat thread", [{**one[0], "threads": ["wa:x"]}]), ("a bad agent name", [{**one[0], "agents": ["../x"]}])):
        r = cl.put("/api/chat/projects", json=bad_list, headers={**O, "if-match": tag})
        arm(f"R5 {label} is 400, nothing written", r.status_code == 400 and chat.projects_file().read_text() == before, r.status_code)
    back = cl.get("/api/chat/projects", headers=O).json()
    arm("R5 the project round-trips", back.get("projects") == one and back.get("etag") == tag, back)

    # ── R6 dictation ─────────────────────────────────────────────────────────────────────────────────────────
    os.environ.pop("OPENAI_API_KEY", None)
    called = []

    async def spy(cfg):                     # never the real provider: a mutant that skips the key check must not
        called.append(cfg)                  # reach the network, only be counted
        return 500, {}
    chat.V.mint = spy
    d = cl.post("/api/chat/dictate/session", headers=O)
    arm("R6 with no OpenAI key the session is refused (503) and nothing is minted", d.status_code == 503 and not called, (d.status_code, d.text))
    arm("R6 the refusal names no key", "sk-" not in d.text and "OPENAI_API_KEY" not in d.text, d.text)

    # ── commands ─────────────────────────────────────────────────────────────────────────────────────────────
    c = cl.get("/api/chat/commands", headers=O).json()
    want = sorted(x.parent.name for x in (REPO / "skills").glob("*/SKILL.md"))
    got = sorted(s["name"] for s in c.get("skills", []))
    arm("COMMANDS the / list is the org's real skills", got == want and len(want) > 0, (got, want))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as td:
        os.environ["OBS_KEY"] = "test-owner-key"
        os.environ.setdefault("ASTRYX_DSN", "postgresql://oracle@127.0.0.1:1/none")   # never connected: no lifespan
        os.environ["ASTRYX_ORG"] = "fixture.example"
        os.environ.setdefault("ASTRYX_COG_REGISTRY", str(Path(td) / "absent.json"))
        main(Path(td))
    print(f"{'PASS' if not fails else 'FAIL'}: chat API ({fails} failing)")
    sys.exit(1 if fails else 0)
