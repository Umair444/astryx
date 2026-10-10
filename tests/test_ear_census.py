#!/usr/bin/env python3
"""Oracle: hearing's COPIER CENSUS and SNAPPER arms (plan-8674 S1, nucleus/ear_census.py; #42059's correction).

SYNTHETIC arms run on a temp root with a fake derived source (/home/tester/genesis/data/pg in container fake-pg),
so every RED control is planted, never waited for:
  RED     tar / rsync / cp / docker cp / shutil.copytree of the source, inside it, or an ANCESTOR of it ($HOME, ~,
          Path.home()); pg_dump with a variable or missing database; pg_dumpall; pg_basebackup; any line naming
          astryx_ear (also as a literal pg_dump target); a crontab line; a .service ExecStart; a volume copy.
  GREEN   the same tokens in comments and docstrings; pg_dump of a LITERAL other database; a copy of an unrelated
          path; the ear's own files naming their database.
  PINS    a reviewed line passes; the same line edited by one character is RED again; a pin whose ASTRYX_DSN binding
          now names astryx_ear is RED.
  RESOLVE the DSN's port → exactly one container → its DATA mounts only (the initdb mount excluded); BLIND (None) when
          nothing serves the port, two containers do, docker is absent, or the DSN is a unix socket; the CLI exits 77.
  SNAPPER a config whose subvolume contains the source (no boundary between) is RED; `/` over a separately-mounted
          /home, or a nested btrfs subvolume root (inode 256) in between, is not; unreadable configs → BLIND.
LIVE arms (read-only): the live DSN resolves to its container's bind source; the live root's census and the host's
snapper configs are GREEN. Where docker or the DSN is unreachable these verify nothing → exit 77.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from nucleus import ear_census as C  # noqa: E402

fails, skipped = [], []
HOME = "/home/tester"
CID = "f" * 52 + "a1b2c3d4e5f6"
PHYS = {"container": "fake-pg", "names": ["fake-pg", CID, CID[:12], "pg"], "sources": [f"{HOME}/genesis/data/pg"],
        "volumes": ["fakevol"], "dests": ["/var/lib/postgresql"], "compose_dir": f"{HOME}/genesis/services/pg"}


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


def plant(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def run_scan(root, **kw):
    return C.scan(root, PHYS, reviewed=kw.pop("reviewed", []), home=HOME, **kw)


print("synthetic copier census")
RED_CASES = {
    "tar of the source":            ("a.sh", "tar czf /mnt/b.tgz /home/tester/genesis/data/pg\n", "copies-data-path"),
    "rsync of an ancestor ($HOME)": ("b.sh", 'rsync -a "$HOME/" /mnt/backup/\n', "copies-data-path"),
    "cp from inside the source":    ("c.sh", "cp -a ~/genesis/data/pg/base /tmp/x\n", "copies-data-path"),
    "docker cp of the container":   ("d.sh", "docker cp fake-pg:/var/lib/postgresql /tmp/x\n", "docker-cp-container"),
    "python copytree of home":      ("e.py", "import shutil\nshutil.copytree(Path.home(), dst)\n", "copies-data-path"),
    "pg_dump of a variable":        ("f.sh", 'pg_dump -Fc "$DB" > out.dump\n', "pg_dump-nonliteral"),
    "pg_dump with no database":     ("g.sh", "pg_dump -Fc > out.dump\n", "pg_dump-nonliteral"),
    "python pg_dump of a variable": ("h.py", 'subprocess.run(["pg_dump", "-Fc", "-d", target])\n', "pg_dump-nonliteral"),
    "pg_dumpall":                   ("i.sh", "pg_dumpall > /mnt/all.sql\n", "pg_dumpall"),
    "pg_basebackup":                ("j.sh", "pg_basebackup -D /mnt/base -Ft\n", "pg_basebackup"),
    "a site naming astryx_ear":     ("k.sh", "psql -d astryx_ear -c 'COPY utterances TO STDOUT' > x\n", "names-astryx_ear"),
    "pg_dump of astryx_ear (URI)":  ("l.sh", 'pg_dump "postgresql://u@h/astryx_ear" > x\n', "pg_dump-astryx_ear"),
    "a unit ExecStart":             ("m.service", "[Service]\nExecStart=/usr/bin/tar czf /b.tgz /home/tester\n", "copies-data-path"),
    "a volume copy":                ("n.sh", "docker run --rm -v fakevol:/d alpine tar c /d > v.tar\n", "copies-volume"),
    "an extensionless script":      ("bin/backup", "#!/bin/sh\npg_dumpall | gzip > /x\n", "pg_dumpall"),
    # R1 (review): docker's own documented volume-backup idiom names neither the db nor the host path
    "R1 --volumes-from (the idiom)": ("o.sh", "docker run --rm --volumes-from fake-pg -v /tmp:/b alpine tar czf /b/x "
                                              "/var/lib/postgresql\n", "volumes-from-container"),
    "R1 --volumes-from by short id": ("p.sh", f"docker run --rm --volumes-from={CID[:12]} busybox true\n",
                                      "volumes-from-container"),
    "R1 --volumes-from by compose service": ("q.sh", "docker run --rm --volumes-from pg alpine ls\n",
                                             "volumes-from-container"),
    "R1 a data DESTINATION on docker exec": ("r.sh", "docker exec fake-pg tar c /var/lib/postgresql/18 > x.tar\n",
                                             "docker-data-dest"),
}
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    plant(root, "clean.sh", "# pg_dumpall would be bad; tar the /home/tester tree? no\n"
                            "pg_dump -Fc -U astryx astryx > a.dump\ndocker exec x pg_dump -d astryx > b.dump\n"
                            "cp /home/tester/astryx/notes.txt /tmp/\ntar czf x.tgz /srv/www\n")
    plant(root, "clean.py", '"""Docs may say pg_dumpall, astryx_ear, or tar ~/ freely."""\n'
                            "x = 1  # pg_basebackup in a comment\n"
                            'def f():\n    """pg_dump $X in a docstring"""\n    return ["pg_dump", "-d", "astryx"]\n')
    plant(root, "nucleus/ear_store.py", 'EAR_DB = "astryx_ear"\n')
    plant(root, "other.sh", "docker run --rm --volumes-from othercontainer -v /tmp:/b alpine tar czf /b/x /srv/app\n"
                            "docker run --rm -v /srv/www:/w nginx\nlet m = ~mask; x = ~(y)\n")
    plant(root, "notes.md", "pg_dumpall astryx_ear\n")            # not code-shaped: never a site
    plant(root, "homes/x/.transcript-aside/t.jsonl", '{"c": "pg_dumpall astryx_ear"}\n')
    g = run_scan(root)
    want("GREEN baseline: comments, docstrings, literal dumps, unrelated copies, the ear's own files, prose, an "
         "unrelated `--volumes-from othercontainer`, bitwise-not `~x`",
         g["red"] == [], json.dumps(g["red"], indent=1))
    for label, (rel, text, kind) in RED_CASES.items():
        plant(root, rel, text)
        r = run_scan(root)
        mine = [h for h in r["red"] if h["path"] == rel]
        want(f"RED control: {label} → {kind}", any(k.startswith(kind) for h in mine for k in h["kinds"]),
             json.dumps(mine))
        (root / rel).unlink()
    plant(root, "nucleus/ear_store.py", 'EAR_DB = "astryx_ear"\nos.system("pg_dumpall > x")\n')
    r = run_scan(root)
    want("the ear's own file is exempt only from NAMING its db: a pg_dumpall in it is still RED",
         [k for h in r["red"] for k in h["kinds"]] == ["pg_dumpall"], json.dumps(r["red"]))
    plant(root, "nucleus/ear_store.py", 'EAR_DB = "astryx_ear"\n')
    r = run_scan(root, crontab="0 3 * * * pg_dumpall > /mnt/all.sql\n")
    want("RED control: the user crontab is searched", any(h["path"] == "crontab:-l" for h in r["red"]), str(r["red"]))

    # PINS
    line = 'pg_dump -Fc "$DSN" > "$part"'
    plant(root, "backup.sh", f"DSN=$(cat dsn)\n{line}\n")
    pin = {"path": "backup.sh", "sha": C.line_sha(line), "kinds": ["pg_dump-nonliteral"], "why": "test",
           "resolves": "ASTRYX_DSN"}
    r = run_scan(root, reviewed=[pin], dsn="host=127.0.0.1 dbname=astryx user=u")
    want("a reviewed pin holds while its line and its binding are unchanged", not r["red"] and len(r["pinned"]) == 1,
         str(r))
    r = run_scan(root, reviewed=[pin], dsn="host=127.0.0.1 dbname=astryx_ear user=u")
    want("RED control: the pin's binding (ASTRYX_DSN's dbname) now names astryx_ear → RED",
         any("pin-binding-broken" in k for h in r["red"] for k in h["kinds"]), str(r))
    plant(root, "backup.sh", f"DSN=$(cat dsn)\n{line.replace('-Fc', '-Fd')}\n")
    r = run_scan(root, reviewed=[pin], dsn="host=127.0.0.1 dbname=astryx user=u")
    want("RED control: the pinned line edited by one flag is RED again (re-review needed)", len(r["red"]) == 1, str(r))

print("resolve (fake docker)")
INSPECT = [{"Id": CID, "Name": "/genesis-pg", "Config": {"Env": ["PGDATA=/var/lib/postgresql/18/docker"], "Labels": {
    "com.docker.compose.service": "pg", "com.docker.compose.project.working_dir": "/home/tester/genesis/services/pg"}},
    "Mounts": [
    {"Type": "bind", "Source": "/srv/initdb", "Destination": "/docker-entrypoint-initdb.d"},
    {"Type": "bind", "Source": "/home/tester/genesis/data/pg", "Destination": "/var/lib/postgresql"},
    {"Type": "volume", "Name": "pgextra", "Source": "/var/lib/docker/volumes/pgextra/_data",
     "Destination": "/var/lib/postgresql/18/docker/pg_wal"}]}]


def fake(ps):
    def run(cmd):
        if cmd[:2] == ["docker", "ps"]:
            return ps
        if cmd[:2] == ["docker", "inspect"]:
            return json.dumps(INSPECT)
        return None
    return run


ps1 = "genesis-pg\t127.0.0.1:5432->5432/tcp, 192.168.1.9:5432->5432/tcp\nother\t0.0.0.0:6379->6379/tcp\n"
r = C.resolve("postgresql://u@127.0.0.1:5432/astryx", run=fake(ps1))
want("the DSN's port maps to its ONE container; only DATA mounts (initdb excluded), bind sources + volume names",
     r and r["container"] == "genesis-pg" and r["sources"] == ["/home/tester/genesis/data/pg",
                                                              "/var/lib/docker/volumes/pgextra/_data"]
     and r["volumes"] == ["pgextra"], str(r))
want("R1: every name it answers to (name, full + short id, compose service) and the container-side data DESTINATIONS",
     r and {"genesis-pg", CID, CID[:12], "pg"} <= set(r["names"])
     and r["dests"] == ["/var/lib/postgresql", "/var/lib/postgresql/18/docker/pg_wal"], str(r))
want("R2: the compose home is the top ancestor below $HOME of the compose working_dir",
     r and r["compose_dir"] == "/home/tester/genesis/services/pg"
     and C.compose_home(r, home="/home/tester") == Path("/home/tester/genesis"), str(r and r.get("compose_dir")))
want("R2: a container not started by compose has no compose home", C.compose_home({"compose_dir": None}) is None)
want("BLIND: nothing publishes the DSN's port", C.resolve("postgresql://u@127.0.0.1:5999/a", run=fake(ps1)) is None)
ps2 = ps1 + "twin\t0.0.0.0:5432->5432/tcp\n"
want("BLIND: two containers publish it (ambiguous)", C.resolve("postgresql://u@127.0.0.1:5432/a", run=fake(ps2)) is None)
want("BLIND: docker unavailable", C.resolve("postgresql://u@127.0.0.1:5432/a", run=lambda c: None) is None)
want("BLIND: a unix-socket DSN", C.resolve("host=/var/run/postgresql dbname=a", run=fake(ps1)) is None)
env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
env["ASTRYX_DSN"] = "postgresql://nobody@127.0.0.1:1/none"
cli = subprocess.run([sys.executable, "-m", "nucleus.ear_census"], cwd=REPO, env=env, capture_output=True, text=True)
want("the CLI exits 77 BLIND (never GREEN) when the DSN's container can't be resolved",
     cli.returncode == 77 and "BLIND" in cli.stdout, f"rc={cli.returncode} {cli.stdout}{cli.stderr}")

print("R2: the cluster's own compose home is searched (derived), the data source is not")
with tempfile.TemporaryDirectory() as td:
    h = Path(td) / "home" / "tester"
    repo, gen = h / "astryx", h / "genesis"
    plant(repo, "ok.sh", "echo hi\n")
    plant(gen, "services/pg/docker-compose.yml", "services:\n  pg:\n    image: postgres\n")
    plant(gen, "tools/package-code", "#!/bin/sh\ncd \"$ROOT\"\nrsync -a --exclude='data/' services tools \"$STAGE/\"\n")
    plant(gen, "data/pg/planted.sh", "pg_dumpall > /mnt/all.sql\n")       # INSIDE the data source: not a site
    ph = {**PHYS, "sources": [str(gen / "data" / "pg")], "compose_dir": str(gen / "services" / "pg")}
    doms = C.roots(repo, ph, home=str(h))
    want("R2: the domain is the repo root plus the derived compose home", doms == [repo.resolve(), gen.resolve()],
         str(doms))
    files = [f for d in doms for f in C.corpus(d, skip=ph["sources"])]
    g = C.scan(repo, ph, reviewed=[], files=files, home=str(h))
    want("R2: GREEN on a compose home whose tool rsyncs with --exclude='data/' (and the data dir is never read)",
         g["red"] == [] and not any("data/pg" in str(f) for f in files), json.dumps(g["red"]))
    plant(gen, "tools/pg-backup.sh", f"#!/bin/sh\ntar czf /mnt/pg.tgz {gen}/data\n")
    files = [f for d in doms for f in C.corpus(d, skip=ph["sources"])]
    r2 = C.scan(repo, ph, reviewed=[], files=files, home=str(h))
    want("R2 RED control: a copier planted in the compose home (not the repo) → RED",
         any(x["path"].endswith("tools/pg-backup.sh") and any(k.startswith("copies-data-path") for k in x["kinds"])
             for x in r2["red"]), json.dumps(r2["red"]))
    inner = {**ph, "compose_dir": str(repo / "svc" / "pg")}
    want("R2: a compose home already inside the repo root is not searched twice",
         C.roots(repo, inner, home=str(repo.parent)) == [repo.resolve()], str(C.roots(repo, inner, home=str(repo.parent))))

print("snapper (synthetic filesystem)")
FS = {"/": (1, 256), "/home": (2, 256), "/home/tester": (2, 300), "/home/tester/genesis": (2, 301),
      "/home/tester/genesis/data": (2, 302), "/home/tester/genesis/data/pg": (2, 303)}
st = lambda p: SimpleNamespace(st_dev=FS[p][0], st_ino=FS[p][1])
src = ["/home/tester/genesis/data/pg"]
with tempfile.TemporaryDirectory() as td:
    cd = Path(td) / "configs"
    cd.mkdir()
    (cd / "root").write_text('SUBVOLUME="/"\nFSTYPE="btrfs"\n')
    want("GREEN: `/` does not snapshot a source on a separately-mounted /home", C.snapper_findings(src, cd, st) == [])
    (cd / "home").write_text('SUBVOLUME="/home"\n')
    f = C.snapper_findings(src, cd, st)
    want("RED control: a config on /home snapshots the source", len(f) == 1 and "'home'" in f[0], str(f))
    (cd / "home").unlink()
    (cd / "gen").write_text('SUBVOLUME="/home/tester/genesis"\n')
    want("RED control: a config on an ancestor directory subvolume", len(C.snapper_findings(src, cd, st)) == 1)
    FS["/home/tester/genesis/data"] = (2, 256)                  # a nested btrfs subvolume root in between
    want("a nested subvolume between them is a boundary: not snapshotted", C.snapper_findings(src, cd, st) == [])
    want("no snapper configs dir → nothing to snapshot", C.snapper_findings(src, Path(td) / "absent", st) == [])
    if os.geteuid() != 0:
        cd.chmod(0)
        want("BLIND: unreadable configs → None, never GREEN", C.snapper_findings(src, cd, st) is None)
        cd.chmod(0o755)

print("live (read-only)")
try:
    from nucleus.ear_store import admin_dsn
    dsn = admin_dsn()
except Exception:                                                  # noqa: BLE001
    dsn = ""
phys = C.resolve(dsn) if dsn else None
if phys is None:
    skipped.append("live")
    print("  (live arms NOT RUN: the live DSN's container couldn't be resolved here)")
else:
    want(f"live: the DSN resolves to container {phys['container']} with a data bind source", bool(phys["sources"]),
         str(phys))
    root = Path(os.environ.get("EAR_CENSUS_ROOT") or REPO)
    doms = C.roots(root, phys)
    files = [f for d in doms for f in C.corpus(d, skip=phys["sources"])] + C.extra_files()
    res = C.scan(root, phys, dsn=dsn, files=files, crontab=C._run(["crontab", "-l"]))
    want(f"live: the copier census is GREEN on {' + '.join(map(str, doms))} ({res['files']} code files, "
         f"{len(res['pinned'])} reviewed pins)",
         res["red"] == [], json.dumps(res["red"], indent=1))
    sf = C.snapper_findings(phys["sources"])
    want("live: no snapper config snapshots the pg data source", sf == [], str(sf))

print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}" + (f" ({', '.join(skipped)} NOT RUN)" if skipped else ""))
sys.exit(1 if fails else (77 if skipped else 0))
