#!/usr/bin/env python3
"""cog_roles — the cog's Postgres roles, provisioned (cog-rls slice 2; homes/seed/cog-rebuild/RLS.md §2, §4).

Every runtime connection used to be the bootstrap superuser `astryx` (OID 10, which can never lose SUPERUSER). This
tool moves them off it. It is the PROVISIONER: the only code that holds the superuser credential, and the only code
that creates roles, owns objects, or writes a password.

  role             attributes                                              purpose
  astryx_schema    NOLOGIN NOBYPASSRLS                                     owns every core table, view, function
  astryx_org       NOLOGIN group                                           DML + sequence use on core tables
  org_<key>        LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS   one per org, IN ROLE astryx_org only;
                                                                           creates in the shared `store` only, as
                                                                           store.<key>__<name> (astryx_store_guard)
  astryx_cog       LOGIN                                                   cog store, relay_*, leases, usage
  astryx_test      LOGIN CREATEDB CREATEROLE BYPASSRLS                     the fixtures (ASTRYX_TEST_DSN)
  astryx_monitor   LOGIN, IN ROLE pg_monitor                               pg_stat_activity across roles

Object ownership and the core-table grants are schema.sql's own last statement (`CALL cog.adopt()`), driven by the
names this tool writes into `cog.roles`; so EVERY apply path (init.sh, devtools/org_apply.py, a fixture) leaves the
same ownership, and no role name is a literal in the file. What only a cluster-level actor can do is here: CREATE
ROLE, passwords (a client-computed SCRAM verifier: the plaintext never crosses the socket or reaches a log), database
CONNECT and the org's `cog.orgs` row. There is NO per-org schema (owner ruling 11-13): agent-authored tables live in
the one shared `store` schema, named for their creator and locked by schema.sql's store guard.

THE SUPERUSER CREDENTIAL moves to a ROOT-ONLY file (default /etc/astryx/pg-super.dsn, 0600 root; ASTRYX_PG_SUPER_FILE
names another), and the org's .env gets `ASTRYX_DSN` with user=org_<key>. The verbs that need it run under sudo:

    venv/bin/python devtools/cog_roles.py stash-super --env <org home>/.env --to <file>   # copy the superuser DSN
    sudo install -o root -g root -m 0600 <file> /etc/astryx/pg-super.dsn && shred -u <file>
    sudo venv/bin/python devtools/cog_roles.py apply --cogstore cogstore --harden   # roles, schema.sql + sweep,
                                                                     # every org's role, the cog store, maintenance dbs
    sudo venv/bin/python devtools/cog_roles.py rotate org_astryx --env <org home>/.env   # password -> the org's DSN
    sudo venv/bin/python devtools/cog_roles.py rotate astryx_test --env <org home>/.env --key ASTRYX_TEST_DSN --db postgres
    sudo venv/bin/python devtools/cog_roles.py rotate astryx_cog --env <cog home>/.env --db cogstore
    venv/bin/python devtools/cog_roles.py census --env <org home>/.env --env <cog home>/.env   # rc 1 if any
                                                                     # DSN there still resolves to a superuser
    sudo venv/bin/python devtools/cog_roles.py counts --env <org home>/.env   # per tenant table: org role == super
A .env written while running as root keeps its owner and mode (the services read it as the org's user).

Names are parameters (`Names(prefix)`), so the oracles (tests/test_cog_roles.py, tests/test_rls_leak.py) run this
exact code on per-run roles on the shared cluster; production passes no prefix.
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))), "src"))
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))

import argparse
import hashlib
import os
import re
import secrets
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from astryx import config, orgs  # noqa: E402

SCHEMA = ROOT / "src" / "astryx" / "sql" / "schema.sql"
SUPER_FILE = Path(os.environ.get("ASTRYX_PG_SUPER_FILE") or "/etc/astryx/pg-super.dsn")
_NOT = "NOSUPERUSER NOREPLICATION"
KINDS = {   # kind -> (base name, attributes). ALTERed back to these on every apply: an attribute is never drift.
    "schema": ("astryx_schema", f"NOLOGIN {_NOT} NOCREATEDB NOCREATEROLE NOBYPASSRLS"),
    "org": ("astryx_org", f"NOLOGIN {_NOT} NOCREATEDB NOCREATEROLE NOBYPASSRLS"),
    "cog": ("astryx_cog", f"LOGIN {_NOT} NOCREATEDB NOCREATEROLE NOBYPASSRLS"),
    "test": ("astryx_test", f"LOGIN {_NOT} CREATEDB CREATEROLE BYPASSRLS"),
    "monitor": ("astryx_monitor", f"LOGIN {_NOT} NOCREATEDB NOCREATEROLE NOBYPASSRLS"),
}
ORG_ATTRS = f"LOGIN {_NOT} NOCREATEDB NOCREATEROLE NOBYPASSRLS"
BOOTSTRAP = "astryx"                       # OID 10 on the live cluster: never a runtime user


class Names:
    """Every role name this tool makes, from one prefix ('' in production)."""

    def __init__(self, prefix: str = ""):
        if not re.fullmatch(r"[a-z0-9_]*", prefix):
            raise ValueError("a role prefix is [a-z0-9_]*")
        self.prefix = prefix
        for kind, (base, _) in KINDS.items():
            setattr(self, kind, prefix + base)

    def org_role(self, key: str) -> str:
        return f"{self.prefix}org_{_slug(key)}"

    def all(self) -> list[str]:
        return [getattr(self, k) for k in KINDS]


def _slug(key: str) -> str:
    if not orgs.NAME.fullmatch(key):
        raise ValueError(f"org key {key!r} does not match {orgs.NAME.pattern}")
    return key.replace("-", "_")          # keys never hold '_', so this is one-to-one


def _sql():
    from psycopg import sql
    return sql


def _is_super(conn) -> bool:
    return bool(conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0])


def _exists(conn, role: str) -> bool:
    return conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone() is not None


def _own_set(conn, role: str) -> None:
    """A non-superuser provisioner (the oracles' CREATEROLE admin) must be able to SET ROLE to a role to give it
    objects (ALTER … OWNER TO) and to keep using the schemas it hands over; its creator holds only ADMIN by default
    since PG16."""
    if not _is_super(conn):
        sql = _sql()
        conn.execute(sql.SQL("GRANT {} TO CURRENT_USER WITH INHERIT TRUE, SET TRUE").format(sql.Identifier(role)))


def ensure_roles(admin, names: Names) -> list[str]:
    """The five group/service roles, created or put back to their declared attributes. Returns those created."""
    sql = _sql()
    made = []
    for kind, (_, attrs) in KINDS.items():
        role = getattr(names, kind)
        verb = "ALTER" if _exists(admin, role) else "CREATE"
        if verb == "CREATE":
            made.append(role)
        admin.execute(sql.SQL(f"{verb} ROLE {{}} {attrs}").format(sql.Identifier(role)))
        _own_set(admin, role)
    if _is_super(admin):                   # pg_monitor is grantable only by a superuser (or its admin)
        admin.execute(sql.SQL("GRANT pg_monitor TO {}").format(sql.Identifier(names.monitor)))
    return made


def password(admin, role: str, pw: str | None = None) -> str:
    """Set role's password to `pw` (default: a fresh random one) as a SCRAM verifier. Returns the plaintext."""
    from astryx.security.rotate_db_password import scram_verifier
    sql = _sql()
    pw = pw or secrets.token_urlsafe(24)
    admin.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(scram_verifier(pw))))
    return pw


