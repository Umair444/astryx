"""Authored mutants for src/astryx/security/serve.py, serve_untrusted, the ONE server of untrusted bytes (plan-11884 G3),
judged by its behaviour through /api/chat/file (tests/test_chat_api.py, SERVE_SRC).

    venv/bin/python devtools/mutation_probe.py tests/mutants_serve_untrusted.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "security" / "serve.py"
ORACLE = REPO / "tests" / "test_chat_api.py"
ENV = "SERVE_SRC"

MUTANTS = {
    "V1 the CSP sandbox is dropped":
        ('headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": CSP, "Cache-Control": "no-store"}',
         'headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}'),
    "V2 nosniff is dropped":
        ('headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": CSP, "Cache-Control": "no-store"}',
         'headers = {"Content-Security-Policy": CSP, "Cache-Control": "no-store"}'),
    "V3 frame_pdf drops the sandbox for ANY type, not only a magic-verified PDF":
        ('if frame_pdf and kind == "application/pdf":', "if frame_pdf:"),
    "V4 bytes off the allowlist are served inline, not as an attachment":
        ("    if kind and inline:", "    if inline:"),
    "V5 markup is typed as a page, not as text":
        ('        return "text/plain; charset=utf-8"\n    return None', '        return "text/html; charset=utf-8"\n    return None'),
}
