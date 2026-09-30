#!/usr/bin/env python3
"""branch_check PREP (plan-4918 P0 + P1 inputs): everything done as the admin role OUTSIDE the sandbox.

Nothing here mutates the live environment E. It READS prod (pg_dump), the live repo and the gitignored estate,
and it writes only inside the run's own scope: the databases its role owns, and its root directory.

  precondition   P0-b: every database the run doesn't own must NOT grant PUBLIC CONNECT. It's asked of the server
                 with has_database_privilege, which resolves a NULL (default) ACL. A text scan of datacl passes
                 vacuously on exactly today's unhardened state (a1's binding condition). Fail → refuse rc 77, naming
                 each database and seed's one-time P0-a statement. The tool never runs the REVOKE itself.
  base + clones  one pg_dump of prod → a per-run BASE owned by the run role; each side gets a fresh
                 CREATE DATABASE … TEMPLATE base, so both start from byte-identical state (R2).
  ext template   astryx_bctpl_<schema.sql sha12>: owner = the admin, CACHED across runs, IS_TEMPLATE true, PUBLIC
                 CONNECT revoked, evicted when the sha changes. It carries the extensions a non-superuser can't
                 create, so fixture_db under the run role still gets vector/postgis/age (a2's fail-open find).
  private repo   git archive <sha> → init → one commit. Never a shared worktree (a3 G2).
  estate         sqlguard ledger.estate_paths (never backup_inputs, which KEEPS .env). A file carrying a secret is
                 NOT copied; it's listed "VERIFIED NOTHING: carries a credential".
  branch secrets the branch's TRACKED tree is scanned too. A hit REFUSES, naming file:line, never the value
                 (a3 BC-2): a credential committed by a branch is what a pre-land check exists to stop.
  env            generated: the run role's DSN + an allowlist of non-secret keys. The live .env is never copied.

SECRET SET: derived here until plan-5497 ships its one secret_set(). Then this imports it (never a second copy).
"""
import hashlib
import os
import re
import shutil
import subprocess
import tarfile
import io
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg import sql

LIVE = Path(os.environ.get("ASTRYX_LIVE_REPO", "/home/umair/astryx"))
ENV_ALLOW = ("ASTRYX_ORG", "ASTRYX_URL", "ASTRYX_NODE", "WA_CLI", "WA_DATA_HOST", "WA_DATA_CTR", "TG_API_BASE",
             "GMAIL_ADDRESS", "GROWBOT_BODY_URL", "AUTOREMOTE_GETLOC_URL")      # declared NON-secret keys
P0A = "REVOKE CONNECT ON DATABASE {} FROM PUBLIC"
TPL_PREFIX = "astryx_bctpl_"
# The human-personal tier (local.md law): LINKED into the run and mounted READ-ONLY by the sandbox, never COPIED.
# A copy would put the tier's bytes in the run's tmp; a writable link would let a gate write THROUGH into live.
PRIVATE_TIER = ("tier", "owner.md", "relations.md")
TPL_EXTENSIONS = ("vector", "postgis", "age")


class Refuse(Exception):
    """A precondition failed: the run must not start. rc 77, reason named."""


def read_env(path: Path) -> dict:
    out = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def secret_set(live: Path = LIVE) -> set:
    """Every live .env value whose key isn't declared non-secret, plus every pgpass-file password, each raw and
    URL-encoded. Short values (<8) are dropped: they'd match everywhere and aren't credentials."""
    vals = {v for k, v in read_env(live / ".env").items() if k not in ENV_ALLOW}
    for pf in (Path(os.environ.get("PGPASSFILE", "")), Path.home() / ".pgpass"):
        if pf.is_file():
            for line in pf.read_text().splitlines():
                parts = re.split(r"(?<!\\):", line)
                if len(parts) >= 5:
                    vals.add(parts[4])
    for dsn in list(vals):                                  # a DSN's embedded password is a secret on its own
        m = re.match(r"\w+://[^:/@]+:([^@]+)@", dsn)
        if m:
            vals.add(m.group(1))
    vals = {v for v in vals if len(v) >= 8}
    return vals | {quote(v, safe="") for v in vals}


def carries_secret(path: Path, secrets_: set) -> int:
    """1-based line of the first secret occurrence, 0 if none. Binary-safe; the value is never returned."""
    try:
        data = path.read_bytes()
    except OSError:
        return 0
    for s in secrets_:
        i = data.find(s.encode())
        if i >= 0:
            return data.count(b"\n", 0, i) + 1
    return 0


