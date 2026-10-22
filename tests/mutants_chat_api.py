"""Authored mutants for observatory/api/chat.py (plan-11884 R2/R3/R5/R6), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_chat_api.py

Each is a plausible way the server half breaks while it still looks right: the side panel's path judge loses one of
its refusals, the upload loses a bound, the projects writer stops being the one careful writer, or dictation mints
without asking whether it may.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "observatory" / "api" / "chat.py"
ORACLE = REPO / "tests" / "test_chat_api.py"
ENV = "CHAT_SRC"

MUTANTS = {
    "F1 the path is not resolved (no symlink or '..' normalising)":
        ("p = Path(raw).resolve(strict=True)", "p = Path(raw)"),
    "F2 a dot-path inside a home is served":
        ("return None if any(x.startswith(\".\") for x in rel) or p.name.endswith(\".env\") else p",
         "return None if p.name.endswith(\".env\") else p"),
    "F3 an .env file is served":
        ("return None if any(x.startswith(\".\") for x in rel) or p.name.endswith(\".env\") else p",
         "return None if any(x.startswith(\".\") for x in rel) else p"),
    "F4 an agent's page is served as a page":
        ('UPLOAD_TYPES.get(p.suffix.lower(), "text/plain; charset=utf-8")', 'UPLOAD_TYPES.get(p.suffix.lower(), "text/html")'),
    "F5 the NUL guard is dropped":
        ('if not raw or "\\x00" in raw:', "if not raw:"),
    "U1 any type is accepted":
        ("if ext not in UPLOAD_TYPES:", "if False:"),
    "U2 no size cap":
        ("if len(data) > MAX_UPLOAD:", "if False:"),
    "U3 no random token in the stored name":
        ('f"chat-{secrets.token_hex(12)}-{clean}"', 'f"chat-{clean}"'),
    "U4 the name is not sanitized":
        ('stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name or "file").name).strip(".-") or "file"', 'stem = name or "file"'),
    "P1 If-Match is optional":
        ("if tag is None:", "if False:"),
    "P2 a stale writer wins":
        ("new = atomic_write(projects_file(), text, if_match=tag)", "new = atomic_write(projects_file(), text, if_match=None)"),
    "P3 projects are not validated":
        ("why = _valid(body)", 'why = ""'),
    "D1 dictation mints without asking whether it may":
        ("why = await V.unavailable(pool)", 'why = ""'),
}
