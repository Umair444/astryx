#!/usr/bin/env python3
"""The cog front pipes hands' noVNC websocket to an org's backend, and widens nothing (owner 11-19, medic #67140).

Before 9ff74297 the front had no websocket route: /api/hands/<desk>/vnc fell to StaticFiles and 500'd, so the
owner's Join read "connection closed". This runs the REAL front app in-process on a free loopback port, with its
org table pointed at a FAKE backend websocket (no live front, no desk, no key from .env), and asserts:
  1 bytes pass both ways and the subprotocol is echoed        5 a client close reaches the backend, 0 tasks left
  2 the query reaches the backend intact                     6 a backend close reaches the client, 0 tasks left,
  3 a backend refusal before accept is a 403, nothing opens      and no "Task exception was never retrieved"
  4 an unknown org is a 403, by /o/ and by the chosen org     7 no Cookie and no x-astryx-* header reach the backend
                                                              8 an agent holding %3F stays one path segment
Red control: on a front with no websocket route every pipe arm fails (the 500 it fixed).
"""
import asyncio
import gc
import logging
import socket
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "observatory"))
sys.path.insert(0, str(REPO / "src"))
try:
    import uvicorn
    import websockets
    import front
except Exception as e:  # noqa: BLE001
    print(f"SKIP: the front or its deps don't import here ({type(e).__name__}): the vnc pipe was NOT verified")
    sys.exit(77)

FAILS: list[str] = []


def arm(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


SEEN: list[dict] = []            # what the fake backend was asked for, one entry per handshake
CLOSED: list[int] = []           # the close code the backend saw from the front, per connection


async def backend(conn):
    req = conn.request
    SEEN.append({"path": req.path, "headers": {k.lower(): v for k, v in req.headers.raw_items()}})
    if "refuse" in req.path:
        return
    try:
        async for m in conn:
            if m == b"bye":                          # arm 6: the backend dies mid-session (no close frame)
                conn.transport.abort()
                return
            await conn.send(b"echo:" + m)
    except websockets.ConnectionClosed:
        pass
    finally:
        CLOSED.append(conn.close_code or 0)


async def process_request(conn, request):
    if "refuse" in request.path:                    # arm 3: refused before accept, as the real route does on a bad key
        return conn.respond(403, "no\n")
    return None


def pending() -> int:
    me = asyncio.current_task()
    return sum(1 for t in asyncio.all_tasks() if t is not me and not t.done()
               and t.get_coro().__qualname__.startswith(("_vnc", "down_", "up_")))


async def main() -> None:
    bport, fport = free_port(), free_port()
    front._cog = lambda: {"t": {"org": "t", "port": bport}}
    never: list[str] = []
    asyncio.get_running_loop().set_exception_handler(lambda _l, c: never.append(str(c.get("message"))))
    logging.getLogger("asyncio").addHandler(type("H", (logging.Handler,), {"emit": lambda s, r: never.append(r.getMessage())})())

    srv = uvicorn.Server(uvicorn.Config(front.app, host="127.0.0.1", port=fport, log_level="warning", lifespan="off"))
    async with websockets.serve(backend, "127.0.0.1", bport, process_request=process_request,
                                 select_subprotocol=lambda _c, offered: "binary" if "binary" in offered else None):
        task = asyncio.create_task(srv.serve())
        for _ in range(100):
            if srv.started:
                break
            await asyncio.sleep(0.05)
        base = f"ws://127.0.0.1:{fport}"

        async def opened(path, **kw):
            try:
                c = await websockets.connect(base + path, open_timeout=5, **kw)
                return c, None
            except websockets.InvalidStatus as e:
                return None, e.response.status_code
            except Exception as e:  # noqa: BLE001
                return None, type(e).__name__

        # 1 + 2 + 7
        SEEN.clear()
        c, err = await opened("/o/t/api/hands/desk-1/vnc?key=k1&x=2", subprotocols=["binary"],
                              additional_headers={"Cookie": "astryx_session=s; astryx_org=t", "X-Astryx-Org": "t"})
        if c is None:
            for n in ("bytes pass both ways, subprotocol echoed", "the query reaches the backend intact",
                      "no Cookie and no x-astryx-* header reach the backend"):
                arm(n, False, f"no pipe: {err}")
        else:
            await c.send(b"\x01\x02")
            got = await asyncio.wait_for(c.recv(), 5)
            arm("bytes pass both ways, subprotocol echoed", got == b"echo:\x01\x02" and c.subprotocol == "binary",
                f"{got!r} {c.subprotocol!r}")
            s = SEEN[-1] if SEEN else {"path": "", "headers": {}}
            arm("the query reaches the backend intact", s["path"] == "/api/hands/desk-1/vnc?key=k1&x=2", s["path"])
            leaked = [k for k in s["headers"] if k == "cookie" or k.startswith("x-astryx")]
            arm("no Cookie and no x-astryx-* header reach the backend", not leaked, str(leaked))
            # 5
            n0 = len(CLOSED)
            await c.close()
            for _ in range(50):
                if len(CLOSED) > n0 and pending() == 0:
                    break
                await asyncio.sleep(0.05)
            arm("a client close reaches the backend, 0 pipe tasks left", len(CLOSED) > n0 and pending() == 0,
                f"closed={CLOSED[n0:]} pending={pending()}")

        # 6
        c, err = await opened("/o/t/api/hands/desk-1/vnc?key=k1", subprotocols=["binary"])
        if c is None:
            arm("a backend close reaches the client, 0 pipe tasks left", False, f"no pipe: {err}")
        else:
            await c.send(b"bye")
            try:
                await asyncio.wait_for(c.recv(), 5)
                ended = False
            except websockets.ConnectionClosed:
                ended = True
            except asyncio.TimeoutError:
                ended = False
            for _ in range(50):
                if pending() == 0:
                    break
                await asyncio.sleep(0.05)
            arm("a backend close reaches the client, 0 pipe tasks left", ended and pending() == 0,
                f"ended={ended} pending={pending()}")

        # 3
        n0 = len(SEEN)
        c, err = await opened("/o/t/api/hands/refuse/vnc?key=bad")
        arm("a backend refusal before accept is a 403, nothing opens", c is None and err == 403, str(err))
        # 4
        c1, e1 = await opened("/o/zzz/api/hands/desk-1/vnc?key=k1")
        c2, e2 = await opened("/api/hands/desk-1/vnc?key=k1", additional_headers={"Cookie": "astryx_org=zzz"})
        c3, e3 = await opened("/api/hands/desk-1/vnc?key=k1", additional_headers={"Cookie": "astryx_org=t"})
        arm("an unknown org is a 403, by /o/ and by the chosen org; the chosen org's own pipe opens",
            c1 is None and e1 == 403 and c2 is None and e2 == 403 and c3 is not None, f"{e1} {e2} {e3}")
        if c3:
            await c3.close()
        # 8
        SEEN.clear()
        c, err = await opened("/o/t/api/hands/desk%3Fx=..%23y/vnc?key=k1")   # ? and # decoded; an encoded / never routes
        p = SEEN[-1]["path"] if SEEN else ""
        arm("an agent holding %3F stays one path segment", p == "/api/hands/desk%3Fx%3D..%23y/vnc?key=k1", p or str(err))
        if c:
            await c.close()

        await asyncio.sleep(0.2)
        gc.collect()                                 # asyncio reports an unretrieved task exception when the task is freed
        await asyncio.sleep(0)
        arm('no "Task exception was never retrieved"', not any("never retrieved" in m for m in never), str(never))
        srv.should_exit = True
        await task


asyncio.run(main())
print(f"FAIL ({len(FAILS)})" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