def provision_db(conn, names: Names, schema_text: str | None = None) -> None:
    """In an org database, as its superuser (or a CREATEROLE owner holding SET on the roles): name the roles in
    cog.roles, then apply schema.sql whole when given (its last statement sweeps ownership and grants), else just the
    sweep. CONNECT on the database: the org group, the cog role and the monitor; PUBLIC loses it."""
    sql = _sql()
    if schema_text is not None:
        conn.execute(schema_text)
    conn.execute("INSERT INTO cog.roles (owner, org, cog, monitor) VALUES (%s, %s, %s, %s) ON CONFLICT (one) DO "
                 "UPDATE SET owner = EXCLUDED.owner, org = EXCLUDED.org, cog = EXCLUDED.cog, monitor = EXCLUDED.monitor",
                 (names.schema, names.org, names.cog, names.monitor))
    conn.execute("CALL cog.adopt()")
    db = sql.Identifier(conn.execute("SELECT current_database()").fetchone()[0])
    conn.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(db))
    conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(db, sql.Identifier(names.org),
                                                                         sql.Identifier(names.monitor)))


def ensure_org(conn, names: Names, key: str, parent: str | None = None, pw: str | None = None) -> str:
    """One org in this database: its LOGIN role (IN ROLE the org group and NOTHING else: any other membership is a
    SET ROLE escape from cog.tenant()) and its cog.orgs row. That is all an org is (owner ruling 11-13: adding
    an org = one row + one role). Idempotent. Returns the role. `pw` sets the password (else an existing one is kept)."""
    sql = _sql()
    I = sql.Identifier
    role = names.org_role(key)
    if _exists(conn, role):
        conn.execute(sql.SQL(f"ALTER ROLE {{}} {ORG_ATTRS}").format(I(role)))
    else:
        conn.execute(sql.SQL(f"CREATE ROLE {{}} {ORG_ATTRS} IN ROLE {{}}").format(I(role), I(names.org)))
    conn.execute(sql.SQL("GRANT {} TO {}").format(I(names.org), I(role)))
    for (other,) in conn.execute("SELECT g.rolname FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid "
                                 "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = %s AND g.rolname <> %s",
                                 (role, names.org)).fetchall():
        conn.execute(sql.SQL("REVOKE {} FROM {}").format(I(other), I(role)))
    if pw is not None:
        password(conn, role, pw)
    ppath = None
    if parent is not None:
        row = conn.execute("SELECT path FROM cog.orgs WHERE key = %s", (parent,)).fetchone()
        if row is None:
            raise LookupError(f"parent org {parent!r} is not in cog.orgs")
        ppath = row[0]
    conn.execute("INSERT INTO cog.orgs (key, parent, path, role) VALUES (%s, %s, %s, %s) ON CONFLICT (key) DO UPDATE "
                 "SET parent = EXCLUDED.parent, path = EXCLUDED.path, role = EXCLUDED.role",
                 (key, parent, f"{ppath}.{key}" if ppath else key, role))
    if conn.execute("SELECT to_regprocedure('cog.seed(text)')").fetchone()[0]:
        conn.execute("CALL cog.seed(%s)", (key,))          # its per-org seed rows (slice 3: they name their org)
    return role


