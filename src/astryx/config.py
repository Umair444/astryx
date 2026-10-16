"""The ONE `.env` reader and writer (plan-10224 S1).

Read semantics are the ones the existing readers share (bridges/common.py env(), pulse.py's DSN): a
non-empty process environment variable wins; else the FIRST `KEY=` line of HOME/.env, its value split on
the first '=' and stripped. No quote stripping, no interpolation: a value means the same bytes here as in
`grep '^KEY=' .env | cut -d= -f2-`.

`set_env` edits in place: the first `KEY=` line is replaced, every other line is kept byte for byte, a
missing key is appended, and the file is written via a 0600 temp file and renamed (the .env holds the org
key and the DSN password). It never prints the value.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from astryx import paths


def env_path(home: Path | None = None) -> Path:
    return Path(home or paths.home()) / ".env"


def read_env(path: Path | None = None) -> dict[str, str]:
    """Every KEY=value in the file, first occurrence wins. Missing file -> {}."""
    p = Path(path) if path else env_path()
    out: dict[str, str] = {}
    try:
        text = p.read_text()
    except (FileNotFoundError, NotADirectoryError):
        return out
    for line in text.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k and k == k.strip() and k not in out:
            out[k] = v.strip()
    return out


def get(key: str, default: str = "", path: Path | None = None, environ: dict | None = None) -> str:
    environ = os.environ if environ is None else environ
    if environ.get(key):
        return environ[key]
    return read_env(path).get(key, default)


def dsn(path: Path | None = None, environ: dict | None = None) -> str:
    """ASTRYX_DSN: the environment first (an oracle binds a run to a fixture DB this way), else .env."""
    v = get("ASTRYX_DSN", "", path, environ)
    if not v:
        raise LookupError(f"ASTRYX_DSN is not set in the environment or {Path(path) if path else env_path()}")
    return v


def is_set(key: str, path: Path | None = None) -> bool:
    return bool(read_env(path).get(key))


def set_env(key: str, value: str, path: Path | None = None) -> None:
    if not key or "=" in key or "\n" in key or "\n" in value or "\r" in value:
        raise ValueError("set_env: key must be a bare name and value a single line")
    p = Path(path) if path else env_path()
    try:
        text = p.read_text()
    except FileNotFoundError:
        text = ""
    lines = text.splitlines(keepends=True)
    new = f"{key}={value}\n"
    for i, line in enumerate(lines):
        if line.split("=", 1)[0] == key and "=" in line:
            lines[i] = new
            break
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=p.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("".join(lines))
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    os.chmod(p, 0o600)
