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
ARKEY = "fAkEaRkEy4918" + "y" * 10                               # a fake AUTOREMOTE `key=` value


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
    (live / ".gitignore").write_text("triggers/\n.env\ntier/\n")
    (live / "tier").mkdir()
    (live / "tier" / "personal.md").write_text("human-personal tier: never copied\n")
    (live / "triggers" / "t").mkdir(parents=True)
    (live / "triggers" / "t" / "plain.py").write_text("y = 2\n")
    (live / "triggers" / "t" / "leaky.py").write_text(f"a = 1\nDSN = 'postgresql://u:{FAKE}@h/db'\n")
    (live / ".env").write_text(f"ASTRYX_DSN=postgresql://u:{FAKE}@h/db\nASTRYX_ORG=org.test\nOPENAI_API_KEY=sk-{FAKE}\n"
                               f"AUTOREMOTE_GETLOC_URL=https://ar.example/x?key={ARKEY}&message=hello\n")
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
    if not adm.execute("SELECT rolcreaterole AND rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:
        print("NOT SEARCHED: this role can't CREATE ROLE/DATABASE (e.g. branch_check's own run role). Nothing was verified.")
        return 77
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
        # a1 BC-1: the exemption is a LITERAL prefix, never a LIKE: lookalikes are ACCUSED, a real one exempt
        pid = os.getpid()
        look = [f"astryxAfxBprod_{pid}", f"astryx-fx-prod-{pid}"]
        real_fx = f"astryx_fx_bcx_{pid}"                        # an OPEN fixture: a creator regression now
        live_wp = f"astryx_wakeprobe_{pid}"                        # the declared class, creator ALIVE (this pid)
        deadp = subprocess.Popen(["true"]); deadp.wait()
        dead_wp = f"astryx_wakeprobe_{deadp.pid}"                  # the declared class, creator GONE (the 3730269 case)
        for d in look + [real_fx, live_wp, dead_wp]:
            adm.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(d)))
            made_dbs.append(d)
        uh = bp.unhardened(adm, scope.role)
        check("BC-1: lookalike names ('_' as a wildcard would exempt them) are ACCUSED", all(d in uh for d in look), str(uh))
        check("a2 BC: an open astryx_fx_ DB is ACCUSED (fixture_db is zero-window now, so it's a creator regression)",
              real_fx in uh, str(uh))
        check("W1: TRANSIENT is EMPTY (pinned; a re-added prefix is a decision, and pid-keyed liveness is unsound "
              "under --unshare-pid)", bp.TRANSIENT == {}, str(bp.TRANSIENT))
        check("W1: an open wakeprobe DB is ACCUSED like any other, whatever pid its name carries",
              live_wp in uh and dead_wp in uh, str(uh))

        class Flaky:                                                  # a1 BC-2: a member that errors is ACCUSED
            def __init__(self, real, bad):
                self.real, self.bad = real, bad
            def execute(self, q, params=()):
                if "has_database_privilege" in q and params and params[0] == self.bad:
                    raise psycopg.errors.InvalidCatalogName("dropped mid-check")
                return self.real.execute(q, params)
        uh2 = bp.unhardened(Flaky(adm, nul), scope.role)
        check("BC-2: a member whose check ERRORS (dropped mid-check) is ACCUSED as unevaluable, never skipped",
              f"{nul} (unevaluable)" in uh2, str(uh2))
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
        class Rec:                                                    # records the statements, delegates the rest
            def __init__(self, real):
                self.real, self.seq, self.info = real, [], real.info
            def execute(self, q, params=None):
                s = q.as_string(self.real) if hasattr(q, "as_string") else str(q)
                if "DATABASE" in s:
                    self.seq.append(s)
                return self.real.execute(q, params) if params is not None else self.real.execute(q)
        rec = Rec(adm)
        tpl = bp.ensure_ext_template(rec, mine, keep=existing | {kept[len(bp.TPL_PREFIX):]})
        tseq = [q for q in rec.seq if tpl in q]
        check("R3: the template is born CLOSED, then REVOKE, then opened",
              len(tseq) >= 3 and "ALLOW_CONNECTIONS false" in tseq[0] and tseq[1].startswith("REVOKE CONNECT")
              and "ALLOW_CONNECTIONS true" in tseq[2], str(tseq[:3]))
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

        # ── fixture_db AS THE RUN ROLE: the template hook is what gives it the extensions (a2's fail-open) ───
        froot = tmp / "froot"
        (froot / "nucleus").mkdir(parents=True)
        shutil.copy2(REPO / "nucleus" / "schema.sql", froot / "nucleus" / "schema.sql")
        (froot / ".env").write_text(f"ASTRYX_DSN={scope.dsn(own)}\n")
        def _private_trace(e):
            # This child is RE-ROOTED at a fake repo (ASTRYX_SQLGUARD_ROOT), so its shim can't attribute a frame to
            # the real one: under check.sh its probe SQL read BLIND as ?::? (seed #33150). Like test_sqlguard's
            # _env, a re-rooted child traces into its OWN dir, never the estate's.
            if "ASTRYX_SQLGUARD_DIR" in e:
                d = tmp / f"trace-{len(list(tmp.glob('trace-*')))}"
                d.mkdir()
                e["ASTRYX_SQLGUARD_DIR"] = str(d)
        probe_fx = ("import os,sys,json,psycopg,importlib.util; sys.path.insert(0, sys.argv[1])\n"
                    "seq, real = [], psycopg.Connection.execute\n"      # the helper's statement sequence (a3 BC-5)
                    "def spy(self, q, *a, **k):\n    s = str(q)\n    seq.append(s) if 'DATABASE' in s else None\n    return real(self, q, *a, **k)\n"
                    "psycopg.Connection.execute = spy\n"
                    "src = os.environ.get('SQLGUARD_FIXTURE_SRC')\n"      # mutation_probe swaps fixture.py here
                    "if src:\n    sp = importlib.util.spec_from_file_location('fixture', src); fixture = importlib.util.module_from_spec(sp); sp.loader.exec_module(fixture)\n"
                    "else:\n    from nucleus.sqlguard import fixture\n"
                    "with fixture.fixture_db() as fx:\n"
                    "    c = psycopg.connect(fx['dsn'])\n"
                    "    ex = sorted(r[0] for r in c.execute('select extname from pg_extension'))\n"
                    "    pub = c.execute(\"select has_database_privilege('public', current_database(), 'CONNECT')\").fetchone()[0]\n"
                    "    print(json.dumps({'exts': ex, 'public': pub, 'seq': seq})); c.close()")
        def fx_exts(template):
            e = {**os.environ, "ASTRYX_SQLGUARD_ROOT": str(froot), "ASTRYX_SQLGUARD_RUN": f"bco{os.getpid()}"}
            _private_trace(e)
            e.pop("ASTRYX_FIXTURE_TEMPLATE", None)
            if template:
                e["ASTRYX_FIXTURE_TEMPLATE"] = template
            r = subprocess.run([sys.executable, "-c", probe_fx, str(REPO)], env=e, capture_output=True, text=True, timeout=120)
            return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]
        import json as _json
        def parsed(s):
            try:
                return _json.loads(s)
            except ValueError:
                return {"exts": [], "public": None, "raw": s}
        bare, templ = parsed(fx_exts(None)), parsed(fx_exts(tpl))
        check("fail-open reproduced: a NOSUPERUSER fixture WITHOUT the template lacks the extensions",
              "vector" not in bare["exts"], str(bare))
        check("fixture_db under the run role WITH ASTRYX_FIXTURE_TEMPLATE has vector/postgis/age",
              all(x in templ["exts"] for x in ("vector", "postgis", "age")), str(templ))
        seq = [s.split('"')[0].strip() for s in templ.get("seq", [])][:3]
        check("BC-5: no window: CREATE … ALLOW_CONNECTIONS false, then REVOKE, then ALTER … ALLOW_CONNECTIONS true",
              len(seq) == 3 and seq[0].startswith("CREATE DATABASE") and "ALLOW_CONNECTIONS false" in templ["seq"][0]
              and seq[1].startswith("REVOKE CONNECT") and "ALLOW_CONNECTIONS true" in templ["seq"][2], str(templ.get("seq")))
        check("BC-4: fixture_db REVOKEs PUBLIC CONNECT at creation, verified by the SERVER (not datacl)",
              templ["public"] is False and bare["public"] is False, f"{bare.get('public')} {templ.get('public')}")

        # ── fixture.url() over a UNIX SOCKET: the sandbox's only route (first e2e #33638, sqlguard P1's asyncpg) ──
        import asyncio
        import importlib.util
        fsrc = os.environ.get("SQLGUARD_FIXTURE_SRC")
        if fsrc:
            fsp = importlib.util.spec_from_file_location("fixture_under_test", fsrc)
            fxmod = importlib.util.module_from_spec(fsp)
            fsp.loader.exec_module(fxmod)
        else:
            from nucleus.sqlguard import fixture as fxmod
        from nucleus import branch_check_sandbox as sbx
        sdir = tmp / "sock"
        sdir.mkdir()
        sock_url = fxmod.url(scope.dsn(own, socket_dir=sdir))
        check("url(): a socket directory rides in ?host=, never in the authority",
              "@/" + own + "?host=" in sock_url and str(sdir) not in sock_url.split("?")[0], sock_url.split("@")[-1])
        try:
            import asyncpg
        except ModuleNotFoundError:
            asyncpg = None
        if asyncpg is None:
            print("  NOTE  asyncpg absent: the socket-connect arm didn't run")
        else:
            async def _via_socket():
                con = await asyncpg.connect(sock_url, timeout=10)
                try:
                    return await con.fetchval("SELECT current_database()")
                finally:
                    await con.close()
            with sbx.PgBridge(sdir):
                try:
                    got = asyncio.run(_via_socket())
                except Exception as e:                                  # the arm's verdict, reported by name
                    got = f"{type(e).__name__}: {e}"
            check("asyncpg connects through the bridge SOCKET with url()'s URL", got == own, str(got)[:200])

        # ── FixtureUnavailable: the ENVIRONMENT class only; a broken schema.sql propagates as itself (a1 #31528) ──
        probe_ex = ("import os,sys,importlib.util; sys.path.insert(0, sys.argv[1])\n"
                    "src = os.environ.get('SQLGUARD_FIXTURE_SRC')\n"
                    "if src:\n    sp = importlib.util.spec_from_file_location('fixture', src); fixture = importlib.util.module_from_spec(sp); sp.loader.exec_module(fixture)\n"
                    "else:\n    from nucleus.sqlguard import fixture\n"
                    "try:\n    with fixture.fixture_db() as fx: print('OPENED')\n"
                    "except fixture.FixtureUnavailable: print('FixtureUnavailable')\n"
                    "except Exception as e: print(type(e).__module__ + '.' + type(e).__name__)")
        def fx_outcome(root):
            e = {**os.environ, "ASTRYX_SQLGUARD_ROOT": str(root), "ASTRYX_SQLGUARD_RUN": f"bcx{os.getpid()}"}
            _private_trace(e)
            r = subprocess.run([sys.executable, "-c", probe_ex, str(REPO)], env=e, capture_output=True, text=True,
                               timeout=120)
            return (r.stdout.strip().splitlines() or [r.stderr[-200:]])[-1]
        dead = tmp / "dead"
        (dead / "nucleus").mkdir(parents=True)
        shutil.copy2(REPO / "nucleus" / "schema.sql", dead / "nucleus" / "schema.sql")
        (dead / ".env").write_text("ASTRYX_DSN=postgresql://nobody@127.0.0.1:1/x?connect_timeout=2\n")
        out = fx_outcome(dead)
        check("FixtureUnavailable: an unreachable server is the ENVIRONMENT class", out == "FixtureUnavailable", out)
        broken = tmp / "broken"
        (broken / "nucleus").mkdir(parents=True)
        (broken / "nucleus" / "schema.sql").write_text("CREATE TABLEE nope (x int);\n")
        (broken / ".env").write_text(f"ASTRYX_DSN={scope.dsn(own)}\n")
        out = fx_outcome(broken)
        check("a BROKEN schema.sql propagates as itself (a psycopg SyntaxError), never as FixtureUnavailable",
              out.endswith("SyntaxError") and "FixtureUnavailable" not in out, out)

        # ── private repo, estate copy, secrets, env ──────────────────────────────────────────────────────
        live = synthetic_live(tmp)
        before = git(live, "status", "--porcelain", "--ignored")
        repo = bp.private_repo(live, git(live, "rev-parse", "HEAD").strip(), tmp / "run" / "repo")
        check("private repo: ONE commit of the tree, the live repo only read",
              git(repo, "rev-list", "--count", "HEAD").strip() == "1" and (repo / "code.py").is_file()
              and git(live, "status", "--porcelain", "--ignored") == before, "")
        secrets_ = bp.secret_set(live)
        vals = {s.value for s in secrets_}
        check("secret_set comes from nucleus.secretset: the DSN password, the API key and AUTOREMOTE's key= are secret",
              FAKE in vals and f"sk-{FAKE}" in vals and ARKEY in vals and "org.test" not in vals, "")
        rep = bp.copy_estate(live, repo, secrets_)
        check("estate: a plain gitignored file is copied", (repo / "triggers/t/plain.py").is_file(), str(rep))
        check("estate: a file carrying a secret is NOT copied, and is listed",
              not (repo / "triggers/t/leaky.py").exists() and "triggers/t/leaky.py" in rep["skipped_credential"],
              str(rep))
        check("estate: .env is never copied (estate_paths excludes it)", not (repo / ".env").exists(), "")
        check("estate: the human-personal tier is LINKED to live, never copied into the run",
              (repo / "tier").is_symlink() and (repo / "tier").resolve() == (live / "tier").resolve()
              and "tier" in rep["linked_private"], str(rep.get("linked_private")))
        (repo / "leak.py").write_text(f"k = '{FAKE}'\n")
        git(repo, "add", "leak.py")
        git(repo, "commit", "-q", "-m", "a branch that commits a credential")
        (repo / "ar.py").write_text(f"URL = 'https://ar.example/x?key={ARKEY}'\n")
        git(repo, "add", "ar.py")
        git(repo, "commit", "-q", "-m", "a branch that commits the AUTOREMOTE key")
        hits = bp.tracked_secret_hits(repo, secrets_)
        check("R2: a branch committing the AUTOREMOTE key= value is REFUSED (file:line, value never printed)",
              "ar.py:1" in hits and not any(ARKEY in h for h in hits), str(hits))
        check("branch tree: a committed credential is found as file:line, the value never in the output (a3 BC-2)",
              "leak.py:1" in hits and not any(FAKE in h for h in hits), str(hits))
        envp = bp.write_env(repo, "postgresql://run@127.0.0.1/x", live)
        text = envp.read_text()
        from nucleus import secretset
        check("generated .env: the run DSN + allowlisted keys only, mode 600",
              "ASTRYX_DSN=postgresql://run@" in text and "ASTRYX_ORG=org.test" in text and FAKE not in text
              and oct(envp.stat().st_mode)[-3:] == "600", "")
        check("R2: the generated .env holds NOTHING secretset flags (AUTOREMOTE's key= included)",
              secretset.scan(text, secrets_) == {} and ARKEY not in text, str(secretset.scan(text, secrets_)))
        # a SYNTHETIC DSN with a fake password: the live DSN is password-less since plan-5497 S1c (the password lives
        # only in ~/.pgpass), and an arm bound to today's data went vacuous the day that landed
        fake_dsn = f"postgresql://u:{FAKE}@127.0.0.1:5432/db"
        ci, env = bp._argv_safe(fake_dsn, "x")
        check("pg_dump/pg_restore argv carries no password (it travels in the child env only)",
              FAKE not in ci and env.get("PGPASSWORD") == FAKE and "dbname=x" in ci, ci)

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
