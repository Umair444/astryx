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
    "F5 the NUL guard is dropped":
        ('if not raw or "\\x00" in raw:', "if not raw:"),
    "K1 (D1) a ?key= authenticates the file route again":
        ('    if "key" in request.query_params:\n        return Response(status_code=403)\n', ""),
    "U1 (D3) the bytes don't decide: anything is accepted as text":
        ("kind = sniff(data[:4096])", 'kind = sniff(data[:4096]) or "text/plain; charset=utf-8"'),
    "U2 no size cap":
        ("if len(data) > MAX_UPLOAD:", "if False:"),
    "U3 (D3) the stored name is the client's, not server-minted":
        ('dest = MEDIA / "upload" / f"{uuid.uuid4().hex}{EXT[kind]}"', 'dest = MEDIA / "upload" / safe_name(name)'),
    "U4 the display name is not sanitized":
        ('stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name or "file").name).strip(".-") or "file"', 'stem = name or "file"'),
    "P1 If-Match is optional":
        ("if tag is None:", "if False:"),
    "P2 a stale writer wins":
        ("new = atomic_write(projects_file(), text, if_match=tag)", "new = atomic_write(projects_file(), text, if_match=None)"),
    "P3 projects are not validated":
        ("why = _valid(body)", 'why = ""'),
    "P4 (D6') a read doesn't check the roster":
        ('"missing": [a for a in p.get("agents", []) if a not in live]', '"missing": []'),
    "W1 (D4, a3) a turn is filed by input_msg_id only":
        ("ids AS (SELECT DISTINCT turn_id AS id FROM messages WHERE thread = $1 AND turn_id IS NOT NULL\n"
         "                        UNION SELECT id FROM turns WHERE input_msg_id IN (SELECT id FROM th))",
         "ids AS (SELECT id FROM turns WHERE input_msg_id IN (SELECT id FROM th))"),
    "W2 (D4) never-linked steps are dropped, not counted":
        ('unlinked[a] = (await pool.fetchrow(', 'unlinked[a] = 0 and (await pool.fetchrow('),
    "W3 (D4) the done-marks are shown as work":
        ('QUIET = ("tool_done", "heartbeat", "response")', 'QUIET = ("heartbeat",)'),
    "D1 dictation mints without asking whether it may":
        ("why = await V.unavailable(pool)", 'why = ""'),
}
