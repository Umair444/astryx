#!/usr/bin/env python3
"""Oracle: plan-11884, /chat's server half (observatory/api/chat.py) and serve_untrusted (src/astryx/security/serve.py).
In-process: the estate is a temp dir (chat.bind), the app's lifespan runs on a throwaway fixture database (fixture_db),
no OpenAI key is set, so nothing leaves the host.
  - R1/G1 GATE: every /api/chat (method, path) the subject serves, HEAD and OPTIONS too, is 403 to a visitor; none is
    a PUBLIC pair.
  - D1: /api/chat/file is 403 with ONLY ?key= (and with ?key= beside the header): a navigation never authenticates it;
    200 with the header.
  - D3 UPLOAD: the BYTES decide (a script or an svg is 415 whatever its name); an empty body 400, an oversize one 413;
    the stored name is server-minted (uuid + the sniffed extension) under media/upload/, the client's name only
    display metadata; two uploads of one name make two files; the answer names nothing else.
  - G3 SERVING: every answer of the file route carries nosniff and the CSP sandbox; an allowlisted type is served as
    itself; an agent's page is plain text; bytes off the allowlist are an octet-stream ATTACHMENT; serve_untrusted's
    frame_pdf drops the sandbox only for a magic-verified PDF.
  - R3: a '..' escape, an outside path, a symlink out, NUL, a home's dot-path, an .env, a directory: 404 like a miss.
  - R5/D6' PROJECTS: 428 / 409 / 400 as before; a read names the agents no longer on the roster in `missing`, which is
    never stored.
  - D4 WORK: a turn is filed under EVERY thread it touched: opened here, OR answered here from a turn another thread
    opened (the mutant that files by input_msg_id only loses it); each turn names its other threads; the done-marks
    are dropped; an unrelated turn never appears; the newest unlinked steps are the live lane; older unlinked steps
    are counted, never dropped. The other side, so each work() statement also returns zero rows (sqlguard RESPONSIVE):
    a turn with no steps is filed with none, a party with nothing unlinked has an empty lane, and a thread nobody
    wrote to answers empty.
  - R6 DICTATE: with no OpenAI key the session is refused (503) and nothing is minted.
  - COMMANDS: the / list is the org's real skills.
CHAT_SRC names another chat.py, SERVE_SRC another serve.py (devtools/mutation_probe.py: tests/mutants_chat_api.py,
tests/mutants_serve_untrusted.py)."""
import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_chat_api", REPO, deps=("fastapi", "httpx", "asyncpg", "psycopg"), env=False)   # fixture_db only
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402

