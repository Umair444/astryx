"""S1c-0 runner census (plan-5497): will a PASSWORD-LESS DSN authenticate for every (client, runner)?

S1c moves the DB password out of every DSN into ~/.pgpass. libpq-family clients find that file
through HOME (or PGPASSFILE); node-pg reads ONLY those two, with no getpwuid fallback. So before
the switch, each client must be proven under each RUNNER's REAL environment, not the interactive
shell's (the PATH-minimal pulse scar, 507e7ea).

The environments are READ, not assumed: each running service's /proc/<MainPID>/environ (only
HOME, USER, LOGNAME, PATH, PGPASSFILE are kept, and never printed beyond "set"/"unset"), a live
resident's channel server, and a bare `env -i` shape as the worst case. (09-30: a unit-file grep
said "9 of 10 units set no HOME"; /proc says every running service HAS one, because systemd sets
HOME for User= units. The unit file was the proxy.)

The DSNs are DERIVED: every *_DSN in .env and the declared DSN holders, with the password
removed and the host kept. A pgpass entry must match that host LITERALLY (localhost is not
127.0.0.1: BC-a).

  venv/bin/python -m nucleus.dsn_census          # table; exit 0 iff every expected pair authenticates
  venv/bin/python -m nucleus.dsn_census --json

The bare `env -i` column is REPORTED, not required: no runner measured uses it for node.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEEP = ("HOME", "USER", "LOGNAME", "PATH", "PGPASSFILE")
SERVICES = ("astryx-observatory", "astryx-gateway", "astryx-whatsapp", "astryx-telegram",
            "astryx-discord", "astryx-senses", "astryx-geoloc", "astryx-growbot",
            "genesis-observer")
DSN_FILES = (REPO / ".env", Path.home() / "genesis/services/observer/.env")


def passwordless(dsn: str) -> str:
    p = urllib.parse.urlsplit(dsn)
    netloc = (p.username or "") + "@" + (p.hostname or "") + (f":{p.port}" if p.port else "")
    return urllib.parse.urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))


def dsns() -> dict[str, str]:
    out = {}
    for f in DSN_FILES:
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip().endswith("_DSN") and "://" in v:
                out[f"{f.parent.name}/{k.strip()}"] = passwordless(v.strip())
    return out


def _environ(pid) -> dict | None:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return None
    env = dict(x.decode(errors="replace").split("=", 1) for x in raw if b"=" in x)
    return {k: env[k] for k in KEEP if k in env}


def channel_server_pids(candidates=None) -> list[str]:
    """PIDs of running channel servers: processes whose EXECUTABLE is node and whose argv runs
    channel/server.mjs. `pgrep -f channel/server.mjs` alone also matches any SHELL whose command line
    merely contains that string (it counted a1's own bash as a second abstractor-1 body, 09-30), and a
    long-lived one would read as a stale consumer or be picked as the resident env."""
    if candidates is None:
        candidates = subprocess.run(["pgrep", "-f", "channel/server.mjs"], capture_output=True,
                                    text=True).stdout.split()
    out = []
    for pid in candidates:
        try:
            exe = Path(os.readlink(f"/proc/{pid}/exe")).name
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, ProcessLookupError):
            continue                                      # gone: nothing to judge
        except OSError:
            out.append(str(pid))                          # UNKNOWN (not ours to read): kept, so P4's
            continue                                      # "unknown is stale" can refuse on it (a2)
        if exe.startswith("node") and any(a.endswith(b"channel/server.mjs") for a in argv[1:3]):
            out.append(str(pid))
    return out


def runners() -> dict[str, dict]:
    out = {}
    for s in SERVICES:
        pid = subprocess.run(["systemctl", "show", "-p", "MainPID", "--value", s],
                             capture_output=True, text=True).stdout.strip()
        if pid and pid != "0":
            e = _environ(pid)
            if e is not None:
                out[f"unit:{s}"] = e
    for pid in channel_server_pids()[:1]:
        e = _environ(pid)
        if e is not None:
            out["resident:channel"] = e
    out["bare:env -i"] = {"PATH": "/usr/bin:/bin", "USER": os.environ.get("USER", ""),
                          "LOGNAME": os.environ.get("USER", "")}
    return out


def _node() -> str:
    env = REPO / ".env"
    if not env.exists():                                  # a bare clone: PATH's node
        return "node"
    for line in env.read_text().splitlines():
        if line.startswith("ASTRYX_NODE="):
            return line.split("=", 1)[1].strip()
    return "node"


def clients(dsn: str) -> dict[str, list[str]]:
    py = str(REPO / "venv/bin/python")
    q = "select current_user"
    return {
        "psql": ["psql", "-w", dsn, "-Atc", q],                   # -w: never prompt
        "psycopg": [py, "-c", f"import psycopg;print(psycopg.connect({dsn!r},connect_timeout=5)"
                              f".execute({q!r}).fetchone()[0])"],
        "asyncpg": [py, "-c", "import asyncio,asyncpg\nasync def m():\n c=await asyncpg.connect("
                              f"{dsn!r},timeout=5);print(await c.fetchval({q!r}))\nasyncio.run(m())"],
        "node-pg": [_node(), "--input-type=module", "-e",
                    f"import pg from 'pg';const c=new pg.Client({{connectionString:{json.dumps(dsn)}}});"
                    f"await c.connect();console.log((await c.query({json.dumps(q)})).rows[0].current_user);"
                    "await c.end();"],
    }


def probe(cmd, env) -> str:
    """current_user, or an ERROR CLASS (never the message: it can quote a DSN)."""
    if cmd[0].endswith("node") or "node" in Path(cmd[0]).name:
        if not (REPO / "channel/node_modules/pg").exists():
            return "UNAVAILABLE:no channel/node_modules/pg"
    try:
        r = subprocess.run(cmd, env={**env, "PGCONNECT_TIMEOUT": "5"}, cwd=REPO / "channel",
                           capture_output=True, text=True, timeout=8, stdin=subprocess.DEVNULL)
    except Exception as e:                                   # noqa: BLE001
        return f"ERR:{type(e).__name__}"
    out = r.stdout.strip().splitlines()
    if r.returncode == 0 and out:
        return out[-1]
    err = r.stderr
    for sig in ("no password supplied", "password must be a string", "password authentication failed",
                "ERR_MODULE_NOT_FOUND", "Connection refused", "command not found"):
        if sig in err:
            return f"FAIL:{sig}"
    return f"FAIL:rc={r.returncode}"


def census() -> list[dict]:
    """Every derived DSN under every runner, plus a POSITIVE CONTROL: the same DSN on host
    `localhost` (the one pgpass entry that exists today). If the control fails, a failure on the
    real host means nothing: the instrument, not the pgpass, is broken."""
    rows = []
    rs = runners()
    targets = dict(dsns())
    for dname, dsn in list(targets.items()):
        if urllib.parse.urlsplit(dsn).hostname != "localhost":
            targets[f"control:{dname}@localhost"] = dsn.replace(
                "@" + urllib.parse.urlsplit(dsn).hostname, "@localhost", 1)
    jobs = [(dname, dsn, rname, env, cname, cmd) for dname, dsn in targets.items()
            for rname, env in rs.items() for cname, cmd in clients(dsn).items()]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda j: probe(j[5], j[3]), jobs))
    for (dname, dsn, rname, env, cname, cmd), got in zip(jobs, results):
        role = urllib.parse.urlsplit(dsn).username
        if True:
            if True:
                rows.append({"dsn": dname, "host": urllib.parse.urlsplit(dsn).hostname,
                             "runner": rname, "client": cname,
                             "home": "set" if "HOME" in env else "unset",
                             "pgpassfile": "set" if "PGPASSFILE" in env else "unset",
                             "got": got if got != role else role,
                             "ok": got == role, "required": not rname.startswith("bare:")})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = census()
    if a.json:
        print(json.dumps(rows, indent=1))
    else:
        for r in rows:
            mark = "ok  " if r["ok"] else ("FAIL" if r["required"] else "warn")
            print(f"{mark} {r['dsn']:<40} {r['runner']:<26} {r['client']:<8} HOME={r['home']:<5} "
                  f"{'' if r['ok'] else r['got']}")
    bad = [r for r in rows if r["required"] and not r["ok"]]
    print(f"\n{len(rows)} probes, {len(bad)} required failing"
          + ("" if rows else "  (NO probes: a census that observed nothing is not a pass)"))
    return 1 if bad or not rows else 0


if __name__ == "__main__":
    sys.exit(main())
