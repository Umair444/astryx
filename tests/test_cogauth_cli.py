#!/usr/bin/env python3
"""plan-11859 U1+U2 (D7, D8, D9): the host CLI, src/astryx/cogauth.py, the ONE writer of accounts and memberships, and
the cog store's backup.

The REAL CLI in a child, against two fixture databases: the cog store (schema.sql + cog_schema.sql as the fixture's
extra DDL) and one org's. A fixture registry names the org and the cog block. Dummy passwords only; nothing prints a
password, a hash or a session token.

  K1 init: rc 0; the cog HOME holds identity.key (mode 600) and keys/<kid>.pub; the store's tables exist; the printed
     registry block names the id and HOME. A second init keeps the key (never overwrites it)
  K2 user add: the password comes from stdin, never argv (a password as an argument is a usage error, rc 2); the row's
     email is lowercased, its pw an argon2id PHC string, never the password; a short password, a duplicate email and
     an add with no cog block are refused (rc 1)
  K3 user reset: a new hash; EVERY live session of that account revoked, another account's left alone; an unknown
     email refused
  K4 grant / revoke: grant writes members (uid@cog id, role) in THAT org's database, a second grant changes the role
     (one row), revoke deletes it; an unknown org, an unknown email and a bad role are refused
  K5 backup + restore-verify (D9): a cog-<ts>.dump starting PGDMP; restore-verify restores it into a scratch database,
     finds the live store's account count, and drops the scratch; after one more account is added, the same dump is
     refused (rc 1: the counts differ), and the scratch is dropped either way
Seam: COGAUTH_SRC (a mutant cogauth.py). Exit 0 · 1 · 77 (no database).
"""
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_cogauth_cli', REPO, deps=('psycopg', 'cryptography'), env=False)
from astryx.security.sqlguard import propagate  # noqa: E402
from astryx.security.sqlguard.fixture import fixture_db, live_dsn  # noqa: E402

PY = sys.executable
fails = []
PW = {"one": "fx-dummy-pass-one-0001", "two": "fx-dummy-pass-two-0002", "new": "fx-dummy-pass-new-0003",
      "three": "fx-dummy-pass-three-0004"}


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            for label, v in PW.items():
                detail = str(detail).replace(v, f"<{label}'s value>")
            print(f"        {detail}")


