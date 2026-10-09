#!/usr/bin/env python3
"""Oracle: CANVAS (bridges/canvas.py, bridges/canvas_shell.py, nucleus/canvas.py) against a real schema.

A throwaway fixture DATABASE (sqlguard's one applier) so NOTIFY and every write stay off production.
The API runs in-process (TestClient on the prefixed ASGI app, lifespan and wire tap included).
Each arm is a property a viewer, an invitee or an agent depends on — the trust lines first.
"""
import asyncio
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
    html = render({"id": 7, "title": "T</script>", "version": 3}, '<script src="/kit/chart.umd.min.js"></script>',
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


if __name__ == "__main__":
    pure()
    with fixture_db() as fx:
        os.environ["ASTRYX_DSN"] = fx["url"]
        os.environ["OBS_KEY"] = "test-owner-key"
        library(fx["url"])
        cid, gt = api(fx["url"])
        asyncio.run(rows(fx["url"], cid, gt))
    print(f"{'PASS' if not fails else 'FAIL'}: canvas ({fails} failing)")
    sys.exit(1 if fails else 0)