def provision_cogstore(conn, names: Names) -> int:
    """The cog's own database (cogstore: users, sessions, links; cog_schema.sql) becomes the cog role's: its schema
    and every relation in it owned by astryx_cog, CONNECT for it alone. Run in that database as the provisioner.
    Returns the relations moved."""
    sql = _sql()
    I = sql.Identifier
    conn.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(I(names.cog)))
    n = 0
    for rel, kind in conn.execute(
            "SELECT c.oid::regclass::text, c.relkind FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace "
            "AND c.relkind IN ('r','p','v','m','S') AND c.relowner <> %s::regrole "
            "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid "
            "AND d.deptype = 'e') AND NOT (c.relkind = 'S' AND EXISTS (SELECT 1 FROM pg_depend d WHERE "
            "d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.refclassid = 'pg_class'::regclass "
            "AND d.deptype IN ('a','i')))", (names.cog,)).fetchall():
        what = {"v": "VIEW", "m": "MATERIALIZED VIEW", "S": "SEQUENCE"}.get(kind, "TABLE")
        conn.execute(sql.SQL(f"ALTER {what} {{}} OWNER TO {{}}").format(sql.SQL(rel), I(names.cog)))
        n += 1
    db = I(conn.execute("SELECT current_database()").fetchone()[0])
    conn.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(db))
    conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db, I(names.cog)))
    return n


def harden_cluster(admin, names: Names, dbs=("postgres", "template1")) -> None:
    """No PUBLIC CONNECT on the maintenance databases (RLS.md §2). The test role keeps CONNECT on the first (it has to
    stand somewhere to CREATE DATABASE) and so does the monitor. The oracle passes a scratch database instead."""
    sql = _sql()
    for d in dbs:
        admin.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(d)))
    admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
        sql.Identifier(dbs[0]), sql.Identifier(names.test), sql.Identifier(names.monitor)))


