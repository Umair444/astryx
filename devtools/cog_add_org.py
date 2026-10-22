#!/usr/bin/env python3
"""Add an org to this host's cog (plan-11324 S3f S5; devtools/cog_add_org.md step 2). The new org's OWN setup path: it
never calls this checkout's init.sh, whose one-org resolver would re-initialise the PRIMARY (the runbook's trap).

    venv/bin/python devtools/cog_add_org.py <key> --home DIR --name FED [--owner EMAIL] [--dry-run]
        [--db NAME] [--dsn DSN] [--ports stem=port,...] [--registry PATH] [--out PATH]
        [--primary-key astryx] [--primary-obs-port 8190]
    venv/bin/python devtools/cog_add_org.py --reconcile <key> [--registry PATH] [--dry-run]

It makes, in order (--dry-run prints each step and does NONE of them):
  1. the org's DATABASE on the primary's server, as the primary's role (R1: one owner, one superuser): CREATE DATABASE
     <db> (default astryx_<key>), then schema.sql applied whole and stamped (schema_applied, init.sh's _act_schema), and
     PUBLIC CONNECT revoked (init.sh's harden). --dsn brings an EXISTING database instead (one the owner created or
     restored by hand): no CREATE, the schema, stamp and revoke still applied (each is idempotent). In a cog with
     sign-in (the registry's `cog` block, plan-11859 U1+U2) --owner EMAIL is REQUIRED and that account is made the
     org's owner (members) in the same connection (D8: never an org that opens to nobody, one writer of that row)
  2. its HOME: absolute, outside every git tree, absent or empty. A `.astryx` marker FILE, local.md from the shipped
     local.template.md, the shipped seed charter (agents/seed/seed.md), homes/ and var/
  3. its .env (mode 600): ASTRYX_ORG (the federation name), ASTRYX_DSN (its database), a fresh ASTRYX_SECRET_KEY (an
     Ed25519 seed, init.sh's org_identity) and OBS_KEY, ASTRYX_URL empty (it is reached through the cog's gateway); no
     channel lines, so no bridge unit is ever wanted. No secret's VALUE is ever printed
  3b. its SHIPPED TRIGGERS (plan-10224 add-org-parity), the one-org reconcile init.sh gives its checkout: the shims
     of context_compact, pr_review, agent_heal and org_backup (its own daily dump into ITS HOME's backups/ and weekly
     restore-verify), and windows_idle_stop where this host has a Windows container, into HOME/triggers/seed/, from
     ONE source (astryx.pulse.shipped_triggers.shims, the text init.sh writes). A new HOME is empty by precondition,
     so no trigger can exist there yet: each is installed
  4. the REGISTRY: the host's current one (orgs.load, the authority, its `cog` block carried) plus this org, written to --out (never /etc), and
     validated by orgs.load. With no registry yet, the primary's entry is derived: --primary-key, the checkout as its
     HOME, its database by orgs.db_of, `primary` and `door` true, today's ports (org_units.json) plus its observatory
     backend's (--primary-obs-port)
Then it prints the OWNER's lines (the runbook's step 4) and runs none of them.

Ports default to the runbook's table (astryx-observatory-org 18190, astryx-canvas 18091). A port another org holds, a
cog port, or one something already answers on (a connect attempt; nothing is bound) REFUSES: pass --ports.
STATED LIMIT: the positive CREATE DATABASE path is exercised by S6's rehearsal, not by a gate (tests/test_cog_add_org.py
proves the statement, the refusal of an existing name, and every other step through --dsn on a fixture database).
`--reconcile <key>` brings an EXISTING org of the registry (not the primary: ./init.sh reconciles that one) to the
same set, idempotently: every shim's names are asked of trigger_names under ITS HOME and the registry, ALL before any
file is written, and a shim is installed only when every name it registers is absent. Installed anywhere, retired, or
deferred (unreadable) stands it down, named. No unit, so no sudo line: the org's pulse runs its triggers.
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
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from astryx import config, orgs  # noqa: E402
from astryx.core import orgname  # noqa: E402
from astryx.pulse.shipped_triggers import shims  # noqa: E402

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


def owner_key() -> str:
    """The cog's ONE owner key (owner 10-19: "a single obs key manages both and switch is seamless"): the primary's
    OBS_KEY (config.get: its environment on one org, else its HOME's .env), so the viewer's one key opens every room
    behind the front. Each org's observatory still checks its own .env's key; they are equal by construction. A
    primary with none (or none readable) gives a fresh key, as before."""
    try:
        k = config.get("OBS_KEY")
    except Exception:  # noqa: BLE001 — an unresolvable HOME reads as no key, never a crash mid-setup
        k = ""
    return k or secrets.token_urlsafe(18)


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
    # the cog's sign-in block (plan-11859 U1+U2) rides through untouched; with one, the org is made with its OWNER
    # (D8, a2 I8: one writer of the first membership row, in the same act), so it never opens to nobody but the key
    cog_block = json.loads(reg_path.read_text()).get("cog") if current else None
    cog = orgs.cog(env) if cog_block is not None else None
    owner_sub = None
    if cog is not None:
        if not a.owner:
            raise Refused("this cog has sign-in (its registry's `cog` block): name the new org's owner, --owner EMAIL")
        import psycopg
        from astryx import cogauth
        with psycopg.connect(cogauth.store_dsn(cog["home"])) as c:
            uid = cogauth.uid_of(c, a.owner)
        if uid is None:
            raise Refused(f"--owner: the cog has no such account (add it first: src/astryx/cogauth.py user add)")
        owner_sub = cogauth.sub(uid, cog["id"])
    elif a.owner:
        raise Refused("--owner needs a cog with sign-in (the registry's `cog` block); this one has none")
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
    # its FEDERATION name (10224 NAMES, a2 #61769 F-1): a peer addresses an org by it, so two orgs of one cog under one
    # name are one address. Judged last, so every other refusal keeps its own reason; read from each existing HOME's
    # .env FILE (orgs.fed_name), the derived primary's (this checkout) included, case-insensitively
    if not orgname.org_ok(a.name):
        raise Refused(f"--name {a.name!r} is not a federation name ([a-z0-9][a-z0-9._-]{{0,79}}, not reserved)")
    held = {o: orgs.fed_name(e["home"]) for o, e in raw.items()}
    clash = sorted(o for o, n in held.items() if n and n.lower() == a.name.lower())
    if clash:
        raise Refused(f"--name {a.name} is already the federation name of {', '.join(clash)} in this cog: two orgs under "
                      "one name are one address to every peer")
    return {"home": home, "db": db, "lab_dsn": lab_dsn, "primary_dsn": primary_dsn, "entry": entry, "merged": merged,
            "reg_path": reg_path, "had_registry": bool(current), "cog": cog_block, "owner_sub": owner_sub}


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
    if p["owner_sub"]:
        say(dry, f"make {p['owner_sub']} its owner (members), in the same act (D8)")
    if dry:
        return
    with psycopg.connect(p["lab_dsn"], autocommit=True) as c:
        c.execute(schema.decode())
        c.execute("CREATE TABLE IF NOT EXISTS schema_applied (id int PRIMARY KEY CHECK (id = 1), sha text NOT NULL, "
                  "applied_at timestamptz NOT NULL DEFAULT now())")
        c.execute("INSERT INTO schema_applied (id, sha) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET sha = "
                  "EXCLUDED.sha, applied_at = now()", (sha,))
        c.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(orgs.db_of(p["lab_dsn"]))))
        if p["owner_sub"]:
            from astryx import cogauth
            cogauth.grant(c, p["owner_sub"], "owner")


def make_home(p: dict, a, dry: bool) -> None:
    home = p["home"]
    say(dry, f"create HOME {home}: .astryx marker, local.md (from local.template.md), agents/seed/seed.md (the "
             "shipped seed), homes/, var/")
    say(dry, f"write {home}/.env (mode 600): ASTRYX_ORG={a.name}, ASTRYX_DSN ({shown(p['lab_dsn'])}), "
             "ASTRYX_SECRET_KEY (fresh), OBS_KEY (the primary's: one owner key for the cog), ASTRYX_URL= (empty)")
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
                f"OBS_KEY={owner_key()}\nASTRYX_URL=\n")
    os.chmod(envf, 0o600)


def make_triggers(p: dict, a, dry: bool) -> None:
    install_triggers(p["home"], dry)


# the shipped triggers a cog org gets (init.sh's one-org set, minus what serves only a checkout: phone_resume_sweep needs
# ANDROID_ENABLED in the org's .env, which a new org never has; upstream_prs is the upstream REPO's own watch)
COG_SHIMS = ("context_compact", "pr_review", "windows_idle_stop", "agent_heal", "org_backup")


def _wanted(shim: str) -> bool:
    """init.sh's gates, for what a cog org gets: windows_idle_stop only where this host has a Windows container."""
    if shim != "windows_idle_stop":
        return True
    return shutil.which("docker") is not None and subprocess.run(
        ["docker", "inspect", os.environ.get("WINDOWS_CONTAINER") or "windows"], capture_output=True).returncode == 0


def _state(name: str, home: Path, registry: Path) -> tuple[str, str]:
    """trigger_names' answer for `name` in the org at `home` (the ONE helper; its registry named explicitly). No
    ASTRYX_* name is inherited: this tool runs with the PRIMARY's ASTRYX_DSN (env-first), and trigger_names reads its
    legacy rows through config.dsn, env-first too, so an inherited DSN asked the primary's triggers table about the org
    (its org_runners rows read "deferred" for run_backup). Only the org's HOME and the registry are named."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ASTRYX_")}
    r = subprocess.run([sys.executable, "-m", "astryx.core.trigger_names", "state", name, "--target", "seed"], cwd=ROOT,
                       capture_output=True, text=True, timeout=120,
                       env={**env, "ASTRYX_HOME": str(home), orgs.ENV: str(registry), "PYTHONPATH": str(ROOT / "src")})
    out = (r.stdout.strip() or r.stderr.strip()[-200:] or "no answer").split(" ", 1)
    return (out[0] if out[0] in ("installed", "retired", "absent", "deferred") else "deferred"), " ".join(out[1:])


def install_triggers(home: Path, dry: bool, registry: Path | None = None) -> list:
    """The shipped shims into home/triggers/seed. registry None: a NEW home (empty by precondition: install every
    wanted one). Else the deferential reconcile: every state is read BEFORE any file is written (a written shim must
    not change the next one's answer), and a shim goes in only when ALL the names it registers are absent."""
    tdir = home / "triggers" / "seed"
    plan_ = []
    for shim in COG_SHIMS:
        if not _wanted(shim):
            plan_.append((shim, "skip", "not used on this host"))
            continue
        if registry is None:
            plan_.append((shim, "install", "a new HOME has no triggers"))
            continue
        st = {n: _state(n, home, registry) for n in shims.NAMES[shim]}
        if all(s == "absent" for s, _ in st.values()):
            plan_.append((shim, "install", "every name it registers is absent"))
        else:
            plan_.append((shim, "stand down", "; ".join(f"{n} {s} {d}".strip() for n, (s, d) in st.items()
                                                       if s != "absent")))
    for shim, act, why in plan_:
        say(dry, f"{'install' if act == 'install' else act} trigger {shim} in {tdir}" + (f" ({why})" if why else ""))
        if act == "install" and not dry:
            tdir.mkdir(parents=True, exist_ok=True)
            shims.write(shim, tdir)
    return plan_


def reconcile(a) -> int:
    env = {orgs.ENV: a.registry} if a.registry else None
    reg_path = orgs.path(env)
    try:
        got = orgs.load(env)
    except orgs.RegistryError as e:
        print(f"cog_add_org: refusing: {e}", file=sys.stderr)
        return 2
    if not got or a.reconcile not in got:
        print(f"cog_add_org: refusing: '{a.reconcile}' is not an org of the registry {reg_path}", file=sys.stderr)
        return 2
    e = got[a.reconcile]
    if e["primary"]:
        print(f"cog_add_org: refusing: '{a.reconcile}' is the cog's primary, whose checkout ./init.sh reconciles",
              file=sys.stderr)
        return 2
    home = Path(e["home"])
    if not (home / ".env").is_file():
        print(f"cog_add_org: refusing: {home} holds no .env (not a set-up org HOME)", file=sys.stderr)
        return 2
    print(f"cog_add_org: reconcile '{a.reconcile}' ({home})" + ("; NOTHING is changed" if a.dry_run else ""))
    install_triggers(home, a.dry_run, reg_path)
    print(f"\nIts pulse runs them (no unit, no sudo line). Its first dump lands at 04:00 in {home}/backups/; to run one "
          f"now: ASTRYX_HOME={home} scripts/backup.sh")
    return 0


def write_registry(p: dict, a, dry: bool) -> None:
    out = Path(a.out)
    say(dry, f"write the registry ({', '.join(sorted(p['merged']))}) to {out}, never /etc, and validate it by orgs.load")
    if dry:
        return
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps({"orgs": p["merged"], **({"cog": p["cog"]} if p["cog"] is not None else {})},
                              indent=1) + "\n")
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
    ap.add_argument("key", nargs="?")
    ap.add_argument("--home")
    ap.add_argument("--name", help="its federation name (ASTRYX_ORG)")
    ap.add_argument("--reconcile", metavar="KEY", help="bring an EXISTING org's shipped triggers to the set (no add)")
    ap.add_argument("--db")
    ap.add_argument("--dsn", help="an EXISTING database to bring (no CREATE)")
    ap.add_argument("--ports")
    ap.add_argument("--registry", help="the current registry (default: the host's, orgs.path)")
    ap.add_argument("--out", default=None, help="where the new registry is written (default: <home>.cog.json)")
    ap.add_argument("--primary-key", default="astryx")
    ap.add_argument("--primary-obs-port", type=int, default=8190)
    ap.add_argument("--owner", help="the new org's owner, by account email (required when the cog has sign-in)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.reconcile:
        if a.key or a.home or a.name or a.db or a.dsn or a.ports or a.out or a.owner:
            ap.error("--reconcile KEY takes only --registry and --dry-run")
        return reconcile(a)
    if not (a.key and a.home and a.name):
        ap.error("adding an org needs <key>, --home and --name")
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
        make_triggers(p, a, a.dry_run)
        write_registry(p, a, a.dry_run)
    except Exception as e:  # noqa: BLE001 — a failed step is named, with its type; never a value
        print(f"cog_add_org: a step FAILED ({type(e).__name__}: {e})", file=sys.stderr)
        return 3
    owner_lines(p, a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