def main():
    import psycopg
    t = Path(tempfile.mkdtemp(prefix="astryx-cogcli-")).resolve()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    pid = os.getpid()
    cid, org = f"fxcog-{pid:08d}", f"fxcli-{pid}"
    scratch = []
    try:
        with fixture_db(extra=((REPO / "src/astryx/sql/cog_schema.sql").read_text(),)) as store, fixture_db() as od:
            scratch.append(f"{store['dbname']}_restorecheck")
            home, oh = t / "cog", t / org
            home.mkdir()
            oh.mkdir()
            (home / ".env").write_text(f"ASTRYX_DSN={store['url']}\n")
            (oh / ".env").write_text(f"ASTRYX_ORG=fed-{org}\nASTRYX_DSN={od['url']}\n")
            # two orgs: a cog (the second never runs here); the registry names a db of its own (a fixture's is refused)
            o2 = t / "fxcli-other"
            o2.mkdir()
            orgsd = {org: {"home": str(oh), "db": f"fxclidb_{pid}"}, "fxcli-other": {"home": str(o2),
                                                                                      "db": f"fxclidb2_{pid}"}}
            bare, regf = t / "bare.json", t / "cog.json"
            bare.write_text(json.dumps({"orgs": orgsd}))
            regf.write_text(json.dumps({"orgs": orgsd, "cog": {"id": cid, "home": str(home)}}))
            src = os.environ.get("COGAUTH_SRC")
            # a mutant runs AS the real file (its __file__ places sql/ and src/), never from where it was written
            cli = [PY, "-c", "import sys; real, mut = sys.argv[1], sys.argv[2]; del sys.argv[1:3]; "
                   "exec(compile(open(mut).read(), real, 'exec'), {'__name__': '__main__', '__file__': real})",
                   str(REPO / "src/astryx/cogauth.py"), src] if src else [PY, str(REPO / "src/astryx/cogauth.py")]
            # sqlguard's shim in the child checks fixture stamps through the admin DSN, which it finds from an estate;
            # a cog-scoped CLI has no org HOME, so the tree is named (else every site here is capped at FIXTURE-DDL)
            base = {**{k: os.environ[k] for k in ("PATH", "HOME", "ASTRYX_FIXTURE_ADMIN_DSN") if k in os.environ},
                    "ASTRYX_SQLGUARD_ROOT": str(REPO)}

            def cog(*args, stdin="", reg=regf):
                p = subprocess.run([*cli, *args], input=stdin, capture_output=True, text=True, timeout=120,
                                   env=propagate.env_for_child({**base, "ASTRYX_COG_REGISTRY": str(reg)}))
                return p.returncode, p.stdout + p.stderr

            def q(dsn, sql, args=()):
                with psycopg.connect(dsn) as c:
                    return c.execute(sql, args).fetchall()

            outs = []
            print("K1 INIT")
            rc, out = cog("init", "--home", str(home), "--id", cid)
            outs.append(out)
            key = home / "identity.key"
            pubs = list((home / "keys").glob("*.pub")) if (home / "keys").is_dir() else []
            check("rc 0; identity.key (mode 600) and one keys/<kid>.pub", rc == 0 and key.is_file()
                  and stat.S_IMODE(key.stat().st_mode) == 0o600 and len(pubs) == 1, out[-300:])
            check("the store's tables exist", q(store["url"], "SELECT count(*) FROM pg_tables WHERE tablename IN "
                                                "('users', 'sessions')")[0][0] == 2)
            check("it prints the registry block, its id and HOME", f'"id": "{cid}"' in out and str(home) in out, out[-300:])
            before = key.read_bytes()
            rc, out = cog("init", "--home", str(home), "--id", cid)
            check("a second init keeps the key", rc == 0 and key.read_bytes() == before, out[-200:])

            print("\nK2 USER ADD")
            rc, out = cog("user", "add", "One@FX-CogCli.invalid", stdin=PW["one"] + "\n")
            outs.append(out)
            row = q(store["url"], "SELECT email, pw FROM users")
            check("rc 0; the email lowercased; pw an argon2id PHC string, never the password",
                  rc == 0 and len(row) == 1 and row[0][0] == "one@fx-cogcli.invalid" and row[0][1].startswith("$argon2id$")
                  and PW["one"] not in row[0][1], f"{rc} {out[-200:]}")
            rc_argv, out_argv = cog("user", "add", "two@fx-cogcli.invalid", PW["two"])
            check("a password as an argument: a usage error (rc 2), no row", rc_argv == 2 and len(q(
                store["url"], "SELECT 1 FROM users")) == 1, f"{rc_argv}")
            rc_s, _ = cog("user", "add", "two@fx-cogcli.invalid", stdin="short\n")
            rc_d, out_d = cog("user", "add", "ONE@fx-cogcli.invalid", stdin=PW["two"] + "\n")
            rc_n, out_n = cog("user", "add", "two@fx-cogcli.invalid", stdin=PW["two"] + "\n", reg=bare)
            check("refused (rc 1, no row): a short password, a duplicate email (any case), a cog with no block",
                  (rc_s, rc_n) == (1, 1) and "names no cog" in out_n and rc_d != 0
                  and len(q(store["url"], "SELECT 1 FROM users")) == 1,
                  f"{rc_s} {rc_d} {rc_n}")
            rc, out = cog("user", "add", "two@fx-cogcli.invalid", stdin=PW["two"] + "\n")
            check("a second account is added", rc == 0, out[-200:])
            outs += [out_argv, out_d, out_n, out]

            print("\nK3 USER RESET")
            ids = dict(q(store["url"], "SELECT email, id FROM users"))
            u1, u2 = ids["one@fx-cogcli.invalid"], ids["two@fx-cogcli.invalid"]
            with psycopg.connect(store["url"], autocommit=True) as c:     # live sessions, as sign_in leaves them
                for d, u in ((b"fx-sess-1", u1), (b"fx-sess-2", u1), (b"fx-sess-3", u2)):
                    c.execute("INSERT INTO sessions (digest, uid, expires) VALUES (%s, %s, now() + interval '1 day')",
                              (d, u))
            old = q(store["url"], "SELECT pw FROM users WHERE id = %s", (u1,))[0][0]
            rc, out = cog("user", "reset", "one@fx-cogcli.invalid", stdin=PW["new"] + "\n")
            outs.append(out)
            live = dict(q(store["url"], "SELECT uid, count(*) FILTER (WHERE revoked IS NULL) FROM sessions GROUP BY uid"))
            check("rc 0; a new hash; every session of the account revoked, the other account's left alone",
                  rc == 0 and q(store["url"], "SELECT pw FROM users WHERE id = %s", (u1,))[0][0] != old
                  and live.get(u1) == 0 and live.get(u2) == 1, f"{rc} {live}")
            rc, _ = cog("user", "reset", "nobody@fx-cogcli.invalid", stdin=PW["new"] + "\n")
            check("an unknown email: refused (rc 1)", rc == 1)
            rc_r = [cog("user", "reset", "two@fx-cogcli.invalid", stdin=PW["two"] + "\n")[0] for _ in range(2)]
            live = dict(q(store["url"], "SELECT uid, count(*) FILTER (WHERE revoked IS NULL) FROM sessions GROUP BY uid"))
            check("a reset of an account with no live session left: rc 0 (its first reset revoked the one it had)",
                  rc_r == [0, 0] and live.get(u2) == 0, f"{rc_r} {live}")

            print("\nK4 GRANT / REVOKE")
            rc, out = cog("grant", org, "ONE@fx-cogcli.invalid", "member")
            rc2, out2 = cog("grant", org, "one@fx-cogcli.invalid", "owner")
            outs += [out, out2]
            rows = q(od["url"], "SELECT uid, role FROM members")
            check("grant writes members in THAT org's database (uid@cog id); a second grant changes the role, one row",
                  rc == 0 and rc2 == 0 and rows == [(f"{u1}@{cid}", "owner")], f"{rc} {rc2} {rows}")
            rcx = [cog("grant", "fxnoorg", "one@fx-cogcli.invalid", "owner")[0],
                   cog("grant", org, "nobody@fx-cogcli.invalid", "owner")[0],
                   cog("grant", org, "one@fx-cogcli.invalid", "admin")[0]]
            check("refused: an unknown org (1), an unknown email (1), a bad role (usage, 2)", rcx == [1, 1, 2], str(rcx))
            rc, out = cog("revoke", org, "one@fx-cogcli.invalid")
            outs.append(out)
            check("revoke deletes the row", rc == 0 and q(od["url"], "SELECT count(*) FROM members")[0][0] == 0, out[-200:])
            rc, out = cog("revoke", org, "one@fx-cogcli.invalid")
            check("revoking a non-member: rc 0, and it says so", rc == 0 and "was not a member" in out, out[-200:])

            print("\nK5 BACKUP + RESTORE-VERIFY (D9)")
            bk = t / "backups"
            rc, out = cog("backup", str(bk))
            dumps = sorted(bk.glob("cog-*.dump"))
            check("backup: one cog-<ts>.dump, starting PGDMP", rc == 0 and len(dumps) == 1
                  and dumps[0].read_bytes()[:5] == b"PGDMP", out[-300:])

            def scratch_gone():
                with psycopg.connect(live_dsn(), autocommit=True) as c:
                    return not c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (scratch[0],)).fetchone()
            rc, out = cog("restore-verify", str(bk))
            check("restore-verify: rc 0, the live store's account count, the scratch dropped",
                  rc == 0 and "2 accounts" in out and scratch_gone(), out[-300:])
            cog("user", "add", "three@fx-cogcli.invalid", stdin=PW["three"] + "\n")
            rc, out = cog("restore-verify", str(bk))
            check("one more account since the dump: refused (rc 1, the counts differ), the scratch dropped",
                  rc == 1 and scratch_gone(), out[-300:])
            leaked = [label for label, v in PW.items() if any(v in o for o in outs)]
            check("no password on any output", not leaked, str(leaked))
    finally:
        try:
            import psycopg
            from psycopg import sql
            with psycopg.connect(live_dsn(), autocommit=True) as c:
                for d in scratch:
                    c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(d)))
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(t, True)
    print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: the cog's host CLI writes accounts and "
          "memberships, and its store's backup restores")
    return 1 if fails else 0


if __name__ == "__main__":
    from astryx.security.sqlguard.estate import unavailable
    from astryx.security.sqlguard.fixture import FixtureUnavailable
    try:
        sys.exit(main())
    except FixtureUnavailable as e:          # no admin DSN reachable: NOT SEARCHED (77), never a crash read as a red
        unavailable("test_cogauth_cli", REPO, e)