# ── P0-b: the hardening precondition ───────────────────────────────────────────────────────────────────────
# DECLARED TRANSIENT databases (plan-4918 #28982): created continuously by the suites, each with a NULL ACL because
# Postgres has no default privileges for databases, so a one-time REVOKE can't cover them. Each prefix is LITERAL
# (matched with startswith, never an SQL LIKE whose "_" is a wildcard: a1 BC-1) and names its CREATOR (a1 BC-3).
# They hold no live listener, so the worst a run can do there is cross-talk into a concurrent test. Any database
# NOT matching is ACCUSED: an unknown member refuses the run until it's hardened or declared here.
TRANSIENT = {
    "astryx_fx_": "nucleus/sqlguard/fixture.py fixture_db: per run, dropped WITH (FORCE); REVOKEs PUBLIC at creation",
    "astryx_wakeprobe_": "tests/test_wake_recovery.py:138: per pid, dropped in its finally",
}


def transient(name: str) -> bool:
    return any(name.startswith(p) for p in TRANSIENT)


def unhardened(conn, run_role: str, own_templates=()) -> list:
    """Databases the run doesn't own that still grant PUBLIC CONNECT (a NULL ACL counts: the server resolves it).
    Evaluated PER MEMBER: one that errors (dropped between the listing and the check: a live race) is ACCUSED,
    never skipped (a1 BC-2). Declared transient names are excluded before evaluation."""
    names = [r[0] for r in conn.execute(
        "SELECT d.datname FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba "
        "WHERE d.datallowconn AND r.rolname <> %s ORDER BY 1", (run_role,))]
    bad = []
    for n in names:
        if n in own_templates or transient(n):
            continue
        try:
            if conn.execute("SELECT has_database_privilege('public', %s, 'CONNECT')", (n,)).fetchone()[0]:
                bad.append(n)
        except psycopg.Error:
            bad.append(f"{n} (unevaluable)")
    return bad


def require_hardened(conn, run_role: str):
    bad = unhardened(conn, run_role)
    if bad:
        raise Refuse("P0-b: these databases still grant PUBLIC CONNECT, so a run role could reach them (and "
                     "NOTIFY/LISTEN needs no grant). Seed's one-time host hardening (P0-a): "
                     + "; ".join(P0A.format(d) for d in bad))


# ── the fixture-extension template (cached, named, evicted by schema sha) ───────────────────────────────────
def schema_sha(repo: Path) -> str:
    return hashlib.sha256((repo / "nucleus" / "schema.sql").read_bytes()).hexdigest()[:12]


def ensure_ext_template(conn, sha12: str, keep=()) -> str:
    """The cached template for one schema.sql sha. Eviction drops OTHER shas' templates EXCEPT those in `keep`:
    a differential run needs main's AND the branch's at once when a branch changes schema.sql, so evicting
    "everything but mine" would make the two sides evict each other."""
    name = f"{TPL_PREFIX}{sha12}"
    keep = {f"{TPL_PREFIX}{k}" for k in keep} | {name}
    for (old,) in conn.execute("SELECT datname FROM pg_database WHERE datname LIKE %s AND NOT (datname = ANY(%s))",
                               (TPL_PREFIX.replace("_", "\\_") + "%", list(keep))).fetchall():   # "_" is a LIKE wildcard
        conn.execute(sql.SQL("ALTER DATABASE {} IS_TEMPLATE false").format(sql.Identifier(old)))
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(old)))     # evict stale sha
    if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        info = conn.info
        with psycopg.connect(host=info.host, port=info.port, user=info.user, password=info.password,
                             dbname=name, autocommit=True) as t:
            for ext in TPL_EXTENSIONS:
                t.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(sql.Identifier(ext)))
        conn.execute(sql.SQL("ALTER DATABASE {} IS_TEMPLATE true").format(sql.Identifier(name)))
        conn.execute(sql.SQL(P0A).format(sql.Identifier(name)))
    return name


# ── the private repo and the estate ─────────────────────────────────────────────────────────────────────────
def private_repo(live: Path, sha: str, dest: Path) -> Path:
    """`git archive <sha>` into dest, then init + ONE commit. The live repo is only READ."""
    dest.mkdir(parents=True)
    arc = subprocess.run(["git", "archive", sha], cwd=live, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(arc)) as t:
        t.extractall(dest, filter="tar")
    env = {**os.environ, "GIT_AUTHOR_NAME": "branch_check", "GIT_AUTHOR_EMAIL": "bc@local",
           "GIT_COMMITTER_NAME": "branch_check", "GIT_COMMITTER_EMAIL": "bc@local"}
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-q", "-m", f"branch_check {sha}"]):
        subprocess.run(cmd, cwd=dest, env=env, check=True, capture_output=True)
    return dest


def tracked_secret_hits(repo: Path, secrets_: set) -> list:
    """file:line of every tracked file carrying a secret (the value never leaves this function)."""
    files = subprocess.run(["git", "ls-files", "-z"], cwd=repo, capture_output=True, check=True).stdout.split(b"\0")
    hits = []
    for f in (x.decode() for x in files if x):
        ln = carries_secret(repo / f, secrets_)
        if ln:
            hits.append(f"{f}:{ln}")
    return hits


