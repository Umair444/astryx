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

if not __package__:  # run by path (`python src/astryx/config.py dsn` from a shell script): src/ goes first
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))

import os  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from astryx import paths  # noqa: E402


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


def get(key: str, default: str = "", path: Path | None = None, environ: dict | None = None,
        env_first: bool = True) -> str:
    """`key` from the environment first, else the HOME's .env.

    On a MULTI-org host (orgs.multi) the environment is not consulted at all, for any key: the value is the HOME's
    .env or `default`. An org-B process that inherited org A's PEOPLE_SALT or WA_CLI must not salt or send as A
    (a3 BC-S3), and a .env name nobody listed is covered too, because nothing is listed (the polarity secretset uses:
    unknown means guarded). ASTRYX_DSN is read through dsn(), which checks an environment value instead."""
    environ = os.environ if environ is None else environ
    if env_first and environ.get(key) and not _multi(environ):
        return environ[key]
    return read_env(path).get(key, default)


def org_env(key: str, default=None, path: Path | None = None, environ: dict | None = None):
    """An org name a reader took from the ENVIRONMENT only (`os.environ.get(key, default)`), routed (BC-S3(3)).
    One org: exactly `environ.get(key, default)`, byte for byte (no .env read is added). Several orgs: the HOME's .env
    (`path`, else the HOME's) or `default`, never the environment, which may be another org's (a3 #58597)."""
    environ = os.environ if environ is None else environ
    if not _multi(environ):
        return environ.get(key, default)
    v = read_env(path).get(key)
    return v if v else default


def _multi(environ) -> bool:
    from astryx import orgs
    return orgs.multi(environ)


class ForeignDSN(RuntimeError):
    """A DSN that binds ANOTHER registered org's database, or one libpq would reach by default (plan-11324 S3a
    corrections 1 and 2). A RuntimeError, never a LookupError: an oracle reads LookupError as "no DB, skip"."""


def dsn(path: Path | None = None, environ: dict | None = None, env_first: bool = True) -> str:
    """ASTRYX_DSN: the environment first (an oracle binds a run to a fixture DB this way), else .env.
    env_first=False reads the file only (the readers that never consulted the environment keep doing exactly that).

    On a multi-org host (and only there) the pair is checked against the registry, so the HOME and the DSN can't
    disagree (a2 B(1), correction 2 of #58435):
      a fixture database (astryx_fx_*)                          allowed (the oracles bind through the environment)
      the environment's DSN binds ANOTHER registered org's db   refused
      the DSN binds the user-named db or `postgres`            refused (libpq's own fallbacks, correction 1)
      this HOME's own .env names a db other than its registry entry   refused (the disagreeing pair)"""
    environ = os.environ if environ is None else environ
    v = environ.get("ASTRYX_DSN") if env_first else ""
    src = "the environment"
    if not v:
        p = Path(path) if path else env_path()
        v, src = read_env(p).get("ASTRYX_DSN", ""), str(p)
    if not v:
        raise LookupError(f"ASTRYX_DSN is not set in the environment or {Path(path) if path else env_path()}")
    if _multi(environ):
        _check_pair(v, src, path, environ)
    return v


def _check_pair(v: str, src: str, path, environ) -> None:
    from astryx import orgs
    if orgs.is_fixture(v):
        return
    reg = orgs.load(environ) or {}
    info = orgs.conninfo(v)
    db = info.get("dbname") or info.get("user")
    if not db or db in orgs.NEVER_ORG_DB or db == info.get("user"):
        raise ForeignDSN(f"the DSN in {src} binds {db!r}: libpq's default database, never an org's (correction 1)")
    home = Path(path).parent if path else paths.home()
    mine = orgs.org_of(home, environ)
    owner = next((o for o, e in reg.items() if e["db"] == db), None)
    if owner is not None and owner != mine:
        raise ForeignDSN(f"the DSN in {src} binds org {owner}'s database, and this HOME is "
                         f"{mine or 'no registered org'} (correction 2)")
    if mine is not None and owner is None and src != "the environment":
        raise ForeignDSN(f"{src} names database {db!r}, and the registry gives {mine} {reg[mine]['db']!r}")


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


def _main(argv) -> int:
    """`python -m astryx.config dsn|get KEY|estate`: the shell's way to the ONE resolver (spawn.sh, backup.sh, …).
    `dsn` and `get` print the value on stdout for `$(…)` capture, the way `grep '^K=' .env | cut -d= -f2-` did;
    `estate` prints the org's estate root (paths.estate())."""
    import sys
    try:
        f = paths.estate() / ".env"      # this checkout's estate on one org (what `"$ROOT/.env"` was), else the HOME's
        if argv[:1] == ["dsn"]:
            print(dsn(f, env_first="--file" not in argv))
        elif argv[:1] == ["get"] and len(argv) >= 2:
            print(get(argv[1], "", f, env_first="--file" not in argv))
        elif argv[:1] == ["estate"]:
            print(paths.estate())
        else:
            print("usage: python -m astryx.config dsn [--file] | get KEY [--file] | estate", file=sys.stderr)
            return 2
    except (LookupError, RuntimeError) as e:
        print(f"astryx.config: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
