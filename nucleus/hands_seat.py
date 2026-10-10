#!/usr/bin/env python3
"""astryx · hands seat — the agent's own seat on its desktop, held open as a VNC participant.

A headless sway session has no input devices, so its seat0 cannot click anything. wayvnc -t
gives every VNC client a TRANSIENT SEAT of its own: its own cursor and its own keyboard focus.
So the agent joins its desktop exactly as the owner does, as one more participant, and the two
never fight over a cursor (owner, 2026-10-10: "let it keep going with its own cursor… i want to
participate").

A seat's keyboard focus lives as long as its connection, so this process HOLDS the connection
for the life of the desktop (sway's config starts it), and takes commands on a unix socket in
the state dir, one JSON object per line:

    {"op": "pointer", "x": 10, "y": 20, "mask": 1}     RFB PointerEvent (mask bits: 1 left,
                                                       2 middle, 4 right, 8 wheel up, 16 down)
    {"op": "key", "keysym": 65293, "down": true}       RFB KeyEvent
    {"op": "ping"}
Every reply is {"ok": true} or {"ok": false, "error": "..."}.

The RFB client is the minimum the job needs (RFB 3.8, security None on loopback, shared
session). It never requests framebuffer updates; screenshots come from grim.

    venv/bin/python nucleus/hands_seat.py <port> <socket path>
"""
from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading
import time


class RFB:
    def __init__(self, host: str, port: int, timeout: float = 10):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.lock = threading.Lock()
        ver = self._recv(12)
        if not ver.startswith(b"RFB "):
            raise RuntimeError(f"not an RFB server: {ver!r}")
        self.s.sendall(b"RFB 003.008\n")
        n = self._recv(1)[0]
        if n == 0:
            raise RuntimeError("server refused: " + self._reason())
        types = self._recv(n)
        if 1 not in types:
            raise RuntimeError(f"no 'None' security type offered ({list(types)})")
        self.s.sendall(b"\x01")
        if struct.unpack(">I", self._recv(4))[0] != 0:
            raise RuntimeError("security handshake failed: " + self._reason())
        self.s.sendall(b"\x01")                    # ClientInit: shared
        w, h = struct.unpack(">HH", self._recv(4))
        self._recv(16)                              # pixel format
        name_len = struct.unpack(">I", self._recv(4))[0]
        self._recv(name_len)
        self.size = (w, h)
        self.s.settimeout(None)
        # drain whatever the server sends (bell, clipboard) so its buffer never fills
        threading.Thread(target=self._drain, daemon=True).start()

    def _recv(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("VNC server closed the connection")
            buf += chunk
        return buf

    def _reason(self) -> str:
        try:
            ln = struct.unpack(">I", self._recv(4))[0]
            return self._recv(ln).decode(errors="replace")
        except Exception:
            return "?"

    def _drain(self) -> None:
        try:
            while self.s.recv(65536):
                pass
        except OSError:
            pass
        os._exit(3)                                # the desktop is gone: so is this seat

    def pointer(self, x: int, y: int, mask: int) -> None:
        with self.lock:
            self.s.sendall(struct.pack(">BBHH", 5, mask & 0xFF, x, y))

    def key(self, keysym: int, down: bool) -> None:
        with self.lock:
            self.s.sendall(struct.pack(">BBxxI", 4, 1 if down else 0, keysym))


def serve(port: int, path: str) -> None:
    rfb = None
    for _ in range(50):                            # wayvnc may still be binding
        try:
            rfb = RFB("127.0.0.1", port)
            break
        except OSError:
            time.sleep(0.2)
    if rfb is None:
        sys.exit(f"hands seat: no VNC server on 127.0.0.1:{port}")
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    os.chmod(path, 0o600)
    srv.listen(8)

    def handle(conn: socket.socket) -> None:
        with conn, conn.makefile("rwb") as f:
            for line in f:
                try:
                    m = json.loads(line)
                    op = m.get("op")
                    if op == "pointer":
                        rfb.pointer(int(m["x"]), int(m["y"]), int(m.get("mask", 0)))
                    elif op == "key":
                        rfb.key(int(m["keysym"]), bool(m.get("down", True)))
                    elif op != "ping":
                        raise ValueError(f"unknown op {op!r}")
                    out = {"ok": True}
                except Exception as e:             # noqa: BLE001 — reported to the caller
                    out = {"ok": False, "error": str(e)[:200]}
                f.write((json.dumps(out) + "\n").encode())
                f.flush()

    while True:
        c, _ = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()


if __name__ == "__main__":
    serve(int(sys.argv[1]), sys.argv[2])
