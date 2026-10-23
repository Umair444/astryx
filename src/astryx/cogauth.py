#!/usr/bin/env python3
"""The cog's sign-in (plan-11859 U1U2, D7, D8, D9): accounts and sessions in the COG's store, membership in each
org's own `members` table, and the host CLI that is the only writer of either.

    venv/bin/python src/astryx/cogauth.py init --home DIR [--id ID]     a cog HOME: its signing key (+ keys/<kid>.pub)
                                                                        and the cog store's schema; prints the
                                                                        registry block to add (sudo: the owner's)
    venv/bin/python src/astryx/cogauth.py user add EMAIL                the password is read from stdin (a pipe) or
    venv/bin/python src/astryx/cogauth.py user reset EMAIL              the terminal, NEVER argv; reset revokes every
                                                                        session of that account
    venv/bin/python src/astryx/cogauth.py grant ORG EMAIL owner|member|viewer
    venv/bin/python src/astryx/cogauth.py revoke ORG EMAIL
    venv/bin/python src/astryx/cogauth.py backup DIR                    the cog store: pg_dump -Fc → DIR/cog-<ts>.dump
    venv/bin/python src/astryx/cogauth.py restore-verify DIR            the newest dump restores into a scratch
                                                                        database (<db>_restorecheck), its users count
                                                                        matches the live store's, and it is dropped

THE RULES IT HOLDS:
- There is no public sign-up (D7): an account exists because the host CLI wrote it. Recovery is `user reset` (no
  email: an externally authored identity, a1 F6).
- A password is stored as an argon2id PHC string (OWASP's first choice), by libsodium through PyNaCl, already a core
  dependency. libsodium releases the GIL, so the front checks it in a thread and its event loop keeps relaying
  (measured: `cryptography`'s argon2id held the GIL, 2 loop ticks in 1.65 s; PyNaCl's left 61 of ~93). A sign-in for
  an email with no account still pays one check (DUMMY), so the reply's latency doesn't say whether the account
  exists (F8, I9).
- A session is a server row, so sign-out and reset revoke it for real. The cookie holds a random token; the row
  holds only its sha256.
- Bootstrap fails CLOSED with ONE writer (D8, a2 I8): an org whose `members` table is empty opens to nobody but
  the owner key. grant() is the one writer of a membership row: this CLI, and devtools/cog_add_org.py --owner in the
  same act that makes an org.
- The cog store's DSN is the cog HOME's .env (ASTRYX_DSN), never an org's. `grant` reaches an org's database by that
  org's own .env DSN, the declared cog-scoped read the gateway already makes (config.dsn, env_first=False).
Exit 0 done · 1 refused or failed, named (never a value) · 2 usage.
"""
from __future__ import annotations

if not __package__:  # run by path: the checkout's src/ goes first on sys.path so `astryx` resolves
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))

import argparse
import asyncio
import datetime
import getpass
import hashlib
import secrets
import subprocess
import sys
from pathlib import Path

from astryx import config, orgs

ROLES = ("owner", "member", "viewer")
SESSION_DAYS = 14
SCHEMA = Path(__file__).resolve().parent / "sql" / "cog_schema.sql"
# argon2id above OWASP's floor for interactive sign-in (m 19 MiB, t 2): m 64 MiB, t 3; libsodium fixes p at 1
M, T, P = 65536, 3, 1


# ------------------------------------------------------------------ passwords
def hash_password(pw: str) -> str:
    from nacl import pwhash
    return pwhash.argon2id.str(pw.encode(), opslimit=T, memlimit=M * 1024).decode()


def check_password(pw: str, phc: str) -> bool:
    """libsodium's own verify (constant-time), refusing anything that is not an argon2id string."""
    from nacl import exceptions, pwhash
    if not phc.startswith("$argon2id$"):
        return False
    try:
        return pwhash.argon2id.verify(phc.encode(), pw.encode())
    except (exceptions.CryptoError, ValueError, TypeError):
        return False


_dummy: str | None = None


def dummy() -> str:
    """A real hash of a random password, made once: the check an unknown email pays, so its latency is a known
    account's (F8)."""
    global _dummy
    if _dummy is None:
        _dummy = hash_password(secrets.token_urlsafe(16))
    return _dummy


def norm_email(e: str) -> str:
    return e.strip().lower()


