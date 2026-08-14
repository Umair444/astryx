#!/usr/bin/env python3
"""Oracle for triggers/scout/card_address_drift.py — OBSERVABILITY, not drift logic.

THE ONE PROPERTY UNDER TEST: can this guard's own persisted state distinguish
"observed, all clear" from "could not observe"? Reproduced RED against the shipped version
on 2026-08-14 — its entire state was `{"echo_i": 2}`, a rotation counter incremented BEFORE
the fetch, so it advanced identically whether the comparison succeeded or every authority was
down. A guard whose silence is uninterpretable is a guard that cannot be audited, including
by the person who wrote it, and this one has no other oracle at all.

Deliberately narrow. The drift/confirmation/re-nag logic is NOT retested here — that behaviour
is unchanged and untouched, and a broad suite bolted on to justify a small edit is how an
oracle becomes something nobody runs. This asserts the property the edit is FOR.

Run by nucleus/check.sh. Exits 77 (SKIP, not PASS) when the gitignored body is absent.
"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BODY = REPO / "triggers/scout/card_address_drift.py"
EXIT_SKIP = 77

if not BODY.exists():
    print(f"SKIP: {BODY} absent (gitignored trigger body) — nothing verified here.")
    sys.exit(EXIT_SKIP)

sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location("card_address_drift", BODY)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

UTC = timezone.utc
NOW = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
IP = "182.180.56.152"
fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        got:  {got!r}\n        want: {want!r}")
        fails.append(label)


class Ctx:
    """Minimal ctx: the trigger uses only .state and .http."""

    def __init__(self, echo):
        self.state = {}
        self._echo = echo

    def http(self, url):
        r = self._echo(url)
        if isinstance(r, Exception):
            raise r
        return r


mod._now = lambda: NOW
mod._env = lambda k: f"http://{IP}:8845" if k == "ASTRYX_URL" else ""

print("THE PROPERTY: silence must be interpretable from the state alone.\n")

print("HEALTHY — the address agrees with the authority:")
c_ok = Ctx(lambda u: IP)
check("stays silent (correct: nothing is wrong)", mod.card_address_drift(c_ok), None)
check("...and RECORDS that it successfully observed", "last_ok" in c_ok.state, True)
check("...with the value it confirmed", c_ok.state.get("last_ok", {}).get("ip"), IP)
check("...and which authority confirmed it",
      c_ok.state.get("last_ok", {}).get("authority") in mod.ECHOES, True)

print("\nBLIND — every authority is unreachable:")
c_down = Ctx(lambda u: OSError("echo down"))
check("stays silent (it has no observation to report)", mod.card_address_drift(c_down), None)
check("...and records NO successful observation", "last_ok" in c_down.state, False)

print("\nBLIND — an authority answers, but with a captive-portal page, not an IP:")
c_junk = Ctx(lambda u: "<html>Sign in to continue</html>")
check("stays silent", mod.card_address_drift(c_junk), None)
check("...and records NO successful observation", "last_ok" in c_junk.state, False)

print("\nTHE DISCRIMINATOR — the two silences must not look alike:")
check("healthy silence and blind silence differ in the state",
      ("last_ok" in c_ok.state) != ("last_ok" in c_down.state), True)
print("  INVERSION — the shipped version's only state key cannot tell them apart:")
check("echo_i advances identically on the healthy and the blind path",
      c_ok.state.get("echo_i") == c_down.state.get("echo_i"), True)

print("\nSTALENESS IS DERIVABLE — an auditor can date the last real observation:")
c_ok2 = Ctx(lambda u: IP)
mod._now = lambda: NOW + timedelta(days=9)
mod.card_address_drift(c_ok2)
seen = datetime.fromisoformat(c_ok2.state["last_ok"]["at"])
check("last_ok carries a parseable timestamp", seen, NOW + timedelta(days=9))
mod._now = lambda: NOW

print("\nNO REGRESSION — the drift path still fires, and still on two agreeing authorities:")
NEW = "203.0.113.7"
seq = iter(mod.ECHOES)
c_drift = Ctx(lambda u: NEW)
check("first divergent reading holds (one authority is not evidence)",
      mod.card_address_drift(c_drift), None)
check("...and does NOT claim a successful observation of the configured address",
      c_drift.state.get("last_ok", {}).get("ip"), NEW)
out = mod.card_address_drift(c_drift)
check("a second, different authority agreeing fires the alarm",
      out is not None and "CARD ADDRESS STALE" in out, True)
check("...naming the real address", NEW in (out or ""), True)

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
