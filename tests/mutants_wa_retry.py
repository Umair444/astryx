"""Authored mutants for bridges/whatsapp.py wacli()'s transient retry (tests/test_wa_retry.py)."""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "bridges" / "whatsapp.py"
ORACLE = REPO / "tests" / "test_wa_retry.py"
ENV = "WA_SRC"
TIMEOUT = 120

MUTANTS = {
    "retries EVERY error (a real failure could double-send)":
        ("if wait is None or not WACLI_TRANSIENT.search(msg):", "if wait is None:"),
    "never retries (the boot-window rings die again)":
        ("for attempt, wait in enumerate((*WACLI_RETRY_WAITS, None)):", "for attempt, wait in enumerate((None,)):"),
    "unbounded (retries past the last wait)":
        ("if wait is None or not WACLI_TRANSIENT.search(msg):", "if not WACLI_TRANSIENT.search(msg) and wait is not None:"),
}