def digest(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


# ------------------------------------------------------------------ the front's sessions (async: psycopg)
async def sign_in(run, email: str, pw: str, check=None) -> tuple[int, str] | None:
    """(uid, a new session token), or None. `run(fn, *args)` runs fn on the store's connection (the front's lock);
    `check(fn, *args)` runs the password check off the event loop (the front's own bounded executor; asyncio's default
    pool when not given). An unknown email and a wrong password are the same None, and each pays one argon2id check,
    OUTSIDE the store's lock: a sign-in never stalls another viewer's session lookup."""
    row = await run(_account, norm_email(email))
    check = check or asyncio.to_thread
    ok = await check(check_password, pw, row[1] if row else dummy())
    if not (row and ok):
        return None
    token = secrets.token_urlsafe(32)
    await run(_open_session, row[0], digest(token))
    return row[0], token


async def _account(conn, email: str):
    cur = await conn.execute("SELECT id, pw FROM users WHERE email = %s", (email,))
    return await cur.fetchone()


async def _open_session(conn, uid: int, dig: bytes) -> None:
    await conn.execute("INSERT INTO sessions (digest, uid, expires) VALUES (%s, %s, now() + make_interval(days => %s))",
                       (dig, uid, SESSION_DAYS))


async def session_of(conn, token: str) -> tuple[int, str] | None:
    """(uid, email) of a live session (not revoked, not expired), or None."""
    cur = await conn.execute("SELECT u.id, u.email FROM sessions s JOIN users u ON u.id = s.uid "
                             "WHERE s.digest = %s AND s.revoked IS NULL AND s.expires > now()", (digest(token),))
    row = await cur.fetchone()
    return (row[0], row[1]) if row else None


async def sign_out(conn, token: str) -> None:
    await conn.execute("UPDATE sessions SET revoked = now() WHERE digest = %s AND revoked IS NULL", (digest(token),))


# ------------------------------------------------------------------ the host CLI's writes (sync: psycopg)
def add_user(conn, email: str, pw: str) -> int:
    cur = conn.execute("INSERT INTO users (email, pw) VALUES (%s, %s) RETURNING id", (norm_email(email),
                                                                                      hash_password(pw)))
    return cur.fetchone()[0]


def uid_of(conn, email: str) -> int | None:
    row = conn.execute("SELECT id FROM users WHERE email = %s", (norm_email(email),)).fetchone()
    return row[0] if row else None


def reset(conn, email: str, pw: str) -> int | None:
    """A new password, and every session of the account revoked; the uid, or None for no such account."""
    row = conn.execute("UPDATE users SET pw = %s WHERE email = %s RETURNING id",
                       (hash_password(pw), norm_email(email))).fetchone()
    if row:
        conn.execute("UPDATE sessions SET revoked = now() WHERE uid = %s AND revoked IS NULL", (row[0],))
    return row[0] if row else None


def sub(uid: int, cog_id: str) -> str:
    """The identity a token carries and a members row names (a2 I6): the account, qualified by the cog's stable id."""
    return f"{uid}@{cog_id}"


def grant(org_conn, who: str, role: str) -> None:
    """THE one writer of a membership row (D8)."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    org_conn.execute("INSERT INTO members (uid, role) VALUES (%s, %s) ON CONFLICT (uid) DO UPDATE SET role = "
                     "EXCLUDED.role", (who, role))


def revoke(org_conn, who: str) -> bool:
    return org_conn.execute("DELETE FROM members WHERE uid = %s", (who,)).rowcount > 0


# ------------------------------------------------------------------ the CLI
def cog_or_refuse(env=None) -> dict:
    c = orgs.cog(env)
    if c is None:
        raise SystemExit("cogauth: this host's registry names no cog (its `cog` block): there is no sign-in to manage")
    return c


def store_dsn(home: Path) -> str:
    try:        # the ONE resolver, file only: it refuses a DSN that binds an org's database (config._check_pair)
        dsn = config.dsn(Path(home) / ".env", env_first=False)
    except LookupError:
        raise SystemExit("cogauth: the cog HOME's .env names no ASTRYX_DSN (its user store)") from None
    except config.ForeignDSN as e:
        raise SystemExit(f"cogauth: the cog store's DSN is refused: {e}") from None
    if orgs.db_of(dsn) in {e["db"] for e in (orgs.load() or {}).values()}:
        raise SystemExit("cogauth: the cog store's database is an org's; it is the cog's own")
    return dsn


def _password(prompt: str) -> str:
    if sys.stdin.isatty():
        pw = getpass.getpass(prompt)
        if pw != getpass.getpass("again: "):
            raise SystemExit("cogauth: the two passwords differ")
    else:
        pw = sys.stdin.readline().rstrip("\n")
    if len(pw) < 12:
        raise SystemExit("cogauth: a password has at least 12 characters")
    return pw


def _org_dsn(org: str, env=None) -> str:
    reg = orgs.load(env) or {}
    if org not in reg:
        raise SystemExit(f"cogauth: no org {org!r} in this cog")
    return config.dsn(reg[org]["home"] / ".env", env_first=False)


def cmd_init(a) -> int:
    import psycopg
    from astryx.security import identity
    home = Path(a.home).resolve()
    cid = a.id or secrets.token_hex(8)
    if not orgs.COG_ID.fullmatch(cid):
        raise SystemExit(f"cogauth: a cog id matches {orgs.COG_ID.pattern}")
    if (home / identity.PRIVATE).exists():
        print(f"cogauth: {home} already has a signing key; kept")
    else:
        print(f"cogauth: new signing key, kid {identity.make_keys(home)}")
    with psycopg.connect(store_dsn(home), autocommit=True) as c:
        c.execute(SCHEMA.read_text())
    print("cogauth: the cog store's schema is applied. Add this to the registry (the owner's sudo step):")
    print(f'  "cog": {{"id": "{cid}", "home": "{home}"}}')
    return 0


def cmd_user(a) -> int:
    import psycopg
    c = cog_or_refuse()
    pw = _password(f"password for {norm_email(a.email)}: ")
    with psycopg.connect(store_dsn(c["home"]), autocommit=True) as conn:
        if a.act == "add":
            print(f"cogauth: account {sub(add_user(conn, a.email, pw), c['id'])} added")
        elif reset(conn, a.email, pw) is None:
            raise SystemExit("cogauth: no such account")
        else:
            print("cogauth: password reset; every session of the account is revoked")
    return 0


def cmd_grant(a, role: str | None) -> int:
    import psycopg
    c = cog_or_refuse()
    with psycopg.connect(store_dsn(c["home"])) as conn:
        uid = uid_of(conn, a.email)
    if uid is None:
        raise SystemExit("cogauth: no such account")
    with psycopg.connect(_org_dsn(a.org), autocommit=True) as oc:
        if role:
            grant(oc, sub(uid, c["id"]), role)
            print(f"cogauth: {sub(uid, c['id'])} is {role} of {a.org}")
        else:
            print(f"cogauth: {sub(uid, c['id'])} " + ("removed from " if revoke(oc, sub(uid, c["id"])) else
                                                      "was not a member of ") + a.org)
    return 0


def cmd_backup(a) -> int:
    c = cog_or_refuse()
    out = Path(a.dir)
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"cog-{datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ')}.dump"
    tmp = f.with_suffix(".tmp")
    r = subprocess.run(["pg_dump", "-Fc", "-f", str(tmp), store_dsn(c["home"])], capture_output=True, text=True)
    if r.returncode != 0 or tmp.read_bytes()[:5] != b"PGDMP":
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"cogauth: pg_dump failed (rc {r.returncode})")
    tmp.replace(f)
    print(f"cogauth: backed up to {f}")
    return 0


def cmd_restore_verify(a) -> int:
    import psycopg
    from psycopg import sql
    c = cog_or_refuse()
    dumps = sorted(Path(a.dir).glob("cog-*.dump"))
    if not dumps:
        raise SystemExit(f"cogauth: no cog-*.dump in {a.dir}")
    dsn = store_dsn(c["home"])
    db = orgs.db_of(dsn)
    scratch = f"{db}{orgs.SCRATCH_SUFFIX}"
    scratch_dsn = psycopg.conninfo.make_conninfo(dsn, dbname=scratch)
    with psycopg.connect(dsn, autocommit=True) as live:
        live.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(scratch)))
        live.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch)))
        try:
            r = subprocess.run(["pg_restore", "--no-owner", "-d", scratch_dsn, str(dumps[-1])],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise SystemExit(f"cogauth: {dumps[-1].name} did not restore (rc {r.returncode})")
            with psycopg.connect(scratch_dsn) as s:
                got = s.execute("SELECT count(*) FROM users").fetchone()[0]
            have = live.execute("SELECT count(*) FROM users").fetchone()[0]
        finally:
            live.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(scratch)))
    if got != have:
        raise SystemExit(f"cogauth: {dumps[-1].name} restored {got} accounts; the live store has {have}")
    print(f"cogauth: {dumps[-1].name} restores ({got} accounts, as live)")
    return 0


class _Parser(argparse.ArgumentParser):
    """A usage error that never repeats what it didn't expect: a password typed as an argument stays off the screen."""
    def error(self, message):
        if message.startswith("unrecognized arguments"):
            message = "unexpected extra arguments (a password is read from stdin, never the command line)"
        super().error(message)


def main(argv=None) -> int:
    ap = _Parser(description="the cog's sign-in: accounts, membership, its store's backup")
    s = ap.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
    i = s.add_parser("init")
    i.add_argument("--home", required=True)
    i.add_argument("--id")
    u = s.add_parser("user")
    u.add_argument("act", choices=("add", "reset"))
    u.add_argument("email")
    for name in ("grant", "revoke"):
        g = s.add_parser(name)
        g.add_argument("org")
        g.add_argument("email")
        if name == "grant":
            g.add_argument("role", choices=ROLES)
    for name in ("backup", "restore-verify"):
        s.add_parser(name).add_argument("dir")
    a = ap.parse_args(argv)
    if a.cmd == "init":
        return cmd_init(a)
    if a.cmd == "user":
        return cmd_user(a)
    if a.cmd in ("grant", "revoke"):
        return cmd_grant(a, getattr(a, "role", None))
    return cmd_backup(a) if a.cmd == "backup" else cmd_restore_verify(a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
            sys.exit(1)
        raise