# ── the DSN side ─────────────────────────────────────────────────────────────────────────────────────────────────────
def role_dsn(base_dsn: str, role: str, pw: str, dbname: str | None = None) -> str:
    """base_dsn's server, `role` and `pw`, and its database unless one is named. Keeps the base's FORM: a URL stays a
    URL (asyncpg — the observatory's pool — accepts only postgresql:// URLs; make_conninfo always returns key=value,
    which a live rehearsal caught starting the observatory, 11-13); key=value stays key=value."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    kw = {"user": role, "password": pw}
    if dbname:
        kw["dbname"] = dbname
    if "://" not in base_dsn:
        return make_conninfo(base_dsn, **kw)
    from urllib.parse import quote, urlencode
    d = {**conninfo_to_dict(base_dsn), **kw}
    host, port, db = d.pop("host", ""), d.pop("port", ""), d.pop("dbname", "")
    user, pw_ = d.pop("user", ""), d.pop("password", "")
    auth = quote(user, safe="") + (":" + quote(pw_, safe="") if pw_ else "") + "@" if user else ""
    netloc = auth + ("[" + host + "]" if ":" in host else host) + (":" + str(port) if port else "")
    return f"postgresql://{netloc}/{quote(db, safe='')}" + ("?" + urlencode(d) if d else "")


def write_env(env: Path, key: str, value: str) -> None:
    """config.set_env, keeping the file's owner and mode when this runs as root (a sudo verb writing the org's .env)."""
    env = Path(env)
    st = env.stat() if env.exists() else None
    config.set_env(key, value, env)
    if st is not None and os.geteuid() == 0:
        os.chown(env, st.st_uid, st.st_gid)
        os.chmod(env, stat.S_IMODE(st.st_mode))


def stash_super(env: Path, to: Path) -> None:
    """Copy the .env's ASTRYX_DSN (it must be a SUPERUSER's) to `to`, 0600, never printed. The human then installs it
    root-only. Refuses a non-superuser DSN: that would lose the only key to the cluster."""
    import psycopg
    dsn = config.read_env(Path(env)).get("ASTRYX_DSN", "")   # org-home: the provisioner reads the .env it is NAMED (--env), by design
    if not dsn:
        raise SystemExit(f"cog_roles: no ASTRYX_DSN in {env}")
    with psycopg.connect(dsn, connect_timeout=5) as c:
        if not _is_super(c):
            raise SystemExit("cog_roles: that ASTRYX_DSN is not a superuser's; the credential was already moved?")
    to = Path(to)
    fd = os.open(to, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(dsn + "\n")


def super_dsn(path: Path | None = None) -> str:
    """The provisioner's DSN: ASTRYX_SUPER_DSN, else the root-only file. LookupError when neither is readable."""
    v = os.environ.get("ASTRYX_SUPER_DSN")
    if v:
        return v
    p = Path(path or SUPER_FILE)
    try:
        v = p.read_text().strip()
    except OSError:
        raise LookupError(f"no superuser DSN: {p} unreadable (run under sudo) and ASTRYX_SUPER_DSN unset") from None
    if not v:
        raise LookupError(f"{p} is empty")
    return v


def census(envs: list[Path], super_roles=None) -> list[str]:
    """Every DSN-valued key (*_DSN) in these .env files whose user is a superuser or the bootstrap role: sentences,
    never a value. `super_roles` is the set of superuser names (read from the server by the CLI; the oracle passes
    one). A DSN with no user resolves to the OS user, which is judged too."""
    from psycopg.conninfo import conninfo_to_dict
    bad = set(super_roles or ()) | {BOOTSTRAP}
    out = []
    for env in envs:
        for k, v in config.read_env(Path(env)).items():
            if not k.endswith("_DSN") or not v:
                continue
            try:
                user = conninfo_to_dict(v).get("user") or os.environ.get("PGUSER") or _os_user()
            except Exception:                              # noqa: BLE001 (an unparsable DSN is not judged here)
                continue
            if user in bad:
                out.append(f"{env}: {k} connects as {user!r}, a superuser (runtime must be org_<key>/astryx_cog/…)")
    return out


def _os_user() -> str:
    import pwd
    return pwd.getpwuid(os.geteuid()).pw_name


TENANT_TABLES_SQL = ("SELECT quote_ident(n.nspname) || '.' || quote_ident(c.relname) FROM pg_class c "
                     "JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_attribute a ON a.attrelid = c.oid "
                     "AND a.attname = 'tenant' AND NOT a.attisdropped WHERE n.nspname IN ('public', 'library') "
                     "AND c.relkind IN ('r', 'p') AND NOT c.relispartition ORDER BY 1")


