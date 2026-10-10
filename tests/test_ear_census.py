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
PHYS = {"container": "fake-pg", "sources": [f"{HOME}/genesis/data/pg"], "volumes": ["fakevol"]}


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
    plant(root, "notes.md", "pg_dumpall astryx_ear\n")            # not code-shaped: never a site
    plant(root, "homes/x/.transcript-aside/t.jsonl", '{"c": "pg_dumpall astryx_ear"}\n')
    g = run_scan(root)
    want("GREEN baseline: comments, docstrings, literal dumps, unrelated copies, the ear's own files, prose",
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
INSPECT = [{"Config": {"Env": ["PGDATA=/var/lib/postgresql/18/docker"]}, "Mounts": [
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
    res = C.scan(root, phys, dsn=dsn, files=C.corpus(root) + C.extra_files(), crontab=C._run(["crontab", "-l"]))
    want(f"live: the copier census is GREEN on {root} ({res['files']} code files, {len(res['pinned'])} reviewed pins)",
         res["red"] == [], json.dumps(res["red"], indent=1))
    sf = C.snapper_findings(phys["sources"])
    want("live: no snapper config snapshots the pg data source", sf == [], str(sf))

print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}" + (f" ({', '.join(skipped)} NOT RUN)" if skipped else ""))
sys.exit(1 if fails else (77 if skipped else 0))
