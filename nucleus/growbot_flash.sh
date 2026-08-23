#!/usr/bin/env bash
# astryx · growbot flasher — put the body firmware on the Pico.
# Usage: nucleus/growbot_flash.sh [serial-dev]      (default /dev/growbot)
#
# Prereq once: flash stock MicroPython for RP2040 (drag the .uf2 from
# micropython.org/download/RPI_PICO onto the BOOTSEL drive). Then this copies
# nucleus/growbot_firmware.py onto the chip as main.py — it runs at every
# power-on, and astryx-growbot.service talks to it over this same port.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV="${1:-/dev/growbot}"
[ -e "$DEV" ] || { echo "no board at $DEV (BOOTSEL mode? unplugged? pass the device as arg 1)"; exit 1; }
# the body host holds the port open — release it for the copy, restore after
systemctl is-active --quiet astryx-growbot && { RESTART=1; sudo systemctl stop astryx-growbot; } || RESTART=0
"$ROOT/venv/bin/mpremote" connect "$DEV" cp "$ROOT/nucleus/growbot_firmware.py" :main.py
"$ROOT/venv/bin/mpremote" connect "$DEV" reset || true   # reset drops the link by design
[ "$RESTART" = 1 ] && sudo systemctl start astryx-growbot
echo "flashed: growbot_firmware.py -> $DEV as main.py (boot-limp; wiggle it via the GrowBot tab)"
