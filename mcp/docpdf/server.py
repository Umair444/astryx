#!/usr/bin/env python3
"""astryx · docpdf MCP server — render a local HTML document to PDF and VERIFY the result.

One tool, html_to_pdf: headless Chromium print-to-pdf, then the checks a human otherwise runs
by hand (page count, text extractable, optional page cap), and an optional byte-identical copy
under a delivery name. Generic: CVs, reports, one-pagers — the caller supplies every path.

Boundaries (the HTML is a document, never a browser session):
- paths: absolute, resolved (symlinks and `..` followed) and confined to ALLOWED_ROOT
  (default <repo>/homes; DOCPDF_ROOT overrides); input must end .html/.htm, outputs .pdf.
- sandbox: Chromium runs inside bwrap with its own network namespace and a filesystem of /usr,
  fonts, the html file itself (read-only) and an empty output dir only. The page reaches no
  network (any protocol) and no other file, siblings included: documents are self-contained.
- fail closed: a missing Chromium, a render failure, a timeout, an empty/unreadable PDF, or a
  page cap exceeded is "error: ...", and a failed render never overwrites a good PDF.

Granted per charter (`Grants: docpdf`)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))   # astryx.paths: the org's estate (its HOME on a multi-org host), plan-11324 S3a
from astryx import paths  # noqa: E402
ALLOWED_ROOT = Path(os.environ.get("DOCPDF_ROOT") or paths.estate(__file__) / "homes").resolve()
RENDER_TIMEOUT = 60
CHROMIUM_CANDIDATES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")

mcp = FastMCP("astryx-docpdf")


class DocError(Exception):
    pass


def _err(msg: str) -> str:
    return "error: " + re.sub(r"\s+", " ", str(msg)).strip()[:300]


def _confine(p: str, suffixes: tuple[str, ...], what: str, must_exist: bool) -> Path:
    if not p or not os.path.isabs(p):
        raise DocError(f"{what} must be an absolute path")
    rp = Path(p).resolve()
    if rp != ALLOWED_ROOT and ALLOWED_ROOT not in rp.parents:
        raise DocError(f"{what} is outside the allowed root")
    if rp.suffix.lower() not in suffixes:
        raise DocError(f"{what} must end with {'/'.join(suffixes)}")
    if must_exist and not rp.is_file():
        raise DocError(f"{what} does not exist")
    if not must_exist and not rp.parent.is_dir():
        raise DocError(f"{what}: parent directory does not exist")
    return rp


def _chromium() -> str:
    for c in CHROMIUM_CANDIDATES:
        w = shutil.which(c)
        if w:
            return w
    raise DocError("no Chromium/Chrome binary on PATH")


def _render(html: Path, out: Path) -> None:
    """Chromium print-to-pdf into `out`, inside a bwrap sandbox. The one process seam: tests
    replace it. The sandbox is the boundary (a1 REVISE #44856): its own network namespace
    (no protocol leaves, WebRTC/UDP included), and a filesystem holding only /usr, fonts, the
    html FILE itself (read-only, at /doc/<name>; never its folder, a1 #44860: a folder of CVs is
    many applications) and the empty output temp dir (/out), so a file:// iframe/object/embed
    reads no other file at all. Environment cleared. No bwrap →
    error; never an unsandboxed render. The dead proxy is a second layer. (scriptEnabled=false is NOT used: it makes headless print-to-pdf write nothing.)"""
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise DocError("bwrap is not installed; refusing to render unsandboxed")
    chromium = _chromium()
    cmd = [bwrap, "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib",
           "--symlink", "usr/lib", "/lib64", "--symlink", "usr/bin", "/bin",
           "--ro-bind", "/etc/fonts", "/etc/fonts", "--proc", "/proc", "--dev", "/dev",
           "--tmpfs", "/tmp", "--dir", "/doc", "--ro-bind", str(html), f"/doc/{html.name}",
           "--bind", str(out.parent), "/out", "--unshare-all", "--die-with-parent",
           "--clearenv", "--setenv", "PATH", "/usr/bin", "--setenv", "HOME", "/tmp",
           chromium, "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
           "--user-data-dir=/tmp/prof",
           "--proxy-server=socks5://127.0.0.1:9", "--proxy-bypass-list=<-loopback>",
           "--no-pdf-header-footer", f"--print-to-pdf=/out/{out.name}",
           (Path("/doc") / html.name).as_uri()]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=RENDER_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise DocError(f"render timed out after {RENDER_TIMEOUT}s") from None
    if r.returncode != 0:
        raise DocError(f"sandboxed chromium exited {r.returncode}")


def _inspect(pdf: Path) -> dict:
    """Page count + extracted text via poppler (pdfinfo / pdftotext). Seam for tests."""
    try:
        info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, timeout=30)
        text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True,
                              text=True, timeout=30)
    except FileNotFoundError:
        raise DocError("poppler (pdfinfo/pdftotext) is not installed") from None
    except subprocess.TimeoutExpired:
        raise DocError("pdf inspection timed out") from None
    m = re.search(r"^Pages:\s+(\d+)", info.stdout or "", re.M)
    if info.returncode != 0 or not m:
        raise DocError("rendered file is not a readable PDF")
    if text.returncode != 0:
        raise DocError("pdftotext failed on the rendered PDF")
    return {"pages": int(m.group(1)), "text": text.stdout or ""}


@mcp.tool()
def html_to_pdf(html_path: str, pdf_path: str, max_pages: int = 0, copy_to: str = "") -> str:
    """Render a local HTML file to PDF with headless Chromium, then verify it.
    Paths are absolute and must sit under the allowed root (the org's homes/ by default).
    max_pages > 0 fails the call (and leaves any existing PDF untouched) when the render runs
    longer. copy_to (optional .pdf path) receives a byte-identical copy, e.g. a delivery name.
    Sandboxed: no network, no file but the html itself (inline CSS/images).
    Returns JSON: pdf, pages, bytes, text_chars, first_text_line, copy. Any failure is
    "error: ..." (never a half-written PDF)."""
    try:
        html = _confine(html_path, (".html", ".htm"), "html_path", True)
        out = _confine(pdf_path, (".pdf",), "pdf_path", False)
        dest = _confine(copy_to, (".pdf",), "copy_to", False) if copy_to else None
        if max_pages < 0:
            raise DocError("max_pages must be >= 0")
        with tempfile.TemporaryDirectory(prefix="docpdf.", dir=out.parent) as td:
            tmp = Path(td) / "render.pdf"
            _render(html, tmp)
            if not tmp.is_file() or tmp.stat().st_size == 0:
                raise DocError("chromium produced no PDF")
            meta = _inspect(tmp)
            if max_pages and meta["pages"] > max_pages:
                raise DocError(f"rendered {meta['pages']} pages; cap is {max_pages} "
                               "(existing PDF left untouched)")
            text = meta["text"].strip()
            if not text:
                raise DocError("PDF has no extractable text (an ATS would read it as blank)")
            tmp.replace(out)
        if dest:
            if dest.is_symlink():
                raise DocError("copy_to is a symlink; refusing to write through it")
            shutil.copyfile(out, dest, follow_symlinks=False)
        first = next((l.strip() for l in text.splitlines() if l.strip()), "")
        return json.dumps({"pdf": str(out), "pages": meta["pages"], "bytes": out.stat().st_size,
                           "text_chars": len(text), "first_text_line": first[:120],
                           "copy": str(dest) if dest else None}, ensure_ascii=False, indent=1)
    except DocError as e:
        return _err(e)
    except Exception as e:  # unexpected: fail closed, scrubbed
        return _err(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    mcp.run()