SUBJECT = Path(os.environ.get("CHAT_SRC") or REPO / "observatory" / "api" / "chat.py")
O = {"x-obs-key": "test-owner-key"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF = b"%PDF-1.4\n%fixture\n"
fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


QUIET_THREAD = "chat:20990101-quiet"
EMPTY_THREAD = "chat:20990101-nobody-wrote-here"


def seed_work(url: str):
    """D4's fixture: one chat thread, its agent 'zeta', four turns, steps linked and unlinked."""
    import psycopg
    T = "chat:20990101-fixture"
    Q = QUIET_THREAD
    with psycopg.connect(url, autocommit=True) as c:
        def msg(frm, to, thread, turn=None):
            return c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body, turn_id) "
                             "VALUES (%s,%s,%s,'chat','fixture body',%s) RETURNING id", (frm, to, thread, turn)).fetchone()[0]

        def turn(inp, start, end):
            return c.execute("INSERT INTO turns (agent, started_at, ended_at, input_msg_id) VALUES "
                             "('zeta', now() - make_interval(mins => %s), now() - make_interval(mins => %s), %s) RETURNING id",
                             (start, end, inp)).fetchone()[0]

        def step(kind, content, turn_id, mins_ago):
            c.execute("INSERT INTO steps (agent, kind, content, turn_id, ts) VALUES ('zeta', %s, %s, %s, "
                      "now() - make_interval(mins => %s))", (kind, content, turn_id, mins_ago))
        m1 = msg("owner", "zeta", T)
        a = turn(m1, 60, 55)                                  # A: opened here, answered here
        step("tool", "Bash: read the fixture", a, 58)
        step("tool_done", "Bash done", a, 57)
        msg("zeta", "owner", T, a)
        m3 = msg("owner", "zeta", "wa:fixture-other")
        b = turn(m3, 50, 45)                                  # B: opened ELSEWHERE, answered HERE
        step("tool", "Bash: the cross-thread work", b, 48)
        msg("zeta", "owner", T, b)
        m5 = msg("owner", "zeta", T)
        cc = turn(m5, 40, 35)                                 # C: opened here, answered ELSEWHERE
        step("milestone", "answered on the plan thread", cc, 37)
        msg("zeta", "someone", "plan-fixture", cc)
        d = turn(msg("owner", "zeta", "wa:fixture-unrelated"), 30, 25)   # D: never touches T
        step("tool", "Bash: unrelated", d, 28)
        step("tool", "Bash: lost before the last turn end", None, 26)   # unlinked, older than the last end: COUNTED
        step("tool", "Bash: working right now", None, 1)                # unlinked, newer: the LIVE lane
        c.execute("UPDATE messages SET ts = now() - interval '2 hours' WHERE thread = %s", (T,))   # the chat began first
        # QUIET: a thread whose one turn (fixture-agent's) has no steps, and whose party has nothing unlinked since that
        # turn ended. Every work() statement then also returns ZERO rows once, the other side of the fixture above
        # (sqlguard's RESPONSIVE needs both: medic #62524, goal 4243)
        qm = msg("owner", "fixture-agent", Q)
        q = c.execute("INSERT INTO turns (agent, started_at, ended_at, input_msg_id) VALUES "
                      "('fixture-agent', now() - interval '20 minutes', now() - interval '19 minutes', %s) RETURNING id",
                      (qm,)).fetchone()[0]
    return T, (a, b, cc, d, q)


