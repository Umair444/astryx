#!/usr/bin/env python3
"""Apply schema.sql to every org of this host, after a land that changes it (plan-12214, a4 #65062's land blocker).

Every org's pulse runs one checkout, and land.sh applies no schema: its database is whatever it last was. init.sh's
schema node covers one org when somebody runs it. A cog's other orgs have no such step, so code that needs a new shape
reached them with nothing to say so.

    venv/bin/python devtools/apply_schema.py --check   each org's stamp against schema.sql, read-only; rc 1 if one lags
    venv/bin/python devtools/apply_schema.py --all     apply where it differs, the bytes init.sh applies; stamp after

No registry (one org): that org. Each org runs under its own env (orgenv.py exec), so its own DSN is the only one read.
schema.sql is idempotent. Refuses a schema.sql that differs from HEAD, as init.sh does (a4 #41136). rc 0 all current,
1 one lags or failed, 2 refused.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from astryx import config, orgs, paths  # noqa: E402
import psycopg  # noqa: E402

SCHEMA = Path(os.environ.get("ASTRYX_SCHEMA") or ROOT / "src" / "astryx" / "sql" / "schema.sql")


def _one(apply: bool) -> int:
    """This process's org. Reads its DSN from its own estate."""
    body = SCHEMA.read_bytes()
    sha = hashlib.sha256(body).hexdigest()
    with psycopg.connect(config.dsn(paths.estate(__file__) / ".env"), autocommit=True) as c:
        try:
            have = c.execute("SELECT sha FROM schema_applied WHERE id = 1").fetchone()
        except psycopg.errors.UndefinedTable:
            have = None
        if have and have[0] == sha:
            print(f"current ({sha[:12]})")
            return 0
        if not apply:
            print(f"LAGGING: database has {have[0][:12] if have else 'no stamp'}, schema.sql is {sha[:12]}")
            return 1
        c.execute(body.decode())
        c.execute("CREATE TABLE IF NOT EXISTS schema_applied (id int PRIMARY KEY CHECK (id = 1), sha text NOT NULL, "
                  "applied_at timestamptz NOT NULL DEFAULT now())")
        c.execute("INSERT INTO schema_applied (id, sha) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET sha = "
                  "EXCLUDED.sha, applied_at = now()", (sha,))
    print(f"applied ({sha[:12]})")
    return 0


def _committed() -> bool:
    try:
        rel = SCHEMA.resolve().relative_to(ROOT).as_posix()
        got = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{rel}"], capture_output=True, timeout=30)
    except ValueError:
        return True                # an oracle's file outside the tree (ASTRYX_SCHEMA): no HEAD to compare against
    return got.returncode != 0 or got.stdout == SCHEMA.read_bytes()


def main(argv) -> int:
    mode = argv[0] if argv else ""
    if mode not in ("--check", "--all", "--one-check", "--one-apply"):
        print(__doc__)
        return 2
    if mode.startswith("--one"):
        return _one(mode == "--one-apply")
    if mode == "--all" and not _committed():
        print("refused: schema.sql differs from what git has committed. Commit first.", file=sys.stderr)
        return 2
    one = "--one-apply" if mode == "--all" else "--one-check"
    reg = orgs.load()
    if not reg:
        return _one(mode == "--all")
    return _fan_out(reg["orgs"], one)


def _launch(key: str, o: dict, one: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "ASTRYX_DSN"}
    return subprocess.run([sys.executable, str(ROOT / "src/astryx/orgenv.py"), "exec", "--home", o["home"], "--",
                           sys.executable, str(Path(__file__).resolve()), one],
                          capture_output=True, text=True, timeout=300, cwd=ROOT, env=env)


def _fan_out(org_map: dict, one: str, launch=_launch) -> int:
    """Every org gets its turn: one that fails is said, and doesn't stop the next."""
    rc = 0
    for key, o in org_map.items():
        p = launch(key, o, one)
        last = (p.stdout.strip() or p.stderr.strip()).splitlines()[-1:] or ["no output"]
        print(f"{key}: {last[0][:300]}" + (f" (rc {p.returncode})" if p.returncode else ""))
        rc = rc or (1 if p.returncode else 0)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
