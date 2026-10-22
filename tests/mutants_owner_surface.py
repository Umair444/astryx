"""Authored mutants for the owner-surface census (tests/test_owner_surface.py, plan-11884 G2/G3), each applied to
observatory/api/main.py: a proxy whose upstream stops being declared (so its module would silently leave the domain),
a new writer of the wire, and a second hand-written server of bytes.

    venv/bin/python devtools/mutation_probe.py tests/mutants_owner_surface.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "observatory" / "api" / "main.py"
ORACLE = REPO / "tests" / "test_owner_surface.py"
ENV = "SURFACE_MAIN_SRC"

MUTANTS = {
    "O1 the /ear proxy's upstream is a literal, not a declared unit (ear.py would drop out of the domain)":
        ('EAR_UP = _upstream("astryx-ear", 8092)', 'EAR_UP = "http://127.0.0.1:8092"'),
    "O2 growbot's body is reached by a literal port (a2 #62292's growbot form)":
        ("orgs.port('astryx-growbot') or 8470", "8470"),
    "O3 a new INSERT INTO messages path":
        ('@app.post("/api/thread/read")',
         'async def sneak(p):\n    await p.execute("INSERT INTO messages (body) VALUES ($1)", "x")\n\n\n@app.post("/api/thread/read")'),
    "O4 a second hand-written server of bytes":
        ('@app.post("/api/thread/read")',
         'def sneak_file(p):\n    return FileResponse(p)\n\n\n@app.post("/api/thread/read")'),
    "O5 the owner_send writer is renamed (the expected set is exact, not a floor)":
        ("async def owner_send(", "async def owner_send_v2("),
}
