#!/usr/bin/env python3
"""Oracle: CANVAS (bridges/canvas.py, bridges/canvas_shell.py, nucleus/canvas.py) against a real schema.

A throwaway fixture DATABASE (sqlguard's one applier) so NOTIFY and every write stay off production.
The API runs in-process (TestClient on the prefixed ASGI app, lifespan and wire tap included).
Each arm is a property a viewer, an invitee or an agent depends on — the trust lines first.
"""
import asyncio
import contextlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nucleus.sqlguard.fixture import fixture_db  # noqa: E402

fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def pure():
    from nucleus import canvas as cv
    from nucleus.orgname import org_ok
    from bridges.canvas_shell import render
    print("pure")
    arm("ids: 12 / canvas-12 / cv:canvas-12 all name 12",
        cv.parse_id("12") == cv.parse_id("canvas-12") == cv.parse_id("cv:canvas-12") == 12)
    try:
        cv.parse_id("../12"); arm("a non-id is refused by name", False)
    except cv.CanvasError:
        arm("a non-id is refused by name", True)
    body, notes = cv.body_of("<!doctype html><html><head><title>x</title><style>.a{}</style></head>"
                             "<body><p>hi</p><script src='https://cdn.x/y.js'></script></body></html>")
    arm("a whole document keeps head styles + body, drops the skeleton",
        "<style>.a{}</style>" in body and "<p>hi</p>" in body and "<title>" not in body and "<html" not in body, body)
    arm("an external script is named in the notes (the CSP will block it)", any("EXTERNAL" in n for n in notes), notes)
    arm("publish writers: the canvas's agent, painter, seed, owner — not a stranger",
        cv.may_write("forge", "forge") and cv.may_write("forge", "painter") and not cv.may_write("forge", "scout"))
    html = render(7, "T</script>", 3, '<script src="/kit/chart.umd.min.js"></script>',
                  "https://h.example/canvas/kit/")
    arm("the shell's CSP forbids every network call", "connect-src &#x27;none&#x27;" in html)
    arm("/kit/ refs are rewritten to the real (prefixed) kit", 'src="https://h.example/canvas/kit/chart.umd.min.js"' in html)
    arm("a title cannot close the shim's script", "T</script>" not in html.split("<title>")[1].split("</title>")[0])
    arm("surface names are reserved at the federation door",
        not any(org_ok(o) for o in ("canvas", "whatsapp", "telegram", "discord", "local")) and org_ok("acme.org"))


def library(dsn):
    import psycopg
    from nucleus import canvas as cv
    print("library (nucleus/canvas.py)")
    with psycopg.connect(dsn) as c:
        cid = cv.create(c, "Probe", "forge", "owner", "b")
        arm("create registers the canvas's own thread",
            c.execute("SELECT agent FROM canvas_threads WHERE thread=%s", (f"cv:canvas-{cid}",)).fetchone() == ("forge",))
        try:
            cv.publish(c, cid, "<p>x</p>", "scout"); arm("a non-writer cannot publish", False)
        except cv.CanvasError:
            arm("a non-writer cannot publish", True)
        v1, _ = cv.publish(c, cid, "<p>one</p>", "forge")
        v2, _ = cv.publish(c, cid, "<p>two</p>", "painter")
        arm("publish = a new immutable version", (v1, v2) == (1, 2)
            and c.execute("SELECT count(*) FROM canvas_versions WHERE canvas_id=%s", (cid,)).fetchone()[0] == 2)
        v3 = cv.rollback(c, cid, 1, "owner")
        arm("rollback republishes the old html as a NEW version", v3 == 3 and c.execute(
            "SELECT html FROM canvas_versions WHERE canvas_id=%s AND version=3", (cid,)).fetchone()[0] == "<p>one</p>")
        cv.set_data(c, cid, "k", {"a": 1}, f"canvas-{cid}")
        arm("the page itself (canvas-<id>) may write its own data", cv.get_data(c, cid, "k") == {"a": 1})
        try:
            cv.set_data(c, cid, "k", 2, "canvas-999"); arm("another canvas cannot write this one's data", False)
        except cv.CanvasError:
            arm("another canvas cannot write this one's data", True)
        old = cv.RATE_N
        cv.RATE_N = 3
        try:
            cv.publish(c, cid, "<p>4</p>", "forge"); arm("the per-canvas publish rate cap holds", False)
        except cv.CanvasError:
            arm("the per-canvas publish rate cap holds", True)
        cv.RATE_N = old
        try:
            cv.publish(c, cid, "x" * (cv.MAX_HTML + 1), "forge"); arm("the size cap holds", False)
        except cv.CanvasError:
            arm("the size cap holds", True)
        c.rollback()


