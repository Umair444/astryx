#!/usr/bin/env python3
"""branch_check PREP oracle (plan-4918 P0/P1): the hardening precondition, the cached extension template, the
private repo, the estate copy and the generated env. Synthetic repos and FAKE secrets; one real pg_dump of prod
into a run-owned base (torn down). Exits 77 without a DSN that can CREATE ROLE/DATABASE.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
fails = []
FAKE = "fAkE-sEcReT-4918-" + "x" * 12                            # never a real credential


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def admin_dsn():
    if os.environ.get("ASTRYX_DSN"):
        return os.environ["ASTRYX_DSN"]
    for line in ((REPO / ".env").read_text().splitlines() if (REPO / ".env").is_file() else []):
        if line.startswith("ASTRYX_DSN="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def git(cwd, *a):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *a], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout


def synthetic_live(tmp: Path) -> Path:
    """A tiny live repo: tracked code, a gitignored estate (one plain file, one carrying the fake secret), a .env."""
    live = tmp / "live"
    (live / "nucleus" / "sqlguard").mkdir(parents=True)
    shutil.copy2(REPO / "nucleus" / "sqlguard" / "ledger.py", live / "nucleus" / "sqlguard" / "ledger.py")
    for f in ("__init__.py", "privacy.py", "judge.py", "inventory.py", "normalize.py", "drivers.py", "fixture.py"):
        src = REPO / "nucleus" / "sqlguard" / f
        if src.exists():
            shutil.copy2(src, live / "nucleus" / "sqlguard" / f)
    (live / "nucleus" / "__init__.py").write_text("")
    (live / "nucleus" / "schema.sql").write_text("-- synthetic\n")
    (live / "code.py").write_text("x = 1\n")
    (live / ".gitignore").write_text("triggers/\n.env\n")
    (live / "triggers" / "t").mkdir(parents=True)
    (live / "triggers" / "t" / "plain.py").write_text("y = 2\n")
    (live / "triggers" / "t" / "leaky.py").write_text(f"a = 1\nDSN = 'postgresql://u:{FAKE}@h/db'\n")
    (live / ".env").write_text(f"ASTRYX_DSN=postgresql://u:{FAKE}@h/db\nASTRYX_ORG=org.test\nOPENAI_API_KEY=sk-{FAKE}\n")
    git(live, "init", "-q")
    git(live, "add", "-A")
    git(live, "commit", "-q", "-m", "base")
    return live


def main():
    dsn = admin_dsn()
    if not dsn:
        print("NOT SEARCHED: no ASTRYX_DSN. Nothing was verified.")
        return 77
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    try:
        src = os.environ.get("BRANCH_CHECK_PREP_SRC")                 # mutation_probe points this at a mutant copy
        if src:
            import importlib.util
            spec = importlib.util.spec_from_file_location("bcprep_under_test", src)
            bp = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bp)
        else:
            from nucleus import branch_check_prep as bp
        from nucleus import runscope as rs
    except ImportError as e:
        check("branch_check_prep importable", False, str(e))
        return 1
    adm = psycopg.connect(dsn, autocommit=True)
    sys.path.insert(0, str(REPO / "tests"))
    from _oracle_debris import ORACLE_BASE, TEST_DB, reap
    TEST_NAME = lambda n: bool(TEST_DB.match(n))
    reap(adm)                                                    # a killed earlier run's debris, by raw SQL
    tmp = Path(tempfile.mkdtemp(prefix="bcprep-oracle-"))
    made_dbs, scope = [], None
    try:
        # ── P0-b: the hardening precondition (a1's binding NULL-ACL arm) ──────────────────────────────────
        scope = rs.RunScope(dsn, root=ORACLE_BASE).open()
        nul = f"{scope.role}_nullacl"
        adm.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nul)))      # admin-owned, NULL datacl
        made_dbs.append(nul)
        acl = adm.execute("SELECT datacl FROM pg_database WHERE datname=%s", (nul,)).fetchone()[0]
        check("fixture: the probe DB has a NULL (default) ACL", acl is None, str(acl))
        check("P0-b: a NULL-ACL database the run doesn't own is UNHARDENED (the server resolves the default)",
              nul in bp.unhardened(adm, scope.role), "")
        adm.execute(sql.SQL(bp.P0A).format(sql.Identifier(nul)))
        check("P0-b control: after the P0-a REVOKE it is hardened", nul not in bp.unhardened(adm, scope.role), "")
        own = scope.create_db(f"{scope.role}_own")
        check("P0-b: a database the RUN owns is never counted", own not in bp.unhardened(adm, scope.role), "")
        try:
            bp.require_hardened(adm, "no_such_role_x")        # every DB counts → on an unhardened host this refuses
            refused = not bp.unhardened(adm, "no_such_role_x")
        except bp.Refuse as e:
            refused = "REVOKE CONNECT ON DATABASE" in str(e)
        check("require_hardened refuses with seed's P0-a statement whenever anything is unhardened", refused, "")

        # ── the cached extension template (P0-c; keep set; LIKE escape) ──────────────────────────────────
        existing = {r[0][len(bp.TPL_PREFIX):] for r in adm.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE 'astryx\\_bctpl\\_%'") if not TEST_NAME(r[0])}
        pid = os.getpid()
        mine = f"t_{pid}"                                          # test-only names carry the pid (see _oracle_debris)
        stale = f"astryx_bctpl_zz_{pid}"
        decoy = f"astryxQbctplQ_{pid}"                            # matches only if "_" were a wildcard
        kept = f"astryx_bctpl_zk_{pid}"                           # a planted KEPT template: the arm can't be vacuous
        for d in (stale, decoy, kept):
            adm.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(d)))
            made_dbs.append(d)
        tpl = bp.ensure_ext_template(adm, mine, keep=existing | {kept[len(bp.TPL_PREFIX):]})
        made_dbs.append(tpl)
        row = adm.execute("SELECT datistemplate, has_database_privilege('public', datname, 'CONNECT') "
                          "FROM pg_database WHERE datname=%s", (tpl,)).fetchone()
        check("the extension template is IS_TEMPLATE and grants no PUBLIC CONNECT", row == (True, False), str(row))
        gone = lambda d: not adm.execute("SELECT 1 FROM pg_database WHERE datname=%s", (d,)).fetchone()
        check("a stale-sha template NOT in keep is evicted", gone(stale), "")
        check("eviction never touches a lookalike name ('_' is escaped in LIKE)", not gone(decoy), "")
        check("eviction keeps every template in the keep set (a planted one included)",
              not gone(kept) and all(not gone(bp.TPL_PREFIX + k) for k in existing), "")
        clone = f"{scope.role}_fx"
        with psycopg.connect(scope.dsn(own), autocommit=True) as rc_:        # AS THE RUN ROLE (P0-c)
            rc_.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(clone), sql.Identifier(tpl)))
        with psycopg.connect(scope.dsn(clone), autocommit=True) as fc:
            exts = {r[0] for r in fc.execute("SELECT extname FROM pg_extension")}
        check("P0-c: the NOSUPERUSER run role clones the template, and the clone HAS the extensions",
              set(bp.TPL_EXTENSIONS) <= exts, str(sorted(exts)))

        # ── private repo, estate copy, secrets, env ──────────────────────────────────────────────────────
        live = synthetic_live(tmp)
        before = git(live, "status", "--porcelain", "--ignored")
        repo = bp.private_repo(live, git(live, "rev-parse", "HEAD").strip(), tmp / "run" / "repo")
        check("private repo: ONE commit of the tree, the live repo only read",
              git(repo, "rev-list", "--count", "HEAD").strip() == "1" and (repo / "code.py").is_file()
              and git(live, "status", "--porcelain", "--ignored") == before, "")
        secrets_ = bp.secret_set(live)
        check("secret_set derives the non-allowlisted .env values (and the DSN's embedded password), not allowlisted ones",
              FAKE in secrets_ and f"sk-{FAKE}" in secrets_ and "org.test" not in secrets_, "")
        rep = bp.copy_estate(live, repo, secrets_)
        check("estate: a plain gitignored file is copied", (repo / "triggers/t/plain.py").is_file(), str(rep))
        check("estate: a file carrying a secret is NOT copied, and is listed",
              not (repo / "triggers/t/leaky.py").exists() and "triggers/t/leaky.py" in rep["skipped_credential"],
              str(rep))
        check("estate: .env is never copied (estate_paths excludes it)", not (repo / ".env").exists(), "")
        (repo / "leak.py").write_text(f"k = '{FAKE}'\n")
        git(repo, "add", "leak.py")
        git(repo, "commit", "-q", "-m", "a branch that commits a credential")
        hits = bp.tracked_secret_hits(repo, secrets_)
        check("branch tree: a committed credential is found as file:line, the value never in the output (a3 BC-2)",
              "leak.py:1" in hits and not any(FAKE in h for h in hits), str(hits))
        envp = bp.write_env(repo, "postgresql://run@127.0.0.1/x", live)
        text = envp.read_text()
        check("generated .env: the run DSN + allowlisted keys only, mode 600",
              "ASTRYX_DSN=postgresql://run@" in text and "ASTRYX_ORG=org.test" in text and FAKE not in text
              and oct(envp.stat().st_mode)[-3:] == "600", "")
        ci, env = bp._argv_safe(dsn, "x")
        pw = conninfo_to_dict(dsn).get("password")
        check("pg_dump/pg_restore argv carries no password (it travels in the child env only)",
              bool(pw) and pw not in ci and env.get("PGPASSWORD") == pw, "")

    finally:
        if scope:
            scope.close()
        for d in made_dbs:
            if not d.startswith(bp.TPL_PREFIX) or d.startswith(("astryx_bctpl_zz_", "astryx_bctpl_zk_", "astryx_bctpl_t_")):
                if adm.execute("SELECT 1 FROM pg_database WHERE datname=%s", (d,)).fetchone():
                    adm.execute(sql.SQL("ALTER DATABASE {} IS_TEMPLATE false").format(sql.Identifier(d)))
                    adm.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(d)))
        shutil.rmtree(tmp, ignore_errors=True)
        adm.close()
    print(f"\n{'FAIL' if fails else 'PASS'}: branch_check prep ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
