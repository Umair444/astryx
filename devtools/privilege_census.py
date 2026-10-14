#!/usr/bin/env python3
"""astryx · privilege_census — what the org's code asks postgres to do, by SURFACE and by the PRIVILEGE it needs.

WHY (people library 1b, seed #36018). Today every resident connects as the superuser. Moving residents to a
NOSUPERUSER role (`astryx_resident`) is decided on numbers: which statements residents' surfaces execute, and which
of those a non-superuser can be GRANTed (cheap), needs to OWN the object (a migration question), needs CREATEDB /
CREATEROLE (role attributes), or needs SUPERUSER outright (a blocker, so it has to move to a service).

    venv/bin/python -m devtools.privilege_census            # the table
    venv/bin/python -m devtools.privilege_census --json     # everything, per file
    venv/bin/python -m devtools.privilege_census --live     # + the server: tables/sequences/owners (read-only)

METHOD AND DOMAIN, stated because a census is only re-runnable evidence with both:
  * DOMAIN: every .py / .mjs / .js / .sh file under the repo, walked on the FILESYSTEM (triggers/ is gitignored and
    real), minus SKIP_DIRS. Printed with the result.
  * A statement is a regex hit of one CLASS pattern on one LINE (uppercase SQL, this codebase's style). A
    multi-statement line counts each class once. It's a static over-approximation of what a surface MAY run, never a
    trace of what it DID: a string in a docstring counts. The live half (--live) only reads catalogs.
  * DSN SOURCE per file: does it read ASTRYX_DSN from the ENVIRONMENT, or open the .env FILE directly? A surface that
    reads the file ignores any per-resident DSN, so 1b's switch can't reach it without a code change.
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))
from astryx.paths import repo_root  # noqa: E402

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(os.environ.get("ASTRYX_CENSUS_ROOT") or repo_root(__file__)).resolve()
SKIP_DIRS = {"venv", ".venv", "node_modules", "homes", ".git", "__pycache__", "dist", "build", "var", "backups"}
EXTS = {".py", ".mjs", ".js", ".sh"}

# SURFACE: who runs the code, by path prefix, first match wins. `runs_as` is what 1b changes: resident surfaces move
# to astryx_resident; services keep the admin DSN.
SURFACES = (
    ("channel/", "wire channel server (resident-spawned MCP)", "resident"),
    ("mcp/", "MCP tool servers (resident-spawned)", "resident"),
    ("tests/", "check.sh oracles (resident-run)", "resident"),
    ("devtools/check.sh", "check.sh (resident-run)", "resident"),
    ("nucleus/", "nucleus library (resident AND service callers)", "both"),
    ("triggers/", "pulse triggers (service)", "service"),
    ("observatory/", "observatory (service)", "service"),
    ("bridges/", "bridges (service)", "service"),
    ("sensors/", "sensors (service)", "service"),
    ("init.sh", "init.sh (the human / seed)", "admin"),
)

# CLASS -> (what a NOSUPERUSER role needs, pattern). Order matters only for display.
CLASSES = {
    "dml": ("a GRANT on the table", r"\b(SELECT\b.+\bFROM|INSERT INTO|UPDATE\s+\w+\s+SET|DELETE FROM|TRUNCATE)\b"),
    "notify": ("nothing (any role)", r"\b(LISTEN\s+\w|NOTIFY\s+\w|pg_notify\()"),
    "ddl": ("OWNERSHIP of the object (or CREATE on the schema)",
            r"\b(CREATE (OR REPLACE )?(TABLE|INDEX|UNIQUE INDEX|VIEW|MATERIALIZED VIEW|FUNCTION|TRIGGER|SCHEMA|"
            r"SEQUENCE|TYPE)|ALTER (TABLE|VIEW|SEQUENCE|FUNCTION)|DROP (TABLE|INDEX|VIEW|FUNCTION|TRIGGER|SCHEMA|"
            r"SEQUENCE|TYPE)|COMMENT ON (TABLE|VIEW|COLUMN))\b"),
    "grant": ("OWNERSHIP of the object granted on", r"\b(GRANT\s+(SELECT|INSERT|UPDATE|DELETE|ALL|USAGE|CONNECT|"
                                                    r"CREATE|TEMP)|REVOKE\s+(SELECT|INSERT|UPDATE|DELETE|ALL|USAGE|"
                                                    r"CONNECT|CREATE|TEMP))\b"),
    "createdb": ("the CREATEDB attribute", r"\b(CREATE DATABASE|DROP DATABASE|ALTER DATABASE)\b"),
    "createrole": ("the CREATEROLE attribute", r"\b(CREATE ROLE|DROP ROLE|ALTER ROLE|CREATE USER|DROP USER)\b"),
    "superuser": ("SUPERUSER (no grant reaches it: a blocker for a resident surface)",
                  r"(\bCREATE EXTENSION\b|\bLOAD\s+'|\bALTER SYSTEM\b|\bCOPY\b.+\b(TO|FROM)\s+(PROGRAM|')|"
                  r"\bpg_read_file\(|\bpg_ls_dir\(|\blo_import\(|\bSET\s+session_preload_libraries\b|"
                  r"\bpg_terminate_backend\()"),
}
_CLASS_RE = {k: re.compile(p) for k, (_, p) in CLASSES.items()}
ENV_RE = re.compile(r"os\.environ(\.get)?\W+ASTRYX_DSN|process\.env\.ASTRYX_DSN|\$\{?ASTRYX_DSN\b|getenv\(\W*ASTRYX_DSN")
FILE_RE = re.compile(r"""['"/]\.env['"]|\.env\b['"]?\)|live_dsn\(|grep\s+['"]?\^ASTRYX_DSN=""")


def surface(rel: str):
    for pre, label, runs in SURFACES:
        if rel == pre or rel.startswith(pre):
            return label, runs
    return "other", "unknown"


def classify(line: str) -> set:
    return {k for k, r in _CLASS_RE.items() if r.search(line)}


def files():
    for dirpath, dirnames, filenames in os.walk(REPO, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for f in sorted(filenames):
            p = Path(dirpath) / f
            if p.suffix in EXTS or f == "init.sh":
                yield p


def scan_file(p: Path) -> dict:
    try:
        text = p.read_text(errors="replace")
    except OSError as e:
        return {"error": type(e).__name__}
    hits = Counter()
    for line in text.splitlines():
        for k in classify(line):
            hits[k] += 1
    return {"classes": dict(hits), "dsn_env": bool(ENV_RE.search(text)), "dsn_file": bool(FILE_RE.search(text))}


def census() -> dict:
    per_file, by_surface = {}, defaultdict(Counter)
    unread = []
    for p in files():
        rel = p.relative_to(REPO).as_posix()
        r = scan_file(p)
        if "error" in r:
            unread.append(rel)
            continue
        if not r["classes"] and not r["dsn_file"] and not r["dsn_env"]:
            continue
        label, runs = surface(rel)
        r.update(surface=label, runs_as=runs)
        per_file[rel] = r
        s = by_surface[label]
        for k, n in r["classes"].items():
            s[k] += n
            s[f"files:{k}"] += 1
        s["dsn_file"] += r["dsn_file"]
        s["dsn_env"] += r["dsn_env"]
    return {"root": str(REPO), "skip_dirs": sorted(SKIP_DIRS), "exts": sorted(EXTS), "unreadable": unread,
            "surfaces": {k: dict(v) for k, v in by_surface.items()}, "files": per_file}


def live(dsn: str) -> dict:
    """Catalog reads only. The numbers 1b's GRANT set is sized by. (The queries are LOCAL so sqlguard keys them to
    the function that runs them.)"""
    import psycopg
    LIVE_SQL = {
        "tables": "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                  "WHERE c.relkind IN ('r','p') AND n.nspname='public'",
        "sequences": "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                     "WHERE c.relkind='S' AND n.nspname='public'",
        "views": "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                 "WHERE c.relkind IN ('v','m') AND n.nspname='public'",
        "owners": "SELECT r.rolname, r.rolsuper, count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                  "JOIN pg_roles r ON r.oid=c.relowner WHERE c.relkind IN ('r','p','v','m','S') AND n.nspname='public' "
                  "GROUP BY 1,2 ORDER BY 3 DESC",
        "login_roles": "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolcanlogin "
                       "AND rolname !~ '^bc_' ORDER BY 1",
        "functions": "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' "
                     "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid=p.oid AND d.deptype='e')",
    }
    out = {}
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("SET default_transaction_read_only = on")
        for k, q in LIVE_SQL.items():
            rows = c.execute(q).fetchall()
            out[k] = rows[0][0] if len(rows) == 1 and len(rows[0]) == 1 else [list(r) for r in rows]
    return out


def render(c: dict, lv: dict = None) -> list:
    cols = list(CLASSES)
    out = [f"privilege census over {c['root']}  (exts {', '.join(c['exts'])}; skipped {', '.join(c['skip_dirs'])})",
           "  a count is LINES matching a class (static: what a surface MAY run), [files] in brackets", ""]
    w = max(len(s) for s in c["surfaces"]) if c["surfaces"] else 10
    out.append(f"  {'surface':<{w}}  " + "  ".join(f"{k:>14}" for k in cols) + "   dsn: env / .env-file")
    order = [s[1] for s in SURFACES] + ["other"]
    for s in sorted(c["surfaces"], key=lambda x: order.index(x) if x in order else 99):
        v = c["surfaces"][s]
        cells = "  ".join(f"{(str(v.get(k, 0)) + ' [' + str(v.get('files:' + k, 0)) + ']'):>14}" for k in cols)
        out.append(f"  {s:<{w}}  {cells}   {v.get('dsn_env', 0)} / {v.get('dsn_file', 0)}")
    out.append("")
    for k, (need, _) in CLASSES.items():
        out.append(f"  {k:<10} needs {need}")
    for runs in ("resident", "both"):
        fs = [f for f, r in c["files"].items() if r["runs_as"] == runs]
        who = "RESIDENT" if runs == "resident" else "SHARED-library"
        for cls in ("superuser", "createrole", "createdb"):
            hit = sorted(f for f in fs if c["files"][f]["classes"].get(cls))
            out.append(f"  {who} files with a {cls.upper()} statement ({len(hit)}): " + (", ".join(hit) or "none"))
    fileread = sorted(f for f, r in c["files"].items() if r["runs_as"] in ("resident", "both") and r["dsn_file"])
    out.append(f"  RESIDENT/SHARED files reading the .env FILE for their DSN ({len(fileread)}): "
               + (", ".join(fileread) or "none"))
    if c["unreadable"]:
        out.append(f"  UNREADABLE (not counted): {', '.join(c['unreadable'])}")
    if lv:
        out += ["", "  live (catalog reads only):"] + [f"    {k}: {v}" for k, v in lv.items()]
    return out


def main(argv) -> int:
    c = census()
    lv = None
    if "--live" in argv:
        dsn = os.environ.get("ASTRYX_DSN") or next(
            (l.split("=", 1)[1].strip() for l in ((REPO / ".env").read_text().splitlines()
                                                  if (REPO / ".env").is_file() else ())
             if l.startswith("ASTRYX_DSN=")), None)     # the scanned root's own .env, never printed
        lv = live(dsn) if dsn else {"error": "no ASTRYX_DSN"}
    if "--json" in argv:
        print(json.dumps({**c, "live": lv}, indent=1, sort_keys=True, default=str))
    else:
        print("\n".join(render(c, lv)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