def api(url):
    from fastapi.testclient import TestClient
    import bridges.canvas as b
    from nucleus import canvas as cv_lib
    print("api (bridges/canvas.py, in-process)")
    H = {"x-astryx": "1"}
    A = "/canvas/api"
    # ONE client (one event loop owns the pool); identities are cookie jars swapped in and out
    with TestClient(b.root, base_url="http://testserver") as cl:
        jars = {}

        def who(name):
            cl.cookies.clear()
            for k, v in jars.get(name, {}).items():
                cl.cookies.set(k, v, path="/canvas")
            return cl

        def keep(name):
            jars[name] = {c.name: c.value for c in cl.cookies.jar}

        arm("anonymous is 401", who("anon").get(f"{A}/me").status_code == 401)
        arm("a write without x-astryx is 403 (CSRF)", who("anon").post(f"{A}/login", json={"key": "k"}).status_code == 403)
        arm("owner logs in with the owner key",
            who("anon").post(f"{A}/login", json={"key": "test-owner-key"}, headers=H).status_code == 200)
        keep("owner")
        r = who("owner").post(f"{A}/users", json={"name": "guest", "agents": ["painter"]}, headers=H).json()
        arm("guest login with the invite token",
            who("anon").post(f"{A}/login", json={"key": r["token"]}, headers=H).status_code == 200)
        keep("guest")
        me = who("guest").get(f"{A}/me").json()
        arm("an invitee is cv-<name>, never owner", me["wire"] == "cv-guest" and me["owner"] is False, me)
        arm("an invitee with nothing yet sees no canvases and no threads",
            who("guest").get(f"{A}/canvases").json() == [] and who("guest").get(f"{A}/threads").json() == [])
        arm("an invitee sees only granted agents", [a["name"] for a in who("guest").get(f"{A}/agents").json()] == ["painter"])
        arm("an invitee cannot open a thread with an ungranted agent",
            who("guest").post(f"{A}/threads", json={"agent": "seed"}, headers=H).status_code == 403)
        t = who("guest").post(f"{A}/threads", json={"agent": "painter"}, headers=H).json()["thread"]
        m = who("guest").post(f"{A}/threads/{t}/messages", json={"body": "@seed please do X"}, headers=H).json()
        arm("an @mention cannot route past a grant",
            m.get("to") == "painter" and m.get("from") == "cv-guest" and m.get("from_org") == "canvas", m)
        arm("the owner's admin views are owner-only", who("guest").get(f"{A}/users").status_code == 403)
        c = who("owner").post(f"{A}/canvases", json={"title": "Pulse", "brief": "b"}, headers=H).json()
        arm("the owner's canvas is invisible to an invitee", who("guest").get(f"{A}/canvases/{c['id']}").status_code == 404)
        who("owner").post(f"{A}/canvases/{c['id']}/ask", json={"text": "@seed escalate", "frame": True}, headers=H)
        who("owner").post(f"{A}/canvases/{c['id']}/data", json={"key": "x", "value": 5}, headers=H)
        p = who("owner").post(f"{A}/canvases", json={"title": "Mine", "tier": "personal"}, headers=H).json()
        arm("a personal-tier canvas is never shared",
            who("owner").post(f"{A}/canvases/{p['id']}/share", json={"users": ["guest"]}, headers=H).status_code == 400)
        # ── THE PRIVACY GATES at the bridge (steward; a3 #35598): share AND view read steward/pii_canvas ──
        with psycopg_conn(url) as pc:
            s_id = cv_lib.create(pc, "Shared", "painter", "owner")
            cv_lib.publish(pc, s_id, "<p>clean</p>", "painter")
            pc.execute("DELETE FROM triggers WHERE agent='steward' AND name='pii_canvas'")
            pc.commit()
        arm("share with no privacy verdict at all → 409 (fail closed)",
            who("owner").post(f"{A}/canvases/{s_id}/share", json={"users": ["guest"]}, headers=H).status_code == 409)

        def verdict(open_=None):
            with psycopg_conn(url) as pc:
                pc.execute("DELETE FROM triggers WHERE agent='steward' AND name='pii_canvas'")
                pc.execute("INSERT INTO triggers (agent, name, schedule, kind, state) VALUES "
                           "('steward','pii_canvas','*/5 * * * *','python', jsonb_build_object("
                           "'checked_at', now()::text, 'open', %s::jsonb))", (json.dumps(open_ or {}),))
                pc.commit()
        verdict()
        arm("a scanned, clean canvas shares", who("owner").post(
            f"{A}/canvases/{s_id}/share", json={"users": ["guest"]}, headers=H).status_code == 200)
        g1 = who("guest").get(f"{A}/canvases/{s_id}/render?v=1").json()
        arm("the guest reads the CLEARED version", g1.get("html") and not g1.get("withheld"), g1)
        with psycopg_conn(url) as pc:
            cv_lib.publish(pc, s_id, "<p>call 15555550123</p>", "painter")      # after the share, after the scan
            pc.commit()
        g2 = who("guest").get(f"{A}/canvases/{s_id}/render?v=2").json()
        arm("a version published AFTER sharing is WITHHELD from the guest until scanned (the bypass a3 found)",
            g2.get("html") is None and g2.get("withheld") and "pending privacy scan" in g2["withheld"][0], g2)
        arm("...the head is withheld too (no ?v)", who("guest").get(f"{A}/canvases/{s_id}/render").json().get("html") is None)
        arm("...and the OWNER still sees it", who("owner").get(f"{A}/canvases/{s_id}/render?v=2").json().get("html"))
        who("owner").post(f"{A}/canvases/{s_id}/data", json={"key": "k", "value": 1}, headers=H)
        gd = who("guest").get(f"{A}/canvases/{s_id}/data")
        arm("live data changed after the scan is withheld from the guest (empty, with the reason in a header)",
            gd.json() == {} and "pending privacy scan" in gd.headers.get("x-astryx-withheld", ""), gd.headers)
        verdict({"h": {"cid": s_id, "src": f"canvas:{s_id}:v2", "loc": "x", "label": "phone-bare"}})
        g2b = who("guest").get(f"{A}/canvases/{s_id}/render?v=2").json()
        arm("once scanned, a FLAGGED version stays withheld; the clean one is served",
            g2b.get("html") is None and "owner-PII" in g2b["withheld"][0]
            and who("guest").get(f"{A}/canvases/{s_id}/render?v=1").json().get("html"), g2b)
        verdict({"d": {"cid": s_id, "src": f"canvas:{s_id}:data:k", "loc": "x", "label": "phone-bare"}})
        gdf = who("guest").get(f"{A}/canvases/{s_id}/data")       # scanned AFTER the write: only the FINDING holds it
        arm("a scanned, FLAGGED data value is withheld from the guest (a3 M3); the owner reads it",
            gdf.json() == {} and "withheld" in gdf.headers.get("x-astryx-withheld", "")
            and "pending" not in gdf.headers.get("x-astryx-withheld", "")
            and who("owner").get(f"{A}/canvases/{s_id}/data").json() == {"k": 1}, gdf.headers)
        # C2 (a3 #36233): title/brief and publish NOTES are agent-written and served to guests — gated too
        with psycopg_conn(url) as pc:
            cv_lib.publish(pc, s_id, "<p>three</p>", "painter", "added 15555550123")
            pc.commit()
        verdict({"m": {"cid": s_id, "src": f"canvas:{s_id}:meta", "loc": "x", "label": "phone-bare"},
                 "n": {"cid": s_id, "src": f"canvas:{s_id}:v3:note", "loc": "x", "label": "phone-bare"}})
        gl = {c["id"]: c for c in who("guest").get(f"{A}/canvases").json()}
        arm("a flagged TITLE is masked in the guest's canvas list; the owner sees it",
            gl[s_id]["title"].startswith("(withheld") and gl[s_id]["brief"] is None
            and any(c["id"] == s_id and not c["title"].startswith("(withheld")
                    for c in who("owner").get(f"{A}/canvases").json()), gl.get(s_id))
        gv = {x["version"]: x for x in who("guest").get(f"{A}/canvases/{s_id}").json()["versions"]}
        arm("a flagged publish NOTE is masked for THAT version only",
            gv[3]["note"].startswith("(withheld") and not (gv[1]["note"] or "").startswith("(withheld"), gv)
        arm("...and the owner reads the note", who("owner").get(f"{A}/canvases/{s_id}").json()["versions"][0]["note"]
            == "added 15555550123")
        with psycopg_conn(url) as pc:
            m_id = cv_lib.create(pc, "Plain", "painter", "owner")
            pc.commit()
        verdict({"m": {"cid": m_id, "src": f"canvas:{m_id}:meta", "loc": "x", "label": "phone-bare"}})
        arm("a flagged title blocks a WIDENING share",
            who("owner").post(f"{A}/canvases/{m_id}/share", json={"users": ["guest"]}, headers=H).status_code == 409)
        arm("narrowing the audience is never gated", who("owner").post(
            f"{A}/canvases/{s_id}/share", json={"users": []}, headers=H).status_code == 200)
        with psycopg_conn(url) as pc:
            pc.execute("DELETE FROM triggers WHERE agent='steward' AND name='pii_canvas'")
            pc.commit()
        who("owner").post(f"{A}/users/guest/revoke", headers=H)
        arm("a revoked invitee's live session dies", who("guest").get(f"{A}/me").status_code == 401)
        return c["id"], t


