#!/usr/bin/env python3
"""Add an org to this host's cog (plan-11324 S3f S5; devtools/cog_add_org.md step 2). The new org's OWN setup path: it
never calls this checkout's init.sh, whose one-org resolver would re-initialise the PRIMARY (the runbook's trap).

    venv/bin/python devtools/cog_add_org.py <key> --home DIR --name FED [--dry-run]
        [--db NAME] [--dsn DSN] [--ports stem=port,...] [--registry PATH] [--out PATH]
        [--primary-key astryx] [--primary-obs-port 8190]

It makes, in order (--dry-run prints each step and does NONE of them):
  1. the org's DATABASE on the primary's server, as the primary's role (R1: one owner, one superuser): CREATE DATABASE
     <db> (default astryx_<key>), then schema.sql applied whole and stamped (schema_applied, init.sh's _act_schema), and
     PUBLIC CONNECT revoked (init.sh's harden). --dsn brings an EXISTING database instead (one the owner created or
     restored by hand): no CREATE, the schema, stamp and revoke still applied (each is idempotent)
  2. its HOME: absolute, outside every git tree, absent or empty. A `.astryx` marker FILE, local.md from the shipped
     local.template.md, the shipped seed charter (agents/seed/seed.md), homes/ and var/
  3. its .env (mode 600): ASTRYX_ORG (the federation name), ASTRYX_DSN (its database), a fresh ASTRYX_SECRET_KEY (an
     Ed25519 seed, init.sh's org_identity) and OBS_KEY, ASTRYX_URL empty (it is reached through the cog's gateway); no
     channel lines, so no bridge unit is ever wanted. No secret's VALUE is ever printed
  4. the REGISTRY: the host's current one (orgs.load, the authority) plus this org, written to --out (never /etc), and
     validated by orgs.load. With no registry yet, the primary's entry is derived: --primary-key, the checkout as its
     HOME, its database by orgs.db_of, `primary` and `door` true, today's ports (org_units.json) plus its observatory
     backend's (--primary-obs-port)
Then it prints the OWNER's lines (the runbook's step 4) and runs none of them.

Ports default to the runbook's table (astryx-observatory-org 18190, astryx-canvas 18091). A port another org holds, a
cog port, or one something already answers on (a connect attempt; nothing is bound) REFUSES: pass --ports.
STATED LIMIT: the positive CREATE DATABASE path is exercised by S6's rehearsal, not by a gate (tests/test_cog_add_org.py
proves the statement, the refusal of an existing name, and every other step through --dsn on a fixture database).
Exit 0 done (or planned) · 2 refused, with the reason · 3 a step failed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from astryx import config, orgs  # noqa: E402

DEFAULT_PORTS = {"astryx-observatory-org": 18190, "astryx-canvas": 18091}


class Refused(Exception):
    """A precondition failed: nothing was changed by the step that refused."""


def say(dry: bool, what: str) -> None:
    print(f"{'[dry-run] would ' if dry else '· '}{what}")


def shown(dsn: str) -> str:
    """A DSN as a reader may see it: user@host:port/db, the password never."""
    d = orgs.conninfo(dsn)
    return f"{d.get('user', '?')}@{d.get('host', '?')}:{d.get('port', '5432')}/{d.get('dbname', '?')}"


def with_db(dsn: str, db: str) -> str:
    """`dsn` on database `db`, as a postgresql:// URL: the org's .env DSN feeds asyncpg too (the gateway's pools, the
    observatory's), which reads no libpq key=value form (step 4 live, 10-19: a key=value DSN crash-looped the cog's
    gateway). Every other parameter rides the query string; a socket-directory host is a `host=` parameter."""
    from urllib.parse import quote, urlencode
    d = orgs.conninfo(dsn)
    d.pop("dbname", None)
    user, pw, host, port = (d.pop(k, "") for k in ("user", "password", "host", "port"))
    if host.startswith("/"):
        d["host"], host = host, ""
    auth = quote(user, safe="") + (":" + quote(pw, safe="") if pw else "")
    q = "?" + urlencode(d) if d else ""
    return f"postgresql://{auth}{'@' if auth else ''}{host}{':' + port if port else ''}/{quote(db, safe='')}{q}"


def in_git_tree(p: Path) -> Path | None:
    for a in (p, *p.parents):
        if (a / ".git").exists():
            return a
    return None


def answering(port: int) -> bool:
    """Something already accepts on 127.0.0.1:port (a connect attempt: nothing is bound, nothing is released)."""
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def parse_ports(text: str | None) -> dict:
    if not text:
        return dict(DEFAULT_PORTS)
    out = {}
    for part in text.split(","):
        stem, _, n = part.partition("=")
        if not stem or not n.isdigit():
            raise Refused(f"--ports: '{part}' is not stem=port")
        out[stem.strip()] = int(n)
    return out


def plan(a) -> dict:
    """Every precondition, judged BEFORE anything is changed."""
    if not orgs.NAME.fullmatch(a.key):
        raise Refused(f"key '{a.key}' is not a registry key ([a-z0-9][a-z0-9-]{{0,62}})")
    home = Path(a.home)
    if not home.is_absolute():
        raise Refused(f"--home {a.home} is not absolute")
    home = home.resolve()
    g = in_git_tree(home)
    if g is not None:
        raise Refused(f"--home {home} is inside the git tree {g}: a HOME stays outside every checkout (no marker walk "
                      "may reach another org's)")
    if home.exists() and any(home.iterdir()):
        raise Refused(f"--home {home} exists and is not empty")
    env = {orgs.ENV: a.registry} if a.registry else None
    reg_path = orgs.path(env)
    current = orgs.load(env)                      # the authority: a malformed registry RAISES (RegistryError)
    raw = json.loads(reg_path.read_text())["orgs"] if current else {}
    primary_dsn = config.dsn()                    # the primary's: the env first, else its estate's .env (never printed)
    if not current:
        units = json.loads((ROOT / "src" / "astryx" / "data" / "org_units.json").read_text())["units"]
        pports = {k: v["port"] for k, v in units.items() if v["scope"] == "org" and "port" in v}
        pports["astryx-observatory-org"] = a.primary_obs_port
        raw = {a.primary_key: {"home": str(ROOT), "db": orgs.db_of(primary_dsn), "primary": True, "door": True,
                               "ports": pports}}
    if a.key in raw:
        raise Refused(f"'{a.key}' is already registered in {reg_path}")
    db = a.db or "astryx_" + a.key.replace("-", "_")
    ports = parse_ports(a.ports)
    for stem, p in ports.items():               # another org's port is the AUTHORITY's to refuse (below), never re-ruled here
        if answering(p):
            raise Refused(f"port {p} ({stem}): something already answers on 127.0.0.1:{p}")
    lab_dsn = a.dsn or with_db(primary_dsn, db)
    if not a.dsn:
        import psycopg
        with psycopg.connect(primary_dsn, autocommit=True) as c:
            if c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,)).fetchone():
                raise Refused(f"database {db} already exists: pass --dsn to bring it, or choose --db")
    entry = {"home": str(home), "db": db, "ports": ports}
    merged = {**raw, a.key: entry}
    # the REGISTRY is a precondition too (a2 #60860 R-1): the authority judges the merged file here, before any database,
    # HOME or key exists, so a refused one leaves nothing to hand-clean (write_registry judges it again, as defence)
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "cog.json"
        probe.write_text(json.dumps({"orgs": merged}))
        try:
            orgs.load({orgs.ENV: str(probe)})
        except orgs.RegistryError as e:
            raise Refused(f"the merged registry is refused by the authority: {e}") from None
    return {"home": home, "db": db, "lab_dsn": lab_dsn, "primary_dsn": primary_dsn, "entry": entry, "merged": merged,
            "reg_path": reg_path, "had_registry": bool(current)}


def make_db(p: dict, a, dry: bool) -> None:
    import psycopg
    from psycopg import sql
    if not a.dsn:
        say(dry, f"CREATE DATABASE {p['db']} on {shown(p['primary_dsn'])} (the primary's role)")
        if not dry:
            with psycopg.connect(p["primary_dsn"], autocommit=True) as c:
                c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(p["db"])))
    else:
        say(dry, f"use the EXISTING database {shown(p['lab_dsn'])} (--dsn: no CREATE)")
    schema = (ROOT / "src" / "astryx" / "sql" / "schema.sql").read_bytes()
    sha = hashlib.sha256(schema).hexdigest()
    say(dry, f"apply schema.sql ({sha[:12]}) whole to {shown(p['lab_dsn'])} and stamp schema_applied")
    say(dry, f"REVOKE CONNECT ON DATABASE {orgs.db_of(p['lab_dsn'])} FROM PUBLIC")
    if dry:
        return
    with psycopg.connect(p["lab_dsn"], autocommit=True) as c:
        c.execute(schema.decode())
        c.execute("CREATE TABLE IF NOT EXISTS schema_applied (id int PRIMARY KEY CHECK (id = 1), sha text NOT NULL, "
                  "applied_at timestamptz NOT NULL DEFAULT now())")
        c.execute("INSERT INTO schema_applied (id, sha) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET sha = "
                  "EXCLUDED.sha, applied_at = now()", (sha,))
        c.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(orgs.db_of(p["lab_dsn"]))))


def make_home(p: dict, a, dry: bool) -> None:
    home = p["home"]
    say(dry, f"create HOME {home}: .astryx marker, local.md (from local.template.md), agents/seed/seed.md (the "
             "shipped seed), homes/, var/")
    say(dry, f"write {home}/.env (mode 600): ASTRYX_ORG={a.name}, ASTRYX_DSN ({shown(p['lab_dsn'])}), "
             "ASTRYX_SECRET_KEY (fresh), OBS_KEY (fresh), ASTRYX_URL= (empty)")
    if dry:
        return
    from nacl.encoding import HexEncoder
    from nacl.signing import SigningKey
    for d in (home, home / "agents" / "seed", home / "homes", home / "var"):
        d.mkdir(parents=True, exist_ok=True)
    (home / ".astryx").write_text("")
    shutil.copy(ROOT / "local.template.md", home / "local.md")
    shutil.copy(ROOT / "agents" / "seed" / "seed.md", home / "agents" / "seed" / "seed.md")   # org-home: the SHIPPED seed charter (tracked, the code tree's), copied as the new org's
    envf = home / ".env"
    fd = os.open(envf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"ASTRYX_ORG={a.name}\nASTRYX_DSN={p['lab_dsn']}\n"
                f"ASTRYX_SECRET_KEY={SigningKey.generate().encode(HexEncoder).decode()}\n"
                f"OBS_KEY={secrets.token_urlsafe(18)}\nASTRYX_URL=\n")
    os.chmod(envf, 0o600)


def write_registry(p: dict, a, dry: bool) -> None:
    out = Path(a.out)
    say(dry, f"write the registry ({', '.join(sorted(p['merged']))}) to {out}, never /etc, and validate it by orgs.load")
    if dry:
        return
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps({"orgs": p["merged"]}, indent=1) + "\n")
    try:                                          # judged BEFORE it is the registry: a refused one is never left behind
        got = orgs.load({orgs.ENV: str(tmp)})     # RAISES on anything the authority refuses
        prims = [o for o, e in got.items() if e["primary"]]
        if a.key not in got or len(got) != len(p["merged"]) or len(prims) != 1 or a.key in prims:
            raise RuntimeError(f"the registry does not read back as {sorted(p['merged'])} with one primary")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(out)


def owner_lines(p: dict, a) -> None:
    print("\nOWNER (the runbook's step 4, after the S6 rehearsal; run from your own terminal, never a resident's pane):")
    print(f"  sudo install -d -m 755 /etc/astryx && sudo install -m 644 {a.out} /etc/astryx/cog.json")
    print(f"  ASTRYX_HOME={ROOT} ./init.sh units          # ours: plain names, today's units but the observatory")
    print(f"  ASTRYX_HOME={p['home']} ./init.sh units     # {a.key}'s: astryx-<stem>@{a.key}.*")
    print("  env -u ASTRYX_HOME ./init.sh units          # the cog's own: the gateway, the front")
    print(f"  ASTRYX_HOME={ROOT} scripts/deploy.sh units && ASTRYX_HOME={p['home']} scripts/deploy.sh units "
          "&& scripts/deploy.sh units --cog")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="add an org to this host's cog (plan-11324 S3f S5)")
    ap.add_argument("key")
    ap.add_argument("--home", required=True)
    ap.add_argument("--name", required=True, help="its federation name (ASTRYX_ORG)")
    ap.add_argument("--db")
    ap.add_argument("--dsn", help="an EXISTING database to bring (no CREATE)")
    ap.add_argument("--ports")
    ap.add_argument("--registry", help="the current registry (default: the host's, orgs.path)")
    ap.add_argument("--out", default=None, help="where the new registry is written (default: <home>.cog.json)")
    ap.add_argument("--primary-key", default="astryx")
    ap.add_argument("--primary-obs-port", type=int, default=8190)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    a.out = a.out or str(Path(a.home).resolve()) + ".cog.json"
    try:
        p = plan(a)
    except (Refused, orgs.RegistryError) as e:
        print(f"cog_add_org: refusing: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — a precondition that couldn't be judged (the server, say): named, never a value
        print(f"cog_add_org: a precondition could not be judged ({type(e).__name__}: {e})", file=sys.stderr)
        return 3
    if a.dry_run:
        print(f"cog_add_org: the plan for '{a.key}' ({a.name}); NOTHING is changed")
    try:
        make_db(p, a, a.dry_run)
        make_home(p, a, a.dry_run)
        write_registry(p, a, a.dry_run)
    except Exception as e:  # noqa: BLE001 — a failed step is named, with its type; never a value
        print(f"cog_add_org: a step FAILED ({type(e).__name__}: {e})", file=sys.stderr)
        return 3
    owner_lines(p, a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
