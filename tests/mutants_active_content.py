"""Authored mutants for the server half of tests/test_active_content.py (plan-11859 D6): bridges/canvas.py serving an
agent-authored file so that it could run on the front's origin. Every one must be CAUGHT.
(The CLIENT rules are a census over the web trees; their fixture arms are their controls.)

    venv/bin/python devtools/mutation_probe.py tests/mutants_active_content.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "bridges" / "canvas.py"
ORACLE = REPO / "tests" / "test_active_content.py"
ENV = "ACTIVE_CANVAS_SRC"

MUTANTS = {
    "A1 an SVG is served inline with its guessed type (an agent's script runs on the owner key's origin)":
        ('INLINE_TYPES = {".pdf", ', 'INLINE_TYPES = {".svg", ".pdf", '),
    # plan-11884 G3: the branches now answer through serve_untrusted; each mutant is a branch that slips past it
    "A2 the download branch bypasses serve_untrusted (a bare FileResponse, nosniff only)":
        ("    return serve_untrusted(path, inline=False)",
         '    return FileResponse(path, filename=path.name, headers={"X-Content-Type-Options": "nosniff"})'),
    "A4 TEXT_TYPES are served with their guessed type, outside serve_untrusted":
        ("    if inline and (ext in TEXT_TYPES or ext in INLINE_TYPES):",
         '    if inline and ext in TEXT_TYPES:\n        return FileResponse(path, content_disposition_type="inline", '
         'headers={"X-Content-Type-Options": "nosniff"})\n    if inline and (ext in TEXT_TYPES or ext in INLINE_TYPES):'),
}
