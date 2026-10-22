#!/usr/bin/env python3
"""Oracle: every wacli call retries ONLY transient errors, bounded (seed, after #54618/#54624: both pulse witness
rings died in the boot window, wacli's store locked and then a 429, and the owner saw neither). The retry is ONE
implementation, bridges/providers/whatsapp.py run_wacli(); the bridge's wacli() and the provider's send() (the path a
text message, the witness's ring included, actually takes: steward #62329) both go through it.

    WA_PROVIDER_SRC=<path> …   (the subject; default bridges/providers/whatsapp.py)

  R1 store-locked, then 429, then ok → returns the output; 3 calls
  R2 a non-transient error → raised at once; 1 call (never a retry that could double-send)
  R3 transient every time → raised after the bounded retries, naming them; len(WAITS)+1 calls
  R4 ok first → 1 call
  R5 a warmup-429 WARNING then a send timeout → raised after 1 call (the last stderr line decides)
  R6 a warning then a transient last line → retried
  R7 PROVIDER.send (a text message's path): store-locked, then 429, then ok → ok, in 3 calls
  R8 PROVIDER.send, transient every time → ok=False naming the bounded retries, in len(WAITS)+1 calls
  R9 PROVIDER.send, a non-transient error → ok=False after 1 call
  R10 the shipped waits sum past the measured boot store lock (BOOT_LOCK_MEASURED_S, 10-22)

Hermetic: no DB, no wacli, no network. A fake WA_CLI script plays a scripted sequence of outcomes and counts its calls.
"""
import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
SUBJECT = Path(os.environ.get("WA_PROVIDER_SRC") or REPO / "bridges" / "providers" / "whatsapp.py")
os.environ["WA_WEBHOOK_SECRET"] = "oracle-secret"
os.environ["ASTRYX_DSN"] = "postgresql://oracle@127.0.0.1:1/none"   # never connected
os.environ["WA_CLI"] = "false"
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_wa_retry", REPO, deps=("fastapi", "asyncpg"), env=False)   # hermetic: never opens the DSN
import bridges.providers  # noqa: E402,F401
# the subject stands in for the provider module itself, so the bridge's own import of it gets the subject too
spec = importlib.util.spec_from_file_location("bridges.providers.whatsapp", SUBJECT)
prov = importlib.util.module_from_spec(spec)
sys.modules["bridges.providers.whatsapp"] = prov
spec.loader.exec_module(prov)
import bridges.whatsapp as wa  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


TD = Path(tempfile.mkdtemp(prefix="wa-retry-"))
FAKE = TD / "wacli"
FAKE.write_text("""#!/bin/sh
n=$(cat "$WA_FAKE_DIR/n" 2>/dev/null || echo 0); n=$((n + 1)); echo $n > "$WA_FAKE_DIR/n"
step=$(echo "$WA_FAKE_SEQ" | cut -d, -f$n); [ -z "$step" ] && step=$(echo "$WA_FAKE_SEQ" | awk -F, '{print $NF}')
case "$step" in
  ok)   echo '{"sent":true}'; exit 0;;
  lock) echo 'error: store is locked (another wacli is running?)' >&2; exit 1;;
  429)  echo 'error: info query returned status 429: rate-overlimit' >&2; exit 1;;
  warntimeout) echo 'warn: send warmup for 123@s.whatsapp.net failed (send will proceed): info query returned status 429: rate-overlimit' >&2
        echo 'Error: send timed out after 45s' >&2; exit 1;;
  warnlock) echo 'warn: send warmup for 123@s.whatsapp.net failed (send will proceed): info query returned status 429: rate-overlimit' >&2
        echo 'error: store is locked (another wacli is running?)' >&2; exit 1;;
  *)    echo 'error: unknown chat 123@s.whatsapp.net' >&2; exit 1;;
esac
""")
FAKE.chmod(0o755)
wa.WA_CLI = [str(FAKE)]
wa.PROVIDER._cmd = [str(FAKE)]
SHIPPED_WAITS = tuple(prov.WACLI_RETRY_WAITS)            # read BEFORE zeroing: R10 grades the values, not the length
prov.WACLI_RETRY_WAITS = (0,) * len(prov.WACLI_RETRY_WAITS)
# The boot store lock, measured 10-22: taken 14:03:21Z (the DOWN ring's error names it), and the bridge's own wacli
# call through it succeeded at 14:03:54Z after 3 retries (journal). 10-15's waits summed ~22 s, under it (a3 #62372).
BOOT_LOCK_MEASURED_S = 33