def counts(super_conn, org_conn, key: str) -> list[str]:
    """The cutover check (DESIGN.md CORRECTIONS 11-13): for every tenant table, the rows the ORG role sees equal the
    rows of its tenant as the provisioner counts them (bypassing RLS), and it sees no other tenant's. Sentences."""
    out = []
    for (t,) in super_conn.execute(TENANT_TABLES_SQL).fetchall():
        want = super_conn.execute(f"SELECT count(*) FROM {t} WHERE tenant = %s", (key,)).fetchone()[0]
        try:
            got, other = org_conn.execute(f"SELECT count(*), count(*) FILTER (WHERE tenant <> %s) FROM {t}",
                                          (key,)).fetchone()
        except Exception as e:                       # noqa: BLE001 (a refused read is the finding)
            out.append(f"{t}: unreadable as the org ({type(e).__name__})")
            continue
        if got != want or other:
            out.append(f"{t}: the org sees {got} ({other} of other tenants), the provisioner counts {want}")
    return out


# ── the CLI ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def _org_keys() -> dict:
    """{key: {"home": Path, "primary": bool}} from the registry, or this checkout's one org ('astryx')."""
    reg = orgs.load()
    if not reg:
        return {"astryx": {"home": ROOT, "primary": True}}
    return reg


def cmd_apply(a) -> int:
    import psycopg
    names = Names(a.prefix)
    sdsn = super_dsn(a.super_file)
    with psycopg.connect(sdsn, autocommit=True) as admin:
        if not _is_super(admin):
            raise SystemExit("cog_roles: the provisioner DSN is not a superuser's")
        made = ensure_roles(admin, names)
        print(f"roles: {len(made)} created, {len(KINDS) - len(made)} kept ({', '.join(names.all())})")
    keys = _org_keys()
    dbname = a.db or "astryx"
    with psycopg.connect(_with_db(sdsn, dbname), autocommit=True) as c:
        body = SCHEMA.read_bytes()
        with c.transaction():
            provision_db(c, names, body.decode())
            c.execute("CREATE TABLE IF NOT EXISTS schema_applied (id int PRIMARY KEY CHECK (id = 1), sha text NOT NULL, "
                      "applied_at timestamptz NOT NULL DEFAULT now())")
            c.execute("INSERT INTO schema_applied (id, sha) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET sha = "
                      "EXCLUDED.sha, applied_at = now()", (hashlib.sha256(body).hexdigest(),))
            c.execute("CALL cog.adopt()")
            for key, e in sorted(keys.items(), key=lambda kv: not kv[1].get("primary")):
                if a.org and key != a.org:
                    continue
                role = ensure_org(c, names, key)
                print(f"org {key}: role {role}")
        # tenant arrived with a constant default (no rewrite), so it has no statistics until autovacuum happens to
        # analyze each table. Without them the planner guesses `tenant = (SELECT cog.tenant())` at 0.5% and, for "an
        # agent's latest N", sorts every row the tenant owns instead of walking an index (11-13 live: 4.7 ms -> 0.14).
        tabs = [r[0] for r in c.execute(
            "SELECT DISTINCT a.attrelid::regclass::text FROM pg_attribute a JOIN pg_class k ON k.oid = a.attrelid "
            "WHERE a.attname = 'tenant' AND NOT a.attisdropped AND k.relkind IN ('r', 'p') "
            "AND k.relnamespace = 'public'::regnamespace")]
        for t in tabs:
            c.execute(f"ANALYZE {t}")
        print(f"analyzed {len(tabs)} tenant table(s)")
    if a.cogstore:
        with psycopg.connect(_with_db(sdsn, a.cogstore), autocommit=True) as cs:
            print(f"cog store {a.cogstore}: {provision_cogstore(cs, names)} relation(s) given to {names.cog}")
    with psycopg.connect(sdsn, autocommit=True) as admin:
        if a.harden:
            harden_cluster(admin, names)
            print("cluster: PUBLIC CONNECT revoked on postgres, template1")
    return 0


def _with_db(dsn: str, dbname: str) -> str:
    from psycopg.conninfo import make_conninfo
    return make_conninfo(dsn, dbname=dbname)


