#!/usr/bin/env python3
"""astryx · growbot healer — serial-reboot the Wi-Fi body and re-point the org.

Brit's reference firmware joins Wi-Fi at BOOT only: an overnight AP drop leaves
the chip associated to nothing, and a router re-lease moves its IP (2026-08-24:
.7 -> .2, the tab read "host down"). This is the rescue that fixed it by hand,
as a tool: soft-reboot the chip over its USB serial line (ctrl-C, ctrl-D), read
the fresh boot banner for the new IP, and rewrite GROWBOT_BODY_URL in .env —
which every consumer resolves per-call, so nothing needs a restart.

Invoked detached by triggers/steward/growbot_body_watch.py when the body stops
answering (also fine to run by hand). Exit 0 = healed (banner seen), 1 = no
serial device (body is battery-roaming or unplugged — a serial heal cannot
reach it), 2 = rebooted but no banner (wifi still down; setup mode; dead chip).
Extension law: this pokes the REPL that MicroPython itself provides — Brit's
firmware is not modified, merely restarted.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import serial

REPO = Path(__file__).resolve().parent.parent
DEV = "/dev/growbot"


def main() -> int:
    if not Path(DEV).exists():
        print("no serial device at", DEV, "— body is untethered; cannot serial-heal")
        return 1
    s = serial.Serial(DEV, 115200, timeout=1)
    s.write(b"\x03")
    time.sleep(0.5)
    s.reset_input_buffer()
    s.write(b"\x04")                      # soft reboot -> main.py -> wifi join
    t0 = time.time()
    buf = b""
    while time.time() - t0 < 45:
        c = s.read(256)
        if c:
            buf += c
            if b"ROBOT SERVER" in buf or b"SETUP MODE" in buf:
                break
    text = buf.decode(errors="replace")
    m = re.search(r"http://(\d+\.\d+\.\d+\.\d+)/", text)
    if not m:
        print("rebooted but no server banner — wifi down or setup mode:\n", text[-300:])
        return 2
    url = f"http://{m.group(1)}"
    env = REPO / ".env"
    lines = env.read_text().splitlines()
    out, seen = [], False
    for ln in lines:
        if ln.startswith("GROWBOT_BODY_URL="):
            seen = True
            if ln != f"GROWBOT_BODY_URL={url}":
                print("body moved:", ln.split("=", 1)[1], "->", url)
            ln = f"GROWBOT_BODY_URL={url}"
        out.append(ln)
    if not seen:
        out.append(f"GROWBOT_BODY_URL={url}")
    env.write_text("\n".join(out) + "\n")
    print("healed: body serving at", url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