def copy_estate(live: Path, repo: Path, secrets_: set) -> dict:
    """Copy the derived estate into the private repo. Secret-bearing files are skipped and listed."""
    import sys
    sys.path.insert(0, str(live))
    from nucleus.sqlguard.ledger import estate_paths
    placed, skipped, linked = [], [], []
    for rel in estate_paths(live):
        rel = rel.rstrip("/")
        src, dst = live / rel, repo / rel
        if rel.split("/")[0] in PRIVATE_TIER:
            if src.exists() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.symlink_to(src)
            linked.append(rel)                                   # the sandbox ro-binds each of these live paths
            continue
        files = [src] if src.is_file() else [p for p in src.rglob("*") if p.is_file()] if src.is_dir() else []
        for f in files:
            r = f.relative_to(live)
            if carries_secret(f, secrets_):
                skipped.append(str(r))
                continue
            (repo / r).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, repo / r, follow_symlinks=True)
        placed.append(rel)
    return {"placed": placed, "skipped_credential": skipped, "linked_private": linked}


def write_env(repo: Path, run_dsn: str, live: Path = LIVE) -> Path:
    """The generated .env: the run role's DSN plus declared non-secret keys. Never the live file."""
    live_env = read_env(live / ".env")
    lines = [f"ASTRYX_DSN={run_dsn}"] + [f"{k}={live_env[k]}" for k in ENV_ALLOW if k in live_env]
    p = repo / ".env"
    p.write_text("\n".join(lines) + "\n")
    p.chmod(0o600)
    return p


# ── prod → base → clones ────────────────────────────────────────────────────────────────────────────────────
OWN_SQL = """
ALTER SCHEMA public OWNER TO {role};
DO $$ DECLARE r record; BEGIN
 FOR r IN SELECT c.oid::regclass AS o, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname NOT IN ('pg_catalog','information_schema','pg_toast') AND c.relkind IN ('r','p','v','m','S','f')
   AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid
                   AND (d.deptype = 'e' OR (c.relkind = 'S' AND d.deptype IN ('a','i')))) LOOP
   EXECUTE format('ALTER %s %s OWNER TO {role}', CASE r.relkind WHEN 'S' THEN 'SEQUENCE' WHEN 'v' THEN 'VIEW'
     WHEN 'm' THEN 'MATERIALIZED VIEW' ELSE 'TABLE' END, r.o); END LOOP;
 FOR r IN SELECT p.oid::regprocedure AS f FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
   WHERE n.nspname = 'public' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e') LOOP
   EXECUTE format('ALTER FUNCTION %s OWNER TO {role}', r.f); END LOOP;
 FOR r IN SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname NOT IN ('information_schema','public')
   AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = pg_namespace.oid AND d.deptype = 'e') LOOP
   EXECUTE format('ALTER SCHEMA %I OWNER TO {role}', r.nspname); END LOOP;
END $$;
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'ag_catalog') THEN
   GRANT USAGE ON SCHEMA ag_catalog TO {role};
   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ag_catalog TO {role};
 END IF; END $$;
"""


def _argv_safe(dsn: str, dbname: str):
    """(conninfo WITHOUT the password, child env WITH PGPASSWORD). A DSN on argv is readable by every process on
    the host via /proc/*/cmdline and `ps`, the plan-5497 class. The password travels in the child's env only."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    d = conninfo_to_dict(dsn)
    pw = d.pop("password", None)
    d["dbname"] = dbname
    env = {**os.environ}
    if pw:
        env["PGPASSWORD"] = pw
    return make_conninfo(**d), env


def build_base(scope, admin_dsn: str, prod_db: str) -> tuple:
    """pg_dump prod | pg_restore into a run-owned base, then hand every object to the run role (a2's measured
    transfer; identity sequences follow their table)."""
    base = scope.create_db(f"{scope.role}_base")
    from psycopg.conninfo import make_conninfo
    src, env = _argv_safe(admin_dsn, prod_db)
    dst, _ = _argv_safe(admin_dsn, base)
    dump = subprocess.Popen(["pg_dump", "-Fc", "-d", src], stdout=subprocess.PIPE, env=env)
    rest = subprocess.run(["pg_restore", "--no-owner", "-d", dst], stdin=dump.stdout, capture_output=True,
                          text=True, env=env)
    dump.stdout.close()
    dump.wait()
    with psycopg.connect(make_conninfo(admin_dsn, dbname=base), autocommit=True) as c:
        c.execute(OWN_SQL.format(role=sql.Identifier(scope.role).as_string(c)))
    return base, rest.returncode, len([l for l in rest.stderr.splitlines() if "error" in l.lower()])