def cmd_rotate(a) -> int:
    import psycopg
    sdsn = super_dsn(a.super_file)
    with psycopg.connect(sdsn, autocommit=True) as admin:
        if not _exists(admin, a.role):
            raise SystemExit(f"cog_roles: no role {a.role} (run apply first)")
        if admin.execute("SELECT rolsuper FROM pg_roles WHERE rolname = %s", (a.role,)).fetchone()[0]:
            raise SystemExit("cog_roles: refusing to write a superuser's password into a .env")
        pw = password(admin, a.role)
    env = Path(a.env)
    old = config.read_env(env).get(a.key, "")
    dsn = role_dsn(old or sdsn, a.role, pw, a.db)
    with psycopg.connect(dsn, connect_timeout=5) as c:            # canary: the new DSN authenticates as the role
        if c.execute("SELECT current_user").fetchone()[0] != a.role:
            raise SystemExit("cog_roles: the new DSN did not authenticate as the role; .env left as it was")
    write_env(env, a.key, dsn)
    print(f"{a.role}: password rotated; {a.key} in {env} now connects as {a.role}")
    return 0


def cmd_stash(a) -> int:
    stash_super(Path(a.env), Path(a.to))
    print(f"superuser DSN copied to {a.to} (0600). Install it root-only:\n"
          f"  sudo install -o root -g root -m 0600 {a.to} {SUPER_FILE} && shred -u {a.to}")
    return 0


def cmd_census(a) -> int:
    import psycopg
    supers = set()
    try:
        with psycopg.connect(super_dsn(a.super_file), connect_timeout=5) as c:
            supers = {r for (r,) in c.execute("SELECT rolname FROM pg_roles WHERE rolsuper").fetchall()}
    except (LookupError, psycopg.Error):
        pass                                  # judged by the bootstrap name alone
    bad = census([Path(e) for e in a.env], supers)
    for b in bad:
        print(f"  RED {b}")
    print(f"census: {'RED' if bad else 'GREEN'} ({len(a.env)} env file(s))")
    return 1 if bad else 0


def cmd_counts(a) -> int:
    import psycopg
    org = config.read_env(Path(a.env)).get("ASTRYX_DSN", "")   # org-home: the provisioner reads the .env it is NAMED (--env)
    from psycopg.conninfo import conninfo_to_dict
    with psycopg.connect(_with_db(super_dsn(a.super_file), conninfo_to_dict(org).get("dbname")), autocommit=True) as s, \
            psycopg.connect(org, autocommit=True) as o:
        key = o.execute("SELECT cog.tenant()").fetchone()[0]
        if key is None:
            print("counts: RED, the org DSN's role is not in cog.orgs")
            return 1
        n = len(s.execute(TENANT_TABLES_SQL).fetchall())
        bad = counts(s, o, key)
    for b in bad:
        print(f"  RED {b}")
    print(f"counts: {'RED' if bad else 'GREEN'} ({n} tenant tables, org {key})")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cog_roles", description=__doc__.split("\n")[0])
    ap.add_argument("--super-file", default=None, help=f"the superuser DSN file (default {SUPER_FILE})")
    ap.add_argument("--prefix", default="", help="role-name prefix: a rehearsal on a fixture (production passes none)")
    sub = ap.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("apply")
    p.add_argument("--org", default=None)
    p.add_argument("--db", default=None, help="the shared org database (default astryx)")
    p.add_argument("--harden", action="store_true", help="also revoke PUBLIC CONNECT on postgres and template1")
    p.add_argument("--cogstore", default=None, help="also give this cog-store database to astryx_cog (e.g. cogstore)")
    p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("rotate")
    p.add_argument("role")
    p.add_argument("--env", required=True)
    p.add_argument("--key", default="ASTRYX_DSN")
    p.add_argument("--db", default=None)
    p.set_defaults(fn=cmd_rotate)
    p = sub.add_parser("stash-super")
    p.add_argument("--env", required=True)
    p.add_argument("--to", required=True)
    p.set_defaults(fn=cmd_stash)
    p = sub.add_parser("census")
    p.add_argument("--env", action="append", required=True)
    p.set_defaults(fn=cmd_census)
    p = sub.add_parser("counts")
    p.add_argument("--env", required=True)
    p.set_defaults(fn=cmd_counts)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