async def rows(url, cid, guest_thread):
    import asyncpg
    import bridges.canvas as b
    conn = await asyncpg.connect(url)
    try:
        task = await conn.fetchrow("SELECT * FROM messages WHERE thread=$1 AND intent='task'", f"cv:canvas-{cid}")
        arm("a new canvas briefs its painter, from the owner on the canvas thread",
            task and task["to_agent"] == "painter" and task["from_agent"] == "owner" and task["from_org"] == "canvas")
        frame = await conn.fetchrow("SELECT * FROM messages WHERE thread=$1 AND intent='canvas'", f"cv:canvas-{cid}")
        arm("a click inside the page is stamped canvas-<id>, never the viewer (confused deputy)",
            frame and frame["from_agent"] == f"canvas-{cid}" and frame["from_org"] == "canvas")
        arm("page text cannot @mention its way to another agent", frame and frame["to_agent"] == "painter")
        d = await conn.fetchrow("SELECT updated_by FROM canvas_data WHERE canvas_id=$1 AND key='x'", cid)
        arm("a page's data write is stamped canvas-<id>", d and d["updated_by"] == f"canvas-{cid}")
        # the claim: ours exactly once, never another surface's
        ids = [await conn.fetchval(
            "INSERT INTO messages (from_agent, to_agent, thread, body) VALUES ($1,$2,$3,'r') RETURNING id", *x)
            for x in (("painter", "owner", f"cv:canvas-{cid}"), ("seed", "owner", "t-elsewhere"),
                      ("painter", "cv-guest", None), ("seed", "owner", "wa:123@s.whatsapp.net"))]
        await b.claim(conn)
        await asyncio.sleep(0.3)
        st = {r["id"]: r for r in await conn.fetch("SELECT id, status, delivery FROM messages WHERE id = ANY($1)", ids)}
        arm("an owner reply on a cv: thread is claimed + receipted",
            st[ids[0]]["status"] == "delivered" and '"canvas:owner"' in st[ids[0]]["delivery"])
        arm("an un-threaded reply to an invitee lands in canvas", st[ids[2]]["status"] == "delivered")
        arm("an owner row on another surface's thread is NOT taken (t-, wa:)",
            st[ids[1]]["status"] == "pending" and st[ids[3]]["status"] == "pending")
    finally:
        await conn.close()


