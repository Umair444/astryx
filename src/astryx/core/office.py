"""Office documents as a PDF, so they read exactly as authored: the ONE converter canvas's /api/file/preview and the
chat workspace's /api/chat/preview share (owner 11-13: "all the office stuff should be visible … following the old
viewer standards", the standard being canvas's). LibreOffice, headless, with its own throwaway profile per run, one
conversion at a time (it is heavy and a shared profile corrupts), cached by the file's content hash, so a document is
converted once however often it is opened. The PDF is then served by security.serve.serve_untrusted like any other
untrusted bytes, and the page draws it with pdf.js: nothing from the document is ever parsed into the page."""
from __future__ import annotations

import asyncio
import hashlib
import shutil
import tempfile
from pathlib import Path

OFFICE_TYPES = {".docx", ".doc", ".odt", ".rtf", ".pptx", ".ppt", ".odp", ".xlsx", ".xls", ".ods"}
TIMEOUT = 120
_lock = asyncio.Lock()


class Unavailable(Exception):
    """A conversion that can't happen: (http status, the words for it)."""
    def __init__(self, status: int, why: str):
        super().__init__(why)
        self.status, self.why = status, why


async def to_pdf(path: Path, cache: Path) -> Path:
    """The PDF of Office document `path`, converted once into `cache` (named by content hash). Raises Unavailable."""
    if path.suffix.lower() not in OFFICE_TYPES:
        raise Unavailable(415, "no preview for this type")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:32]
    out = cache / f"{digest}.pdf"
    if out.is_file():
        return out
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise Unavailable(501, "LibreOffice is not installed on this host")
    async with _lock:
        if out.is_file():
            return out
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / f"doc{path.suffix.lower()}"
            shutil.copyfile(path, src)
            proc = await asyncio.create_subprocess_exec(
                soffice, f"-env:UserInstallation=file://{tmp}/profile", "--headless", "--norestore",
                "--convert-to", "pdf", "--outdir", tmp, str(src),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            try:
                await asyncio.wait_for(proc.wait(), TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                raise Unavailable(504, "the document took too long to render") from None
            made = Path(tmp) / "doc.pdf"
            if not made.is_file():
                raise Unavailable(422, "this document could not be rendered")
            shutil.move(str(made), out)
    return out
