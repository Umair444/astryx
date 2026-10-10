#!/usr/bin/env python3
"""astryx · pg_design — does the RUNNING postgres server match its declared design (infra/pg)? (owner 10-10: "the design
on github should match local"; steward F4 of #42345, plan approved by seed #42759.)

The design is infra/pg/docker-compose.yml (container, image, loopback-only port, the -c settings) and infra/pg/Dockerfile
(the extension versions it is built to carry, LABEL org.astryx.pg.*_version). Judged, read-only, against `docker inspect`
of the declared container and the server itself:
  PORTS     the published bindings are EXACTLY the declared ones (a LAN bind is drift: #5497 removed it on 10-10)
  IMAGE     the container runs the declared image tag
  SETTINGS  every `-c name=value` in the compose command is the server's EFFECTIVE value (SHOW). Its SOURCE (command
            line, or the data dir's postgresql.auto.conf) is REPORTED, never judged: until seed's cutover recreates the
            container from infra/pg, today's 300 comes from auto.conf, and the value is what the org relies on.
  VERSIONS  each declared extension version equals pg_extension.extversion in every database that has it installed
            (a rebuild that pulls a different AGE reads RED)
  NAME      the compose container_name is nucleus/pgcontainer.sh's PG_CONTAINER (the name every docker fallback uses)
Pure comparators take parsed inputs, so the oracle drives them on synthetic records; `check` reads the live ones.

    venv/bin/python -m nucleus.pg_design check     # exit 0 matches, 1 drift (printed), 77 can't observe
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMPOSE = REPO / "infra" / "pg" / "docker-compose.yml"
DOCKERFILE = REPO / "infra" / "pg" / "Dockerfile"
HELPER = REPO / "nucleus" / "pgcontainer.sh"
LABEL_RX = re.compile(r"org\.astryx\.pg\.([a-z]+)_version=\"([^\"]+)\"")
EXT_NAME = {"age": "age", "vector": "vector", "postgis": "postgis"}
# Out of scope by seed's routing (#42323/#42347): genesis is deprecated (its deletion is an open owner question) and
# mattermost isn't the org's. Their mismatches are REPORTED (an un-run ALTER EXTENSION … UPDATE is still worth knowing),
# never judged.
OUT_OF_SCOPE = ("genesis", "mattermost")


class Unobservable(Exception):
    pass


def declared(compose_text: str, dockerfile_text: str) -> dict:
    """The design, from the two tracked files."""
    import yaml
    svc = yaml.safe_load(compose_text)["services"]["pg"]
    settings = {}
    cmd = svc.get("command") or []
    for i, a in enumerate(cmd):
        if a == "-c" and i + 1 < len(cmd) and "=" in cmd[i + 1]:
            k, v = cmd[i + 1].split("=", 1)
            settings[k] = v
    return {"container": svc["container_name"], "image": svc["image"], "ports": sorted(svc.get("ports", [])),
            "settings": settings, "versions": dict(LABEL_RX.findall(dockerfile_text))}


def helper_container(helper_text: str) -> str | None:
    m = re.search(r'PG_CONTAINER="\$\{ASTRYX_PG_CONTAINER:-([^}]+)\}"', helper_text)
    return m.group(1) if m else None


def published(inspect: dict) -> list:
    """`docker inspect` PortBindings → compose-style 'ip:host:container' strings."""
    out = []
    for cport, binds in (inspect.get("HostConfig", {}).get("PortBindings") or {}).items():
        for b in binds or []:
            out.append(f"{b.get('HostIp') or '0.0.0.0'}:{b.get('HostPort')}:{cport.split('/')[0]}")
    return sorted(out)


def compare(want: dict, inspect: dict, show: dict, ext: list, helper: str | None) -> dict:
    """want = declared(); inspect = one `docker inspect` record; show = {setting: (value, source)};
    ext = [(db, extname, extversion)]. Returns {"drift": [...], "report": [...]}."""
    drift, report = [], []
    if helper != want["container"]:
        drift.append(f"NAME: nucleus/pgcontainer.sh says {helper!r}, compose's container_name is {want['container']!r}")
    got_ports = published(inspect)
    if got_ports != want["ports"]:
        drift.append(f"PORTS: published {got_ports}, declared {want['ports']}")
    img = inspect.get("Config", {}).get("Image")
    if img != want["image"]:
        drift.append(f"IMAGE: running {img!r}, declared {want['image']!r}")
    for k, v in sorted(want["settings"].items()):
        got = show.get(k)
        if got is None:
            drift.append(f"SETTINGS: {k} unreadable on the server")
        elif got[0] != v:
            drift.append(f"SETTINGS: {k} is {got[0]} (source: {got[1]}), declared {v}")
        else:
            report.append(f"{k}={v} (source: {got[1]})")
    if not want["versions"]:
        drift.append("VERSIONS: the Dockerfile declares no org.astryx.pg.*_version label (nothing to compare)")
    for name, v in sorted(want["versions"].items()):
        rows = [(db, ver) for db, e, ver in ext if e == EXT_NAME.get(name, name)]
        if not rows:
            drift.append(f"VERSIONS: {name} {v} is declared but installed in no database")
        for db, ver in rows:
            if ver != v:
                (report if db in OUT_OF_SCOPE else drift).append(
                    f"VERSIONS: {name} in {db} is {ver}, declared {v}" + (" (out of scope)" if db in OUT_OF_SCOPE else ""))
    return {"drift": drift, "report": report}


def _live(want: dict):
    try:
        r = subprocess.run(["docker", "inspect", want["container"]], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        raise Unobservable(f"docker unavailable ({type(e).__name__})")
    if r.returncode != 0:
        raise Unobservable(f"no container {want['container']!r} to inspect")
    inspect = json.loads(r.stdout)[0]
    import psycopg
    from psycopg.conninfo import make_conninfo
    sys.path.insert(0, str(REPO))
    from nucleus.sqlguard.fixture import live_dsn
    base = live_dsn()
    with psycopg.connect(base, autocommit=True) as c:
        c.execute("SET default_transaction_read_only = on")
        show = {k: (v, s) for k, v, s in c.execute(
            "SELECT name, setting, source FROM pg_settings WHERE name = ANY(%s)", (list(want["settings"]),))}
        dbs = [d for (d,) in c.execute("SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate "
                                       "AND has_database_privilege(datname, 'CONNECT') ORDER BY 1")]
    ext = []
    for d in dbs:
        try:
            with psycopg.connect(make_conninfo(base, dbname=d), autocommit=True, connect_timeout=5) as c:
                c.execute("SET default_transaction_read_only = on")
                ext += [(d, e, v) for e, v in c.execute(
                    "SELECT extname, extversion FROM pg_extension WHERE extname = ANY(%s)", (list(EXT_NAME.values()),))]
        except psycopg.Error:
            continue                                 # a database being dropped mid-read (a fixture) says nothing
    return inspect, show, ext


def check() -> int:
    want = declared(COMPOSE.read_text(), DOCKERFILE.read_text())
    try:
        inspect, show, ext = _live(want)
    except Unobservable as e:
        print(f"pg_design: NOT SEARCHED ({e})")
        return 77
    got = compare(want, inspect, show, ext, helper_container(HELPER.read_text()))
    for d in got["drift"]:
        print(f"  DRIFT {d}")
    for x in got["report"]:
        print(f"  reported, not judged: {x}")
    print("pg_design: " + ("DRIFT" if got["drift"] else "the running server matches infra/pg"))
    return 1 if got["drift"] else 0


if __name__ == "__main__":
    sys.exit(check() if sys.argv[1:2] in ([], ["check"]) else 2)
