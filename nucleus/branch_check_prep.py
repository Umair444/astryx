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

SECRET SET: imported from nucleus.secretset (plan-5497's ONE authority), never derived here. The env allowlist is
secretset.NOT_SECRET's WHOLE-KEY entries only; a "KEY:param" entry exempts one URL parameter, never its key. A local
list had drifted: it declared AUTOREMOTE_GETLOC_URL non-secret although its `key=` is a credential (a3 #32077 R2).
"""
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg import sql

LIVE = Path(os.environ.get("ASTRYX_LIVE_REPO", "/home/umair/astryx"))
from nucleus import secretset                                  # noqa: E402 (the ONE secret authority)

ENV_ALLOW = tuple(sorted(k for k in secretset.NOT_SECRET if ":" not in k))  # whole-key non-secret entries only
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


def secret_set(live: Path = LIVE) -> list:
    """secretset's Secret list for the LIVE holders (the live .env, the reachable pgpass file)."""
    return secretset.secret_set(env_file=live / ".env")


def carries_secret(path: Path, secrets_) -> int:
    """1-based line of the first occurrence of any FORM of any secret, 0 if none. Binary-safe; never returns a value."""
    try:
        data = path.read_bytes()
    except OSError:
        return 0
    for sec in secrets_:
        for form in sec.forms:
            i = data.find(form.encode())
            if i >= 0:
                return data.count(b"\n", 0, i) + 1
    return 0


# ── P0-b: the hardening precondition ───────────────────────────────────────────────────────────────────────
# DECLARED TRANSIENT databases (plan-4918 #28982): created continuously by the suites, each with a NULL ACL because
# Postgres has no default privileges for databases, so a one-time REVOKE can't cover them. Each prefix is LITERAL
# (matched with startswith, never an SQL LIKE whose "_" is a wildcard: a1 BC-1) and names its CREATOR (a1 BC-3).
# They hold no live listener, so the worst a run can do there is cross-talk into a concurrent test. Any database
# NOT matching is ACCUSED: an unknown member refuses the run until it's hardened or declared here.
# If an entry is ever re-added it is (regex, creator); an exemption then holds only while the parsed creator pid is
# alive (a2 #32775), a dead one is a LEAK, an unparseable name is accused. But see W1 below before re-adding.
TRANSIENT = {}      # EMPTY, and pinned by an arm: every creator is zero-window now (fixture_db, test_wake_recovery).
                    # Re-adding a prefix is a DECISION: under the sandbox's --unshare-pid, a pid parsed from a name
                    # is a NAMESPACE pid (2, 3 …) that the host sees as a live kernel thread (a3 #32897 W1), so a
                    # pid-keyed exemption can't be trusted; fix the creator instead.


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def transient(name: str):
    """True: a declared transient whose creator is ALIVE (exempt). A str: why it's a LEAK (dead or unparseable
    creator: accused). False: not a declared class at all (accused as unhardened)."""
    for prefix, (rx, _creator) in TRANSIENT.items():
        if name.startswith(prefix):
            m = rx.match(name)
            if not m:
                return "leak: declared prefix but no parseable creator pid"
            return True if _pid_alive(int(m.group(1))) else f"leak: creator pid {m.group(1)} is gone"
    return False


def unhardened(conn, run_role: str, own_templates=()) -> list:
    """Databases the run doesn't own that still grant PUBLIC CONNECT (a NULL ACL counts: the server resolves it).
    Evaluated PER MEMBER: one that errors (dropped between the listing and the check: a live race) is ACCUSED,
    never skipped (a1 BC-2). Declared transient names are excluded before evaluation."""
    names = [r[0] for r in conn.execute(
        "SELECT d.datname FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba "
        "WHERE d.datallowconn AND r.rolname <> %s ORDER BY 1", (run_role,))]
    bad = []
    for n in names:
        t = transient(n)
        if n in own_templates or t is True:
            continue
        if isinstance(t, str):
            bad.append(f"{n} ({t})")
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


# AGE's schema is owned by the admin that created the extension, so a run role can't even SEE cypher() without USAGE
# (plan-4918 D1, measured). Granted to PUBLIC, and ONLY inside run-owned databases and the cached template (both have
# PUBLIC CONNECT revoked): the template outlives any one run role (a3 C1c). Idempotent; a no-op without AGE.
AGE_USAGE = ("DO $$ BEGIN IF to_regnamespace('ag_catalog') IS NOT NULL "
             "AND NOT has_schema_privilege('public', 'ag_catalog', 'USAGE') THEN "
             "GRANT USAGE ON SCHEMA ag_catalog TO PUBLIC; END IF; END $$")


def ensure_ext_template(conn, sha12: str, keep=(), prefix: str = TPL_PREFIX, evict: bool = True) -> str:
    """The cached template for one schema.sql sha. Eviction drops OTHER shas' templates EXCEPT those in `keep`:
    a differential run needs main's AND the branch's at once when a branch changes schema.sql, so evicting
    "everything but mine" would make the two sides evict each other.
    SCOPE (seed #34141): eviction only ever sees EXACT names in its own namespace, `^<prefix><12 hex>$`. A
    concurrent oracle's templates live under their own pid-scoped prefix, and a longer or foreign name never
    matches, so one caller can't drop a template another is cloning from. Across concurrent REAL runs the caller
    passes evict=False (branch_check.run does, while any other scope is alive): a run with another schema sha is
    still using its template."""
    if not re.fullmatch(r"[a-z0-9_]+", prefix):
        raise ValueError(f"template prefix {prefix!r}: only [a-z0-9_], so it is literal inside a regex")
    name = f"{prefix}{sha12}"
    keep = {f"{prefix}{k}" for k in keep} | {name}
    if evict:
        for (old,) in conn.execute("SELECT datname FROM pg_database WHERE datname ~ %s AND NOT (datname = ANY(%s))",
                                   (f"^{prefix}[0-9a-f]{{12}}$", list(keep))).fetchall():
            conn.execute(sql.SQL("ALTER DATABASE {} IS_TEMPLATE false").format(sql.Identifier(old)))
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(old)))     # evict stale sha
    if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
        # zero window (a3 #32077 R3): born closed, PUBLIC revoked, then opened for the extension build
        conn.execute(sql.SQL("CREATE DATABASE {} ALLOW_CONNECTIONS false").format(sql.Identifier(name)))
        conn.execute(sql.SQL(P0A).format(sql.Identifier(name)))
        conn.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS true").format(sql.Identifier(name)))
        info = conn.info
        with psycopg.connect(host=info.host, port=info.port, user=info.user, password=info.password,
                             dbname=name, autocommit=True) as t:
            for ext in TPL_EXTENSIONS:
                t.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(sql.Identifier(ext)))
        conn.execute(sql.SQL("ALTER DATABASE {} IS_TEMPLATE true").format(sql.Identifier(name)))
    info = conn.info                                   # a template cached before D1 lacks the grant: add it once
    with psycopg.connect(host=info.host, port=info.port, user=info.user, password=info.password,
                         dbname=name, autocommit=True) as t:
        t.execute(AGE_USAGE)
    return name