def main(tmp: Path, url: str):
    if os.environ.get("SERVE_SRC"):          # tests/mutants_serve_untrusted.py: judge another serve.py, loaded first
        import astryx.security  # noqa: F401
        sspec = importlib.util.spec_from_file_location("astryx.security.serve", os.environ["SERVE_SRC"])
        sm = importlib.util.module_from_spec(sspec)
        sys.modules["astryx.security.serve"] = sm
        sspec.loader.exec_module(sm)
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
    from astryx.security.serve import serve_untrusted

    estate = tmp / "estate"
    media = estate / "media"
    (estate / "homes" / "fixture-agent" / ".claude").mkdir(parents=True)
    media.mkdir(parents=True)
    chat.bind(lambda: obs.pool, estate, media, REPO, roster=lambda: {"zeta", "fixture-agent"})
    cl = TestClient(obs.app, raise_server_exceptions=False)   # a handler that throws is a 500 the arms judge
    cl.__enter__()                                            # the lifespan: the pool on the fixture database

    # ── R1/G1 the gate ───────────────────────────────────────────────────────────────────────────────────────
    served = [(m, r.path) for r in chat.router.routes if isinstance(r, APIRoute) for m in sorted(r.methods)]
    arm("G1 the subject serves the /api/chat routes", len(served) >= 8 and all(p.startswith("/api/chat/") for _, p in served), served)
    arm("G1 no /api/chat route is a PUBLIC pair", not [x for x in served if x in obs.PUBLIC])
    leaks = [f"{m} {p} -> {c}" for m, p in served + [("HEAD", p) for _, p in served] + [("OPTIONS", p) for _, p in served]
             if (c := cl.request(m, p).status_code) != 403]
    arm("G1 every /api/chat (method, path), HEAD and OPTIONS included, is 403 to a visitor", not leaks, leaks)

    # ── D3 upload ────────────────────────────────────────────────────────────────────────────────────────────
    for label, body, name in (("a script named .png", b"#!/bin/sh\x00\x01\x02rm", "photo.png"),
                              ("an svg", b"\x00<svg onload=alert(1)>", "logo.svg")):
        r = cl.post(f"/api/chat/upload?name={name}", content=body, headers=O)
        arm(f"D3 the bytes decide: {label} is 415", r.status_code == 415, r.status_code)
    arm("D3 an empty body is 400", cl.post("/api/chat/upload?name=a.png", content=b"", headers=O).status_code == 400)
    arm("D3 a body over the cap is 413",
        cl.post("/api/chat/upload?name=a.txt", content=b"x" * (chat.MAX_UPLOAD + 1), headers=O).status_code == 413)
    r = cl.post("/api/chat/upload?name=../../evil name!.png", content=PNG, headers=O)
    j = r.json() if r.status_code == 200 else {}
    p = Path(j.get("path", "/nonexistent"))
    arm("D3 a good upload lands under media/upload/ with a server-minted uuid name and the sniffed extension",
        r.status_code == 200 and p.parent == media / "upload" and re.fullmatch(r"[0-9a-f]{32}\.png", p.name) is not None
        and p.read_bytes() == PNG, (r.status_code, j))
    arm("D3 the client's name is display metadata only, sanitized", j.get("name") == "evil-name-.png" and "evil" not in p.name, j.get("name"))
    r2 = cl.post("/api/chat/upload?name=../../evil name!.png", content=PNG, headers=O)
    arm("D3 two uploads of one client name make two files", r2.status_code == 200 and r2.json()["path"] != j.get("path"))
    arm("D3 the answer names only the stored file", set(j) == {"path", "name", "size", "type"}, sorted(j))
    tr = cl.post("/api/chat/upload?name=notes.md", content="# a note\nplain".encode(), headers=O)
    t = tr.json() if tr.status_code == 200 else {"status": tr.status_code}
    arm("D3 text is accepted and stored as .txt", t.get("path", "").endswith(".txt") and t.get("type", "").startswith("text/plain"), t)

    # ── D1 + G3 the file read ────────────────────────────────────────────────────────────────────────────────
    ok = cl.get("/api/chat/file", params={"path": str(p)}, headers=O)
    arm("D1 the header reads the file (200)", ok.status_code == 200, ok.status_code)
    arm("G3 an allowlisted type is served as itself, nosniff, CSP sandbox",
        ok.headers.get("content-type") == "image/png" and ok.headers.get("x-content-type-options") == "nosniff"
        and ok.headers.get("content-security-policy", "").startswith("sandbox"), dict(ok.headers))
    only_q = cl.get("/api/chat/file", params={"path": str(p), "key": "test-owner-key"})
    both = cl.get("/api/chat/file", params={"path": str(p), "key": "test-owner-key"}, headers=O)
    arm("D1 ONLY ?key= is refused: a navigation never authenticates the file route", only_q.status_code in (401, 403), only_q.status_code)
    arm("D1 ?key= beside the header is refused too", both.status_code in (401, 403), both.status_code)
    page = estate / "homes" / "fixture-agent" / "report.html"
    page.write_text("<script>alert(1)</script>")
    h = cl.get("/api/chat/file", params={"path": str(page)}, headers=O)
    arm("G3 an agent's .html is plain TEXT under the sandbox, never a page",
        h.status_code == 200 and h.headers["content-type"].startswith("text/plain")
        and h.headers.get("content-security-policy", "").startswith("sandbox"), (h.status_code, dict(h.headers)))
    blob = estate / "homes" / "fixture-agent" / "data.bin"
    blob.write_bytes(b"\x00\x01\x02binary")
    bb = cl.get("/api/chat/file", params={"path": str(blob)}, headers=O)
    arm("G3 bytes off the allowlist are an octet-stream ATTACHMENT", bb.headers.get("content-type") == "application/octet-stream"
        and bb.headers.get("content-disposition", "").startswith("attachment"), dict(bb.headers))
    pdf = estate / "homes" / "fixture-agent" / "brief.pdf"
    pdf.write_bytes(PDF)
    fp = serve_untrusted(pdf, inline=True, frame_pdf=True)
    fake = estate / "homes" / "fixture-agent" / "fake.pdf"
    fake.write_bytes(b"<html>not a pdf</html>")
    ff = serve_untrusted(fake, inline=True, frame_pdf=True)
    arm("G3 frame_pdf drops the sandbox ONLY for a magic-verified PDF",
        "content-security-policy" not in fp.headers and fp.headers.get("x-content-type-options") == "nosniff"
        and ff.headers.get("content-security-policy", "").startswith("sandbox"), (dict(fp.headers), dict(ff.headers)))
    outside = tmp / "outside.txt"
    outside.write_text("secret")
    (media / "link.txt").symlink_to(outside)
    (estate / "homes" / "fixture-agent" / ".claude" / "session.json").write_text("{}")
    (estate / "homes" / "fixture-agent" / "org.env").write_text("K=V")
    probes = {"a '..' escape": str(media / ".." / ".." / "outside.txt"), "an absolute path outside": str(outside),
              "a symlink out of a root": str(media / "link.txt"), "a NUL byte": str(p) + "\x00.png",
              "a dot-path inside a home": str(estate / "homes" / "fixture-agent" / ".claude" / "session.json"),
              "an .env file": str(estate / "homes" / "fixture-agent" / "org.env"), "a directory": str(media),
              "a missing file": str(media / "nope.png")}
    bad = {k: cl.get("/api/chat/file", params={"path": v}, headers=O).status_code for k, v in probes.items()}
    arm("R3 every escape is 404, the same answer as a missing file", all(c == 404 for c in bad.values()), bad)

    # ── R5 / D6' projects ────────────────────────────────────────────────────────────────────────────────────
    g = cl.get("/api/chat/projects", headers=O).json()
    arm("R5 no projects yet: an empty list and the empty etag", g == {"etag": "", "projects": []}, g)
    one = [{"id": "zeta-launch", "name": "Zeta launch", "brief": "", "agents": ["zeta", "gone-agent"], "threads": ["chat:20990101-abc123"]}]
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
    arm("D6' a read names the agents off the live roster in `missing`",
        back.get("etag") == tag and back.get("projects", [{}])[0].get("missing") == ["gone-agent"], back)
    arm("D6' `missing` is never stored", "missing" not in before, before)

    # ── D4 the work ──────────────────────────────────────────────────────────────────────────────────────────
    T, (a, b, c, d, q) = seed_work(url)
    wk = cl.get("/api/chat/work", params={"thread": T}, headers=O)
    body = wk.json() if wk.status_code == 200 else {}
    got = {x["id"]: x for x in body.get("turns", [])}
    arm("D4 the work route answers", wk.status_code == 200, (wk.status_code, wk.text[:300]))
    arm("D4 a turn opened here is filed here", a in got)
    arm("D4 a turn opened ELSEWHERE that answered here is filed here (not by input_msg_id alone)",
        b in got and got[b]["elsewhere"] == ["wa:fixture-other"], got.get(b))
    arm("D4 a turn opened here that answered elsewhere names that thread", c in got and got[c]["elsewhere"] == ["plan-fixture"], got.get(c))
    arm("D4 an unrelated turn never appears", d not in got, sorted(got))
    arm("D4 the done-marks are dropped, the work kept", a in got and [s["kind"] for s in got[a]["steps"]] == ["tool"], got.get(a))
    live = body.get("live", {}).get("zeta", [])
    arm("D4 the newest unlinked step is the live lane", [s["content"] for s in live] == ["Bash: working right now"], live)
    arm("D4 the older unlinked step is COUNTED, never dropped", body.get("unlinked", {}).get("zeta") == 1, body.get("unlinked"))
    qk = cl.get("/api/chat/work", params={"thread": QUIET_THREAD}, headers=O).json()
    qt = {t["id"]: t for t in qk.get("turns", [])}
    arm("D4 a turn with no steps is still filed, with an empty step list", list(qt) == [q] and qt[q]["steps"] == [], qk)
    arm("D4 a party with nothing unlinked since its last turn has an empty live lane",
        qk.get("live") == {"fixture-agent": []} and qk.get("unlinked") == {"fixture-agent": 0}, qk)
    ek = cl.get("/api/chat/work", params={"thread": EMPTY_THREAD}, headers=O)
    arm("D4 a thread nobody wrote to answers empty, never an error",
        ek.status_code == 200 and ek.json() == {"turns": [], "live": {}, "unlinked": {}}, (ek.status_code, ek.text[:200]))

    # ── R6 dictation ─────────────────────────────────────────────────────────────────────────────────────────
    # HERMETIC AGAINST THE ESTATE (land RED 10-23): voice_mint.env() reads os.environ, then the estate's .env, so on the
    # live checkout a real key made unavailable() pass and the route reached mint. The key is decided HERE, for the
    # arm, by a stub on voice_mint.env (restored after); the live .env is never read for it, and never touched.
    called = []

    async def spy(cfg):                     # never the real provider: a mint is only counted
        called.append(cfg)
        return 500, {}
    real_env, real_mint = chat.V.env, chat.V.mint
    chat.V.mint = spy
    try:
        chat.V.env = lambda k, d="": "sk-test-fixture" if k == "OPENAI_API_KEY" else real_env(k, d)
        present = cl.post("/api/chat/dictate/session", headers=O)
        arm("R6 control: with a key PRESENT (the live estate's case) the route goes on to mint; the spy sees it",
            len(called) == 1 and present.status_code == 502, (present.status_code, len(called)))
        called.clear()
        chat.V.env = lambda k, d="": "" if k == "OPENAI_API_KEY" else real_env(k, d)
        dd = cl.post("/api/chat/dictate/session", headers=O)
        arm("R6 with NO key (decided by the stub, not by the host's .env) the session is refused (503), nothing minted",
            dd.status_code == 503 and not called, (dd.status_code, dd.text))
    finally:
        chat.V.env, chat.V.mint = real_env, real_mint

    # ── commands ─────────────────────────────────────────────────────────────────────────────────────────────
    cm = cl.get("/api/chat/commands", headers=O).json()
    want = sorted(x.parent.name for x in (REPO / "skills").glob("*/SKILL.md"))
    arm("COMMANDS the / list is the org's real skills", sorted(s["name"] for s in cm.get("skills", [])) == want and want, cm)
    cl.__exit__(None, None, None)


if __name__ == "__main__":
    try:
        with fixture_db() as fx, tempfile.TemporaryDirectory() as td:
            os.environ["ASTRYX_DSN"] = fx["url"]
            os.environ["OBS_KEY"] = "test-owner-key"
            os.environ["ASTRYX_ORG"] = "fixture.example"
            os.environ["ASTRYX_GATEWAY_PORT"] = "9"
            os.environ.setdefault("ASTRYX_COG_REGISTRY", str(Path(td) / "absent.json"))
            main(Path(td), fx["url"])
    except FixtureUnavailable as e:                     # no admin DSN reachable: 77 on a committed-only tree, 1 live
        from astryx.security.sqlguard.estate import unavailable
        unavailable("test_chat_api", REPO, e)
    print(f"{'PASS' if not fails else 'FAIL'}: chat API ({fails} failing)")
    sys.exit(1 if fails else 0)
