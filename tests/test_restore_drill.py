#!/usr/bin/env python3
"""Oracle for nucleus/restore_drill.sh, the empty-data-dir restore rehearsal (#5497, seed #44479/#44481).

  NOT RUN   with no docker on PATH, and with docker present but the declared image absent, the drill exits 2 and says
            NOT RUN, naming why. It never exits 0 for a path it didn't walk.
  WIRING    restore_verify.sh runs the drill BEFORE its OK stamp, under a wall cap, and any non-zero (NOT RUN and a
            timeout included) sets fail=1, so the stamp reads FAILED.
  LIVE      a SMALL dump (a stamped fixture DB with one row in each core table) drilled end to end on a throwaway server
            from the declared image: rc 0, every step's ✓ printed, and the container and volume are gone afterwards.
Exit 0 pass · 1 fail · 77 no docker or no image here (the NOT RUN and WIRING arms still ran).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
DRILL = REPO / "nucleus" / "restore_drill.sh"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def run(path_dirs, dump="/dev/null", timeout=60):
    return subprocess.run(["bash", str(DRILL), dump], cwd=REPO, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "PATH": ":".join(path_dirs)})


print("not run:")
with tempfile.TemporaryDirectory() as td:
    nodock = Path(td) / "nodock"
    nodock.mkdir()
    for tool in ("awk", "grep", "cut", "dirname", "mktemp", "bash", "cat"):
        w = shutil.which(tool)
        if w:
            (nodock / tool).symlink_to(w)
    r = run([str(nodock)])
    check("no docker on PATH → exit 2, NOT RUN, naming docker", r.returncode == 2 and "NOT RUN" in r.stderr
          and "docker" in r.stderr, f"rc {r.returncode}: {r.stderr[-200:]}")
    stub = Path(td) / "stub"
    stub.mkdir()
    (stub / "docker").write_text('#!/bin/sh\n[ "$1" = image ] && exit 1\nexit 0\n')
    (stub / "docker").chmod(0o755)
    r = run([str(stub), str(nodock)])
    check("docker present, the declared image absent → exit 2, NOT RUN, naming the image",
          r.returncode == 2 and "NOT RUN" in r.stderr and "not on this host" in r.stderr,
          f"rc {r.returncode}: {r.stderr[-200:]}")

print("wiring:")
rv = (REPO / "nucleus" / "restore_verify.sh").read_text()
i_drill, i_ok = rv.find("bash nucleus/restore_drill.sh"), rv.find('echo "OK $(date')
check("restore_verify runs the drill, and BEFORE the OK stamp", 0 < i_drill < i_ok, f"{i_drill} vs {i_ok}")
check("…under a wall cap", bool(re.search(r'timeout "\$DRILL_CAP" bash nucleus/restore_drill\.sh', rv)))
block = rv[i_drill:rv.find("esac", i_drill)]
check("…and every non-zero (NOT RUN, a timeout, a failed step) sets fail=1",
      "124)" in block and re.search(r"\*\)\s*fail=1", block) is not None, block)

print("live (a small dump, drilled):")
image = next((ln.split()[1] for ln in (REPO / "infra/pg/docker-compose.yml").read_text().splitlines()
              if ln.split()[:1] == ["image:"]), None)
have = shutil.which("docker") and subprocess.run(["docker", "image", "inspect", image], capture_output=True,
                                                  timeout=20).returncode == 0
if not have:
    print(f"  SKIP  live: no docker or no {image} here")
    print(f"\n{'FAIL' if fails else 'SKIP (partial)'}")
    sys.exit(1 if fails else 77)

import psycopg  # noqa: E402

from nucleus import pg_role_sync  # noqa: E402
from nucleus.sqlguard.fixture import fixture_db  # noqa: E402

with fixture_db() as fx, tempfile.TemporaryDirectory() as td:
    with psycopg.connect(fx["dsn"], autocommit=True) as c:
        c.execute("INSERT INTO goals (title, owner) VALUES ('drill', 'steward')")
        c.execute("INSERT INTO triggers (agent, name, schedule) VALUES ('steward', 'drill', '0 0 * * *')")
        c.execute("INSERT INTO steps (agent, kind, content) VALUES ('steward', 'milestone', 'drill')")
        c.execute("INSERT INTO messages (from_agent, to_agent, body) VALUES ('steward', 'steward', 'drill')")
    dump = Path(td) / "small.dump"
    with open(dump, "wb") as f:
        d = subprocess.run(["docker", "exec", pg_role_sync.container(), "pg_dump", "-Fc", "-U",
                            pg_role_sync.target(fx["dsn"])["user"], "-d", fx["dbname"]], stdout=f,
                           stderr=subprocess.PIPE, timeout=120)
    check("the small fixture dump was made", d.returncode == 0 and dump.stat().st_size > 0, d.stderr[-200:].decode())
    before = set(subprocess.run(["docker", "ps", "-aq", "--filter", "name=astryx-restore-drill-"],
                                capture_output=True, text=True).stdout.split())
    r = subprocess.run(["timeout", "600", "bash", str(DRILL), str(dump)], cwd=REPO, capture_output=True, text=True,
                       timeout=620)
    out = r.stdout + r.stderr
    print("\n".join("        " + x for x in out.splitlines()))
    check("the drill exits 0", r.returncode == 0, f"rc {r.returncode}")
    for want in ("initdb'd from", "after pg_role_sync apply the restored pgpass value logs in",
                 "the initdb placeholder is refused", "steps restored 1 rows", "messages restored 1 rows",
                 "goals restored 1 rows", "triggers restored 1 rows"):
        check(f"✓ {want}", f"✓ restore-drill: {want}" in out)
    after = set(subprocess.run(["docker", "ps", "-aq", "--filter", "name=astryx-restore-drill-"],
                               capture_output=True, text=True).stdout.split())
    vols = subprocess.run(["docker", "volume", "ls", "-q", "--filter", "name=astryx-restore-drill-"],
                          capture_output=True, text=True).stdout.split()
    check("teardown: no drill container and no drill volume remain", after <= before and not vols,
          f"containers {after - before}, volumes {vols}")

print(f"\n{'FAIL: ' + str(len(fails)) + ' arm(s)' if fails else 'ALL PASS'}")
sys.exit(1 if fails else 0)
