"""The observatory's ONE writer for host files (plan-11860 E3): charters, runtime.json, routes-<channel>.json, the
SQL library. Every in-place write in observatory/api goes through atomic_write, so a reader never sees a torn file (a
bridge re-reads its routes per message) and a writer that read an older version is refused, not silently last-wins.

    atomic_write(path, text, if_match=None)
        temp file in the SAME directory, fsync, os.replace: the file is the old bytes or the new, never half.
        if_match: the sha256 (hex) of the content the caller read; a mismatch raises Conflict and nothing is written.
        The file keeps its mode (a new file is 0644, or `mode`).
    etag(path) -> the sha256 hex of the file's bytes now ("" for an absent file), what if_match is compared against.

The census (tests/test_observatory_hostwrite.py) holds observatory/api to it: no write_text and no open-for-write
outside this module, except the people answers log, which is O_APPEND-only by design.
"""
import hashlib
import os
import tempfile
from pathlib import Path


class Conflict(Exception):
    """The file changed since the caller read it."""


def etag(path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        return ""


def atomic_write(path, text: str | bytes, if_match: str | None = None, mode: int | None = None) -> str:
    p = Path(path)
    if if_match is not None and etag(p) != if_match:
        raise Conflict(str(p))
    try:
        keep = os.stat(p).st_mode & 0o7777
    except FileNotFoundError:
        keep = 0o644 if mode is None else mode
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", dir=p.parent)
    data = text if isinstance(text, bytes) else text.encode()
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, keep)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return hashlib.sha256(data).hexdigest()
