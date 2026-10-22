"""serve_untrusted: the ONE way a file nobody on this org vouches for reaches a browser (plan-11884 G3, a4 #62268).

The owner's origin holds the owner key (observatory/web/src/api.ts keeps it in localStorage), so a byte stream a
stranger or an agent authored must never be INTERPRETED there as a document. Every route that serves such a file (the
observatory's /api/chat/file, canvas's /api/file and /api/file/preview) answers through this function, and
tests/test_owner_surface.py holds the census: no other FileResponse of a non-build file in the owner-origin domain.

THE RULE. The type is SNIFFED from the bytes, never taken from a filename:
  - an allowlisted passive type is served as itself: png, jpeg, gif, webp, avif, pdf, and the media containers
    (mp4/m4a/mov, webm, ogg, mp3, wav, flac), which a browser plays and never runs;
  - valid UTF-8 text (no NUL) asked for INLINE is served as text/plain: SHOWN, never parsed. An agent's .html or .svg
    is therefore a page of characters, not a document (nosniff + the sandbox keep it so);
  - only an ATTACHMENT, or bytes off the allowlist, is application/octet-stream with Content-Disposition: attachment;
  - ALWAYS X-Content-Type-Options: nosniff and Content-Security-Policy: sandbox; default-src 'none'.
ONE NAMED EXEMPTION, `frame_pdf` (canvas's in-page PDF viewer only, canvas/web/src/Media.tsx): a sandboxed document
can't run the browser's PDF viewer, so a MAGIC-VERIFIED PDF asked for in a frame drops the CSP sandbox (nosniff stays).
/chat never passes it: there a PDF is a download (plan-11884 D2).
"""
from __future__ import annotations

from pathlib import Path

from fastapi.responses import FileResponse

CSP = "sandbox; default-src 'none'"
HEAD = 4096


def sniff(head: bytes) -> str | None:
    """The served type of a file from its first bytes, or None (not on the allowlist)."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"avif", b"avis"):
            return "image/avif"
        if brand == b"qt  ":
            return "video/quicktime"
        return "audio/mp4" if brand[:3] == b"M4A" else "video/mp4"
    if head.startswith(b"fLaC"):
        return "audio/flac"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    if head and b"\x00" not in head:
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as e:
            if e.start < len(head) - 4:                  # a multi-byte char cut by the window is still text
                return None
        return "text/plain; charset=utf-8"
    return None


EXT = {"image/avif": ".avif", "video/quicktime": ".mov", "audio/flac": ".flac", "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "audio/wav": ".wav",
       "application/pdf": ".pdf", "audio/mp4": ".m4a", "video/mp4": ".mp4", "video/webm": ".webm", "audio/ogg": ".ogg",
       "audio/mpeg": ".mp3", "text/plain; charset=utf-8": ".txt"}


def sniff_file(path: Path) -> str | None:
    with open(path, "rb") as f:
        return sniff(f.read(HEAD))


def serve_untrusted(path: Path, *, inline: bool = True, filename: str | None = None,
                    frame_pdf: bool = False) -> FileResponse:
    """Serve `path` (already authorised by the caller) under THE RULE above."""
    kind = sniff_file(path)
    headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": CSP, "Cache-Control": "no-store"}
    if kind and inline:
        if frame_pdf and kind == "application/pdf":
            del headers["Content-Security-Policy"]
        return FileResponse(path, media_type=kind, headers=headers, content_disposition_type="inline",
                            filename=filename or path.name)
    return FileResponse(path, media_type=kind if kind and not kind.startswith("text/") else "application/octet-stream",
                        headers=headers, content_disposition_type="attachment", filename=filename or path.name)