def arm_fake(seq):
    (TD / "n").unlink(missing_ok=True)
    os.environ["WA_FAKE_SEQ"], os.environ["WA_FAKE_DIR"] = seq, str(TD)


def run(seq):
    arm_fake(seq)
    try:
        out, err = asyncio.run(wa.wacli("send", "text")), None
    except RuntimeError as e:
        out, err = None, str(e)
    return out, err, int((TD / "n").read_text())


out, err, n = run("lock,429,ok")
check("R1 store-locked, then 429, then ok → delivered", out and '"sent":true' in out, err)
check("R1 ...in exactly 3 calls", n == 3, n)
out, err, n = run("unknown")
check("R2 a non-transient error is raised at once", err and "unknown chat" in err, out)
check("R2 ...after 1 call (never retried)", n == 1, n)
out, err, n = run("lock")
check("R3 transient every time → raised", err and "store is locked" in err, out)
check("R3 ...naming the bounded retries", err and f"after {len(prov.WACLI_RETRY_WAITS)} transient retries" in err, err)
check("R3 ...in len(WAITS)+1 calls", n == len(prov.WACLI_RETRY_WAITS) + 1, n)
out, err, n = run("ok")
check("R4 ok first → 1 call", out and n == 1, (out, n))
# a3 #54634: wacli prints a 429 as a WARNING before a send that proceeds; a timeout after it may be a delivered message
out, err, n = run("warntimeout,ok")
check("R5 a warmup-429 WARNING then 'send timed out' → raised, never retried (no double send)",
      err and "send timed out after 45s" in err, out)
check("R5 ...after 1 call", n == 1, n)
check("R5 ...the raised text is the real error, not the warning", err and "warmup" not in err, err)
out, err, n = run("warnlock,ok")
check("R6 a warmup warning then a transient LAST line (store locked) → still retried", out and n == 2, (out, err, n))


def send(seq):
    arm_fake(seq)
    res = asyncio.run(wa.PROVIDER.send("123@s.whatsapp.net", "the clock is DOWN"))
    return res, int((TD / "n").read_text())


# the witness's ring is a wire row deliver() sends through PROVIDER.send: the 10-15 fix never reached it (#62329)
res, n = send("lock,429,ok")
check("R7 PROVIDER.send: store-locked, then 429, then ok → ok", res.ok, res.error)
check("R7 ...in exactly 3 calls", n == 3, n)
res, n = send("lock")
check("R8 PROVIDER.send, transient every time → ok=False, naming the bounded retries",
      not res.ok and f"after {len(prov.WACLI_RETRY_WAITS)} transient retries" in (res.error or ""), res.error)
check("R8 ...in len(WAITS)+1 calls", n == len(prov.WACLI_RETRY_WAITS) + 1, n)
res, n = send("unknown")
check("R9 PROVIDER.send, a non-transient error → ok=False after 1 call", not res.ok and n == 1, (res.error, n))
check(f"R10 the shipped waits sum past the measured boot store lock ({BOOT_LOCK_MEASURED_S} s, 10-22)",
      sum(SHIPPED_WAITS) > BOOT_LOCK_MEASURED_S, SHIPPED_WAITS)

print(f"\n{'FAIL' if fails else 'PASS'}: wacli retries only transient errors, bounded ({len(fails)} failing)")
sys.exit(1 if fails else 0)