# ── the private repo and the estate ─────────────────────────────────────────────────────────────────────────
def private_repo(live: Path, sha: str, dest: Path, main_sha: str = None) -> Path:
    """A repo of exactly TWO refs, `main` and the side's sha (checked out, detached), WITH their history (plan-4918
    D2: econ provenance needs `main`, ship_watch needs spawn.sh's history). Fetched over file://, which is a PACK
    transfer: only objects those two refs reach arrive. Never a local clone, which hardlinks the whole object store,
    dangling blobs, stashes and every other branch included (a3 C2a). The live repo is only READ."""
    dest.mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=dest, check=True, capture_output=True)
    run("init", "-q", "-b", "bc_unborn")                   # never "main": fetching into a checked-out branch fails
    refs = [f"{main_sha or sha}:refs/heads/main"] + ([f"{sha}:refs/heads/branch_check"] if main_sha else [])
    run("fetch", "-q", "--no-tags", f"file://{live}", *refs)
    run("checkout", "-q", "--detach", sha)
    return dest


def history_secret_hits(repo: Path, secrets_) -> list:
    """Every commit in the repo's history whose DIFF or MESSAGE carries a form of a secret, as "<sha12> (diff|message)"
    (a3 C2a/C2b). The sandbox can read all of it now, so the scan covers all of it: `-S` alone sees diffs, never a
    secret pasted into a message. One pass over `git log --all -p --text`. The value never leaves this function.
    DECLARED residual: only CURRENT values are known; one committed and since rotated is invisible here."""
    forms = [f.encode() for sec in secrets_ for f in sec.forms if f]
    p = subprocess.Popen(["git", "log", "--all", "-p", "--text", "--no-color", "--no-ext-diff",
                          "--format=%x00%H%n%B"], cwd=repo, stdout=subprocess.PIPE)
    hits, cur, in_msg = [], None, False
    for line in p.stdout:
        if line.startswith(b"\x00"):
            cur, in_msg = line[1:13].decode(), True
            continue
        if in_msg and line.startswith(b"diff --git"):
            in_msg = False
        if cur and any(f in line for f in forms):
            h = f"{cur} ({'message' if in_msg else 'diff'})"
            if h not in hits:
                hits.append(h)
    if p.wait() != 0:
        raise Refuse("the history secret scan couldn't read the repo's history")
    return hits


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


def write_env(repo: Path, run_dsn: str, live: Path = LIVE, node: Path = None) -> Path:
    """The generated .env: the run role's DSN plus declared non-secret keys. Never the live file. `node` replaces
    the live ASTRYX_NODE (possibly a mise shim, unusable inside the sandbox) with the resolved binary (D3)."""
    live_env = read_env(live / ".env")
    if node:
        live_env = {**live_env, "ASTRYX_NODE": str(node)}
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
        c.execute(AGE_USAGE)                           # prod's own ag_catalog ACL is never touched (a3 C1c)
    return base, rest.returncode, len([l for l in rest.stderr.splitlines() if "error" in l.lower()])
