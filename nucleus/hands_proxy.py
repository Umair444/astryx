#!/usr/bin/env python3
"""astryx · hands proxy — the agent's own browser reaches the internet, never this machine or the LAN.

An agent's own browser loads outside pages, and any page can fire GETs (img, form) at
unauthenticated services on this host or the home network (e.g. senses on :8460 turns ?focus=1
into a wire row). Chromium never sends loopback through a PAC script, so the fence is this
proxy, which chromium uses for EVERYTHING (--proxy-bypass-list=<-loopback>):

    it resolves the destination ITSELF, refuses loopback / private / link-local / CGNAT /
    unspecified addresses, and connects to the very IP it checked, so a public name re-pointed at
    a private address is refused too. Only 127.0.0.1:<port> for ports named in HANDS_LOCAL_ALLOW
    passes (default 8006, the Windows VM's viewer).

(a3 #42085 F1.) The owner's REAL browser, on his laptop, is his own and is not proxied.

    venv/bin/python nucleus/hands_proxy.py <listen port>
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import sys

ALLOW = {int(p) for p in (os.environ.get("HANDS_LOCAL_ALLOW") or "8006").split(",") if p.isdigit()}
DENIED = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
BAD = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"


def blocked(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return (a.is_loopback or a.is_private or a.is_link_local or a.is_unspecified
            or a.is_multicast or a.is_reserved
            or (isinstance(a, ipaddress.IPv4Address) and a in ipaddress.ip_network("100.64.0.0/10")))


async def resolve(host: str, port: int) -> str | None:
    """The address to connect to, or None when it's fenced off."""
    if host in ("127.0.0.1", "localhost") and port in ALLOW:
        return "127.0.0.1"
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return None
    ips = [i[4][0] for i in infos]
    if not ips or any(blocked(ip) for ip in ips):
        return None
    return ips[0]


def split_hostport(hp: str, default: int) -> tuple[str, int]:
    if hp.startswith("["):
        host, _, rest = hp[1:].partition("]")
        return host, int(rest[1:]) if rest.startswith(":") else default
    host, _, port = hp.rpartition(":") if hp.count(":") == 1 else (hp, "", "")
    return (host, int(port)) if port.isdigit() else (hp, default)


async def pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
    try:
        while data := await r.read(65536):
            w.write(data)
            await w.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            w.close()
        except Exception:  # noqa: BLE001
            pass


async def handle(cr: asyncio.StreamReader, cw: asyncio.StreamWriter) -> None:
    try:
        head = await asyncio.wait_for(cr.readuntil(b"\r\n\r\n"), 30)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError,
            ConnectionError):
        cw.close()
        return
    line, _, rest = head.partition(b"\r\n")
    try:
        method, target, version = line.decode("latin-1").split(" ", 2)
    except ValueError:
        cw.write(BAD)
        cw.close()
        return
    if method == "CONNECT":
        host, port = split_hostport(target, 443)
        out_head = b""
    else:
        if not target.startswith("http://"):
            cw.write(BAD)
            cw.close()
            return
        hp, _, path = target[7:].partition("/")
        host, port = split_hostport(hp, 80)
        # origin-form, and one request per connection so a reused socket can't switch hosts
        headers = [h for h in rest.split(b"\r\n") if h and not h.lower().startswith(
            (b"proxy-connection:", b"connection:", b"keep-alive:"))]
        out_head = (f"{method} /{path} {version}\r\n".encode("latin-1")
                    + b"\r\n".join(headers) + b"\r\nConnection: close\r\n\r\n")
    ip = await resolve(host, port)
    if ip is None:
        cw.write(DENIED)
        await cw.drain()
        cw.close()
        return
    try:
        ur, uw = await asyncio.wait_for(asyncio.open_connection(ip, port), 15)
    except (OSError, asyncio.TimeoutError):
        cw.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        cw.close()
        return
    if method == "CONNECT":
        cw.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await cw.drain()
    else:
        uw.write(out_head)
        await uw.drain()
    await asyncio.gather(pipe(cr, uw), pipe(ur, cw))


async def main(port: int) -> None:
    srv = await asyncio.start_server(handle, "127.0.0.1", port, limit=1 << 16)
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1])))
