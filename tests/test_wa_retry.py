#!/usr/bin/env python3
"""Oracle: bridges/whatsapp.py wacli() retries ONLY transient errors, bounded (seed, after #54618/#54624: both pulse
witness rings died in the boot window, wacli's store locked and then a 429, and the owner saw neither).

    WA_SRC=<path> …   (the subject; default bridges/whatsapp.py)

  R1 store-locked, then 429, then ok → returns the output; 3 calls
  R2 a non-transient error → raised at once; 1 call (never a retry that could double-send)
  R3 transient every time → raised after the bounded retries, naming them; len(WAITS)+1 calls
  R4 ok first → 1 call

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
SUBJECT = Path(os.environ.get("WA_SRC") or REPO / "bridges" / "whatsapp.py")
os.environ["WA_WEBHOOK_SECRET"] = "oracle-secret"
os.environ["ASTRYX_DSN"] = "postgresql://oracle@127.0.0.1:1/none"   # never connected
os.environ["WA_CLI"] = "false"
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_wa_retry", REPO, deps=("fastapi", "asyncpg"), env=False)   # hermetic: never opens the DSN
import bridges  # noqa: E402,F401
spec = importlib.util.spec_from_file_location("bridges._wa_retry_subject", SUBJECT)
wa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wa)

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
  *)    echo 'error: unknown chat 123@s.whatsapp.net' >&2; exit 1;;
esac
""")
FAKE.chmod(0o755)
wa.WA_CLI = [str(FAKE)]
wa.WACLI_RETRY_WAITS = (0, 0, 0)


def run(seq):
    (TD / "n").unlink(missing_ok=True)
    os.environ["WA_FAKE_SEQ"], os.environ["WA_FAKE_DIR"] = seq, str(TD)
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
check("R3 ...naming the bounded retries", err and f"after {len(wa.WACLI_RETRY_WAITS)} transient retries" in err, err)
check("R3 ...in len(WAITS)+1 calls", n == len(wa.WACLI_RETRY_WAITS) + 1, n)
out, err, n = run("ok")
check("R4 ok first → 1 call", out and n == 1, (out, n))

print(f"\n{'FAIL' if fails else 'PASS'}: wacli retries only transient errors, bounded ({len(fails)} failing)")
sys.exit(1 if fails else 0)
