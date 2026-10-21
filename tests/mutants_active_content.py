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
    "A2 the download branch drops its CSP sandbox":
        ('                                                           "Content-Security-Policy": "sandbox"})',
         '                                                           })'),
    "A3 the download branch drops nosniff":
        ('    return FileResponse(path, filename=path.name, headers={"X-Content-Type-Options": "nosniff",',
         '    return FileResponse(path, filename=path.name, headers={'),
    "A4 TEXT_TYPES are served with their guessed type, not text/plain":
        ('        return FileResponse(path, media_type="text/plain; charset=utf-8", content_disposition_type="inline",',
         '        return FileResponse(path, content_disposition_type="inline",'),
}
