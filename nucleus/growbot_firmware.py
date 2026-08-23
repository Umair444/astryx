"""astryx · growbot serial body firmware — runs ON the Pico as main.py.

The USB-serial GrowBot body: a plain RP2040 Pico (no Wi-Fi, no carrier board)
driving two MG90S/SG90 servos straight off GP0/GP1. The host (nucleus/
growbot_body.py) speaks the open GrowBot protocol to the world and streams
interpolated poses down this wire at ~50 Hz; the chip stays deliberately dumb —
apply the latest pose, go limp when told or when the line goes quiet.

Line protocol over USB CDC (115200, newline-terminated):
  P <l>,<r>   pose in absolute degrees (float ok); either side empty = hold
  R           release both servos (limp: no pulse, no torque, cool + silent)
  S           -> one JSON stats line {"rx":N,"deadman":N,"posed":bool,"up_s":N}
  ?           -> "growbot-serial v1 rp2040"

Safety, engine-owned (the GrowBot contract, PROTOCOL.md §3):
  boot-limp   servos never move on power-up; duty stays 0 until the first P
  dead-man    500 ms without a P line -> limp (the host heartbeats poses,
              so a healthy link never trips this)

Wiring (BUILD.md): left signal->GP0, right signal->GP1, both reds->battery +
(VBUS pin 40 is fine on the bench), all grounds tied together.

Flash: nucleus/growbot_flash.sh — or by hand:
  venv/bin/mpremote connect /dev/growbot cp nucleus/growbot_firmware.py :main.py
"""
import sys
import time
import select
import json
from machine import Pin, PWM

L_GP, R_GP = 0, 1                  # left leg = GP0, right leg = GP1
FREQ = 50                          # 20 ms servo frame
MIN_US, MAX_US = 500, 2500         # 0.5 ms = 0deg .. 2.5 ms = 180deg
PERIOD_US = 1_000_000 // FREQ
DEADMAN_MS = 500

try:
    led = Pin("LED", Pin.OUT)
except Exception:
    led = None


def _duty(deg):
    deg = 0.0 if deg < 0 else 180.0 if deg > 180 else deg
    us = MIN_US + (MAX_US - MIN_US) * deg / 180
    return int(us / PERIOD_US * 65535)


class Body:
    def __init__(self):
        self.pwm = {}
        for gp in (L_GP, R_GP):
            p = PWM(Pin(gp))
            p.freq(FREQ)
            p.duty_u16(0)          # boot-limp: no pulse until the first pose
            self.pwm[gp] = p
        self.posed = False

    def pose(self, l, r):
        if l is not None:
            self.pwm[L_GP].duty_u16(_duty(l))
        if r is not None:
            self.pwm[R_GP].duty_u16(_duty(r))
        self.posed = True
        if led:
            led.on()

    def release(self):
        for p in self.pwm.values():
            p.duty_u16(0)
        self.posed = False
        if led:
            led.off()


body = Body()
poller = select.poll()
poller.register(sys.stdin, select.POLLIN)
stats = {"rx": 0, "deadman": 0}
last_pose = None
t0 = time.ticks_ms()
print("growbot-serial v1 rp2040")

while True:
    if poller.poll(20):
        line = sys.stdin.readline()
        if not line:
            continue
        line = line.strip()
        if line.startswith("P"):
            try:
                ls, _, rs = line[1:].strip().partition(",")
                l = float(ls) if ls else None
                r = float(rs) if rs else None
            except ValueError:
                continue
            body.pose(l, r)
            stats["rx"] += 1
            last_pose = time.ticks_ms()
        elif line == "R":
            body.release()
            last_pose = None
        elif line == "S":
            print(json.dumps({"rx": stats["rx"], "deadman": stats["deadman"],
                              "posed": body.posed,
                              "up_s": time.ticks_diff(time.ticks_ms(), t0) // 1000}))
        elif line == "?":
            print("growbot-serial v1 rp2040")
    if body.posed and last_pose is not None and \
            time.ticks_diff(time.ticks_ms(), last_pose) > DEADMAN_MS:
        body.release()             # the host went quiet mid-motion -> limp
        last_pose = None
        stats["deadman"] += 1