def coverage(url):
    """Every SQL site both ways — a row found AND a row not found — so sqlguard can call each one
    RESPONSIVE (its W witness), not merely executed. Each call is also a real behaviour check."""
    import io
    import contextlib
    from fastapi.testclient import TestClient
    import bridges.canvas as b
    from bridges.providers.canvas import CanvasProvider
    from nucleus import canvas as cv
    print("coverage (every SQL site, found and not-found)")
    H = {"x-astryx": "1"}
    A = "/canvas/api"
    with TestClient(b.root, base_url="http://testserver") as cl:
        cl.post(f"{A}/login", json={"key": "nope"}, headers=H)                       # login: 0 rows
        r = cl.post(f"{A}/login", json={"key": "test-owner-key"}, headers=H)
        arm("owner session for coverage", r.status_code == 200)
        with psycopg_conn(url) as c:
            c.execute("INSERT INTO steps (agent, kind, content) VALUES ('painter', 'tool', 'cov')")
            c.commit()
        arm("agent activity is read from steps", any(a["last_seen"] for a in cl.get(f"{A}/agents").json()))
        arm("list canvases", isinstance(cl.get(f"{A}/canvases").json(), list))
        arm("list threads", isinstance(cl.get(f"{A}/threads").json(), list))
        arm("users list", isinstance(cl.get(f"{A}/users").json(), list))
        cl.post(f"{A}/users", json={"name": "cov", "agents": []}, headers=H)
        arm("grants on a real and a missing user", cl.post(f"{A}/users/cov/grants", json={"name": "cov", "agents": ["painter"]}, headers=H).status_code == 200
            and cl.post(f"{A}/users/ghost/grants", json={"name": "ghost", "agents": []}, headers=H).status_code == 200)
        cl.post(f"{A}/users/ghost/revoke", headers=H)                                # revoke: 0 rows
        empty = cl.post(f"{A}/canvases", json={"title": "Empty"}, headers=H).json()
        full = cl.post(f"{A}/canvases", json={"title": "Full"}, headers=H).json()
        arm("a missing canvas is 404 everywhere",
            all(cl.get(f"{A}/canvases/999999{x}").status_code == 404 for x in ("", "/render", "/data")))
        arm("an unpainted canvas renders nothing", cl.get(f"{A}/canvases/{empty['id']}/render").json()["html"] is None)
        with psycopg_conn(url) as c:
            cv.publish(c, full["id"], "<p>v1</p>", "painter")
            cv.set_data(c, full["id"], "k", 1, "painter")
            c.commit()
        arm("a painted canvas renders its version", "<p>v1</p>" in (cl.get(f"{A}/canvases/{full['id']}/render").json()["html"] or ""))
        arm("an absent version renders nothing", cl.get(f"{A}/canvases/{full['id']}/render?v=99").json()["html"] is None)
        arm("data: all + one key + a missing key",
            cl.get(f"{A}/canvases/{full['id']}/data").json() == {"k": 1}
            and cl.get(f"{A}/canvases/{full['id']}/data?key=k").json()["value"] == 1
            and cl.get(f"{A}/canvases/{full['id']}/data?key=nope").json()["value"] is None
            and cl.get(f"{A}/canvases/{empty['id']}/data").json() == {})
        arm("versions listed for painted + unpainted",
            len(cl.get(f"{A}/canvases/{full['id']}").json()["versions"]) == 1
            and cl.get(f"{A}/canvases/{empty['id']}").json()["versions"] == [])
        # the share gate fails closed without a privacy verdict (steward/pii_canvas), so give it a cleared one
        with psycopg_conn(url) as pc:
            pc.execute("DELETE FROM triggers WHERE agent='steward' AND name='pii_canvas'")
            pc.execute("INSERT INTO triggers (agent, name, schedule, kind, state) VALUES ('steward','pii_canvas',"
                       "'*/5 * * * *','python', jsonb_build_object('checked_at', now()::text, 'open', '{}'::jsonb))")
            pc.commit()
        arm("share an org canvas (cleared by the privacy sweep)", cl.post(f"{A}/canvases/{full['id']}/share", json={"users": ["cov"]}, headers=H).json().get("shared_with") == ["cov"])
        arm("archive", cl.post(f"{A}/canvases/{empty['id']}/archive", headers=H).status_code == 200
            and cl.post(f"{A}/canvases/999999/archive", headers=H).status_code == 404)
        t = cl.post(f"{A}/threads", json={"agent": "painter"}, headers=H).json()["thread"]
        arm("an empty thread reads empty; a missing one is 404",
            cl.get(f"{A}/threads/{t}/messages").json()["messages"] == []
            and cl.get(f"{A}/threads/cv:nope/messages").status_code == 404)
        cl.post(f"{A}/threads/{t}/messages", json={"body": "hello"}, headers=H)
        arm("a thread with a message reads it", len(cl.get(f"{A}/threads/{t}/messages").json()["messages"]) == 1)
        arm("the owner's thread list now has it", any(x["thread"] == t for x in cl.get(f"{A}/threads").json()))
        arm("a canvas thread includes the page's rows",
            cl.get(f"{A}/threads/cv:canvas-{full['id']}/messages").status_code == 200)
        mid = cl.get(f"{A}/threads/{t}/messages").json()["messages"][0]["id"]
        arm("a file not named by the message is 404; a missing message is 404",
            cl.get(f"{A}/file?msg={mid}&n=0").status_code == 404 and cl.get(f"{A}/file?msg=999999999&n=0").status_code == 404)
        sm = cl.post(f"{A}/canvases/{full['id']}/ask", json={"text": "make this weekly", "frame": False, "agent": "forge",
                     "element": {"selector": "#hero", "tag": "div", "text": "17", "html": "<div id=hero>17</div>"}}, headers=H)
        crew = cl.get(f"{A}/canvases/{full['id']}").json().get("crew", [])
        cl.post(f"{A}/canvases/{full['id']}/ask", json={"text": "and again", "frame": False, "agent": "forge"}, headers=H)
        crew2 = cl.get(f"{A}/canvases/{full['id']}").json().get("crew", [])
        with psycopg_conn(url) as c:
            pr = c.execute("SELECT surface, state FROM presence WHERE agent='forge'").fetchone()
        arm("summoning brings an agent onto the crew ONCE, and it appears on the canvas at once (moving)",
            sm.status_code == 200 and crew == ["forge"] and crew2 == ["forge"] and pr == (f"canvas:{full['id']}", "moving"),
            (sm.status_code, crew, crew2, pr))
        arm("logout ends the session", cl.post(f"{A}/logout", headers=H).status_code == 200 and cl.get(f"{A}/me").status_code == 401)
        cl.post(f"{A}/logout", headers=H)                                          # logout: 0 rows

    async def rows2():
        import asyncpg
        conn = await asyncpg.connect(url)
        try:
            ids = [await conn.fetchval("INSERT INTO messages (from_agent, to_agent, thread, body) VALUES ($1,$2,$3,'r') RETURNING id", *x)
                   for x in (("forge", "owner", "cv:opened-by-an-agent"), ("forge", f"canvas-{full['id']}", "t-x"),
                             ("forge", "canvas-999999", "t-y"), ("forge", "cv-nobody", None))]
            await b.claim(conn)
            st = {r["id"]: r["status"] for r in await conn.fetch("SELECT id, status FROM messages WHERE id = ANY($1)", ids)}
            reg = await conn.fetchval("SELECT user_name FROM canvas_threads WHERE thread='cv:opened-by-an-agent'")
            arm("an agent opening a NEW cv: thread to the owner registers it in the owner's list", reg == "owner")
            arm("replies to canvas-<id> (real or gone) are claimed", st[ids[1]] == st[ids[2]] == "delivered")
            await b.on_canvas({"kind": "canvas", "canvas": full["id"], "version": 1})
            arm("presence fan-out: viewers of a real canvas / of a missing one",
                "owner" in await b.canvas_viewers(f"canvas:{full['id']}") and await b.canvas_viewers("canvas:999999") == set())
            await b.on_presence({"agent": "nobody-at-all"})          # no row: nothing to fan out
            await conn.execute("INSERT INTO presence (agent, surface, state) VALUES ('scout', $1, 'working') "
                               "ON CONFLICT (agent) DO UPDATE SET surface=EXCLUDED.surface", f"canvas:{full['id']}")
            await b.on_presence({"agent": "scout"})
            arm("a presence row reaches the canvas's cache", b.present.get("scout", {}).get("surface") == f"canvas:{full['id']}")
            await b.on_canvas({"kind": "data", "canvas": 999999, "key": "k"})
        finally:
            await conn.close()
    import asyncio as _a
    b.pool = None
    _a.run(_pool_run(url, rows2))

    async def prov():
        p = CanvasProvider()
        chats = await p.list_chats()
        hit, miss = await p.search_contacts("cov"), await p.search_contacts("zzz")
        r1, r2 = await p.resolve("canvas:cv-cov"), await p.resolve("canvas:cv-ghost")
        arm("provider: chats listed, contacts found/not, resolve found/not",
            len(chats) > 0 and len(hit) == 1 and miss == [] and r1 is not None and r2 is None)
    _a.run(prov())

    with psycopg_conn(url) as c:
        arm("get_data: {} on a bare canvas, every key on a full one",
            cv.get_data(c, empty["id"]) == {} and cv.get_data(c, full["id"]) == {"k": 1})
        for bad in (lambda: cv.publish(c, 999999, "<p/>", "seed"), lambda: cv.rollback(c, full["id"], 99, "seed"),
                    lambda: cv.get_data(c, full["id"], "nope")):
            try:
                bad(); arm("a missing canvas/version/key is a named error", False)
            except cv.CanvasError:
                pass
        c.rollback()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = [cv.main(["list"]), cv.main(["list", "--all"]), cv.main(["versions", str(full["id"])]),
              cv.main(["versions", str(empty["id"])]), cv.main(["show", str(full["id"])]),
              cv.main(["show", str(full["id"]), "--version", "42"])]
    # presence: the general primitive, its CLI both ways
    from nucleus import presence as pres
    pout = io.StringIO()
    os.environ["ASTRYX_AGENT"] = "scout"
    with contextlib.redirect_stdout(pout):
        prc = [pres.main(["show"]), pres.main(["focus", f"cv:canvas-{full['id']}", "--target", "#x", "--say", "on it"]),
               pres.main(["show", f"canvas-{full['id']}"]), pres.main(["show", "canvas:999999"]),
               pres.main(["done", "--say", "finished"]), pres.main(["clear"]), pres.main(["focus", "nonsense"])]
    os.environ.pop("ASTRYX_AGENT", None)
    txt = pout.getvalue()
    arm("presence CLI: focus/show/done/clear work; a naive surface is normalised; nonsense is refused (rc 1)",
        prc == [0, 0, 0, 0, 0, 0, 1] and f"canvas:{full['id']}" in txt and "(nobody present)" in txt, (prc, txt[-300:]))
    arm("the CLI: list, versions (some/none), show (found / missing version → rc 1)", rc == [0, 0, 0, 0, 0, 1], rc)


@contextlib.contextmanager
def psycopg_conn(url):
    import psycopg
    with psycopg.connect(url) as c:
        yield c


async def _pool_run(url, fn):
    import asyncpg
    import bridges.canvas as b
    b.pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        await fn()
    finally:
        await b.pool.close()


if __name__ == "__main__":
    pure()
    with fixture_db() as fx:
        os.environ["ASTRYX_DSN"] = fx["url"]
        os.environ["OBS_KEY"] = "test-owner-key"
        library(fx["url"])
        cid, gt = api(fx["url"])
        asyncio.run(rows(fx["url"], cid, gt))
        coverage(fx["url"])
    print(f"{'PASS' if not fails else 'FAIL'}: canvas ({fails} failing)")
    sys.exit(1 if fails else 0)
