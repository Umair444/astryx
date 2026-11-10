"""Authored mutants for the one wacli transient retry, bridges/providers/whatsapp.py run_wacli() (tests/test_wa_retry.py)."""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "bridges" / "providers" / "whatsapp.py"
ORACLE = REPO / "tests" / "test_wa_retry.py"
ENV = "WA_PROVIDER_SRC"
TIMEOUT = 120

MUTANTS = {
    "retries EVERY error (a real failure could double-send)":
        ("if wait is None or not WACLI_TRANSIENT.search(msg):", "if wait is None:"),
    "never retries (the boot-window rings die again)":
        ("for attempt, wait in enumerate((*WACLI_RETRY_WAITS, None)):", "for attempt, wait in enumerate((None,)):"),
    "the provider's send bypasses the retry (the 10-15 fix that never reached a text send, #62329)":
        ("        return await run_wacli(self._cmd, *args)",
         "        proc = await asyncio.create_subprocess_exec(*self._cmd, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)\n        out, err = await proc.communicate()\n        if proc.returncode:\n            raise RuntimeError(err.decode())\n        return out.decode()"),
    "the 10-15 budget (~22 s) under the measured ~33 s boot lock: the DOWN ring dies again (a3 #62372 R1)":
        ("WACLI_RETRY_WAITS = (2, 5, 15, 30)", "WACLI_RETRY_WAITS = (2, 5, 15)"),
    "unbounded (retries past the last wait)":
        ("if wait is None or not WACLI_TRANSIENT.search(msg):", "if not WACLI_TRANSIENT.search(msg) and wait is not None:"),
    "classifies the WHOLE stderr (a warmup-429 warning makes a send timeout retry: double send, a3 #54634)":
        ('msg = (err.decode(errors="replace").strip().splitlines() or [""])[-1][:200]',
         'msg = err.decode(errors="replace").strip()[:200]'),
}
