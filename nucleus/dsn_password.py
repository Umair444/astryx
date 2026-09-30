"""S1c switch (plan-5497): move the DB password OUT of every DSN, or put it back, with no copy.

  venv/bin/python -m nucleus.dsn_password strip            # dry run: what would change (names only)
  venv/bin/python -m nucleus.dsn_password strip --apply
  venv/bin/python -m nucleus.dsn_password restore --apply  # rollback: rebuild each DSN from ~/.pgpass

TARGETS are derived, never listed here: every URL_CONFIG key (secretset.URL_CONFIG) found in .env or
in a declared holder FILE of the manifest. So a new copy of a DSN (geoloc.env was one) is switched
with the rest, and a copy nobody declared is L.4's to catch.

STRIP refuses, naming the key, unless ~/.pgpass already holds an entry that matches the DSN's host
LITERALLY (localhost is not 127.0.0.1: BC-a), its port, database and user, with the SAME password:
a stripped DSN must still authenticate. RESTORE needs no copy of anything: the password it puts back
is the one ~/.pgpass holds. Both rewrite atomically with the file's mode kept, and print only
"<file>: <KEY> <action>". Neither ever prints a value.

After --apply: run nucleus.dsn_census (0 required failing), then RESTART every DSN consumer: a
service keeps the DSN it read at startup in memory, so the rotation (S3b, precondition P4) refuses
while any consumer predates the switch.
"""
import argparse
import os
import re
import sys
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from nucleus import secretset as ss  # noqa: E402


def targets(manifest=None, root: Path = REPO) -> list[Path]:
    m = manifest or ss.holders()
    files = {Path(ss.ENV_FILE).resolve()}
    for h in m["holders"]:
        p = h["path"]
        # only LIVE holders: a retired copy (the quarantine) is deleted, not switched
        if h.get("fate") != "keep" or p.startswith(("docker:", "unit-env:")) or " " in p or "*" in p:
            continue
        # resolved: rewriting a SYMLINK's path would replace the link and leave the real file as it was
        files.update(x.resolve() for x in ss._expand(p, root) if x.is_file())
    out = []
    for f in sorted(files):
        try:
            keys = [k for k, _ in ss._env_pairs(f)]
        except OSError:
            continue
        if any(k in ss.URL_CONFIG for k in keys):
            out.append(f)
    return out


def _pgpass(path) -> list[list[str]]:
    """Rows of host, port, db, user, password, with libpq's escaping ('\\:' and '\\\\') undone."""
    rows = []
    for line in Path(path).read_text().splitlines():
        parts = re.split(r"(?<!\\):", line, maxsplit=4)
        if len(parts) == 5 and not line.lstrip().startswith("#"):
            parts[4] = parts[4].replace("\\:", ":").replace("\\\\", "\\")
            rows.append(parts)
    return rows


def _match(rows, host, port, db, user) -> str | None:
    """libpq's rule: the FIRST entry whose fields match (literally, or '*')."""
    for h, p, d, u, pw in rows:
        if h in (host, "*") and p in (str(port), "*") and d in (db, "*") and u in (user, "*"):
            return pw
    return None


def _rewrite(f: Path, key: str, new_value: str):
    lines = f.read_text().splitlines(keepends=True)
    out = []
    for line in lines:
        if line.split("=", 1)[0].removeprefix("export ").strip() == key:
            nl = "\n" if line.endswith("\n") else ""
            out.append(f"{key}={new_value}{nl}")
        else:
            out.append(line)
    tmp = f.with_name(f.name + ".dsn-tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, f.stat().st_mode & 0o777)
    with os.fdopen(fd, "w") as w:
        w.write("".join(out))
        w.flush()
        os.fsync(w.fileno())
    os.replace(tmp, f)


def plan(action: str, files: list[Path], pgpass: Path) -> tuple[list, list]:
    """([(file, key, new_value)], [refusal reasons]). Pure: nothing is written."""
    rows = _pgpass(pgpass) if pgpass.exists() else []
    changes, refusals = [], []
    for f in files:
        for k, v in ss._env_pairs(f):
            if k not in ss.URL_CONFIG or "://" not in v:
                continue
            u = urllib.parse.urlsplit(v)
            host, port = u.hostname, u.port or 5432
            user = u.username or ""
            db = u.path.lstrip("/") or user                # libpq's default database is the user
            where = f"{str(f).replace(str(Path.home()), '~')}: {k}"
            netloc_tail = f"{host}" + (f":{u.port}" if u.port else "")
            if action == "strip":
                if u.password is None:
                    continue
                have = _match(rows, host, port, db, user)
                if have is None:
                    refusals.append(f"{where}: no ~/.pgpass entry for host {host!r} (literal), port "
                                    f"{port}, db {db!r}, user {user!r}: add it first (BC-a)")
                elif have != urllib.parse.unquote(u.password):
                    refusals.append(f"{where}: the ~/.pgpass entry for {host!r} holds a DIFFERENT "
                                    "password: stripping would lock this consumer out")
                else:
                    changes.append((f, k, urllib.parse.urlunsplit(
                        (u.scheme, f"{user}@{netloc_tail}", u.path, u.query, u.fragment))))
            else:
                if u.password is not None:
                    continue
                have = _match(rows, host, port, db, user)
                if have is None:
                    refusals.append(f"{where}: no ~/.pgpass entry to restore from")
                else:
                    pw = urllib.parse.quote(have, safe="")
                    changes.append((f, k, urllib.parse.urlunsplit(
                        (u.scheme, f"{user}:{pw}@{netloc_tail}", u.path, u.query, u.fragment))))
    return changes, refusals


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("strip", "restore"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--pgpass", default=os.environ.get("PGPASSFILE") or str(Path.home() / ".pgpass"))
    a = ap.parse_args(argv)
    changes, refusals = plan(a.action, targets(), Path(a.pgpass))
    for r in refusals:
        print(f"REFUSE {r}")
    if refusals:
        print("nothing written: every refusal must clear first (all or nothing)")
        return 77
    for f, k, _ in changes:
        print(f"{str(f).replace(str(Path.home()), '~')}: {k} "
              f"{'would ' if not a.apply else ''}{a.action}")
    if a.apply:
        for f, k, v in changes:
            _rewrite(f, k, v)
    if not changes:
        print(f"nothing to {a.action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
