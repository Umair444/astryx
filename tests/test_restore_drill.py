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
    for tool in ("awk", "grep", "cut", "dirname", "mktemp", "bash", "cat", "psql", "tr"):
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
dr = DRILL.read_text()
check("the drill applies the roles file BEFORE pg_role_sync apply (the reconcile is the role's last writer, a1 #45231)",
      0 < dr.find('psql -X -q -v ON_ERROR_STOP=0') < dr.find('-m nucleus.pg_role_sync apply'))
check("…including 3, roles NOT VERIFIED on the newest dump", re.search(r"\n\s*3\)[^\n]*fail=1", block) is not None,
      block)

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

import os  # noqa: E402

FXROLE = f"astryx_fx_drill_{os.getpid()}"   # a throwaway NOLOGIN group: the fixture's GRANT names it, so a restore
live = psycopg.connect(pg_role_sync._live_dsn(), autocommit=True)   # without the roles file MUST error on it
live.execute(f"CREATE ROLE {FXROLE} NOLOGIN")


MINE = set()   # the drill containers THIS test started (named in each drill's ✓ line): other agents drill too


def drill(dump):
    r = subprocess.run(["timeout", "600", "bash", "nucleus/restore_drill.sh", str(dump)], cwd=REPO,
                       capture_output=True, text=True, timeout=620)
    out = r.stdout + r.stderr
    print("\n".join("        " + x for x in out.splitlines()))
    MINE.update(re.findall(r"container (astryx-restore-drill-\d+)\)", out))
    return r.returncode, out


try:
    with fixture_db() as fx, tempfile.TemporaryDirectory() as td:
        with psycopg.connect(fx["dsn"], autocommit=True) as c:
            c.execute("INSERT INTO goals (title, owner) VALUES ('drill', 'steward')")
            c.execute("INSERT INTO triggers (agent, name, schedule) VALUES ('steward', 'drill', '0 0 * * *')")
            c.execute("INSERT INTO steps (agent, kind, content) VALUES ('steward', 'milestone', 'drill')")
            c.execute("INSERT INTO messages (from_agent, to_agent, body) VALUES ('steward', 'steward', 'drill')")
            c.execute(f"GRANT SELECT ON goals TO {FXROLE}")
        dump = Path(td) / "small.dump"
        with open(dump, "wb") as f:
            d = subprocess.run(["docker", "exec", pg_role_sync.container(), "pg_dump", "-Fc", "-U",
                                pg_role_sync.target(fx["dsn"])["user"], "-d", fx["dbname"]], stdout=f,
                               stderr=subprocess.PIPE, timeout=120)
        check("the small fixture dump was made", d.returncode == 0 and dump.stat().st_size > 0,
              d.stderr[-200:].decode())
        roles = Path(td) / "small.roles.sql"
        with open(roles, "wb") as f:
            g = subprocess.run(["docker", "exec", pg_role_sync.container(), "pg_dumpall", "--roles-only",
                                "--no-role-passwords", "-U", pg_role_sync.target(fx["dsn"])["user"]], stdout=f,
                               stderr=subprocess.PIPE, timeout=60)
        rtext = roles.read_text()
        check("the paired roles file was made, names the fixture role, and carries no password material",
              g.returncode == 0 and f"CREATE ROLE {FXROLE};" in rtext and "PASSWORD '" not in rtext
              and "SCRAM-SHA-256" not in rtext)

        print("  [A] dump + its roles file:")
        rc, out = drill(dump)
        check("A: the drill exits 0", rc == 0, f"rc {rc}")
        for want in ("empty data dir initdb'd from", "after pg_role_sync apply the restored pgpass value logs in",
                     "the initdb placeholder is refused", "the paired roles file applied",
                     "pg_restore rc 0, 0 error lines", "steps restored 1 rows", "messages restored 1 rows",
                     "goals restored 1 rows", "triggers restored 1 rows"):
            check(f"A: ✓ {want}", f"✓ restore-drill: {want}" in out)

        print("  [B] the same dump, NO roles file (a dump older than roles capture):")
        roles.rename(Path(td) / "held.sql")
        rc, out = drill(dump)
        m = re.search(r"pg_restore rc \d+, (\d+) error line\(s\) \(text withheld; not gated", out)
        check("B: exit 3 and roles NOT VERIFIED (never 0: an unverified restore isn't a drilled one)",
              rc == 3 and "roles NOT VERIFIED" in out, f"rc {rc}")
        check("B: …and the GRANT to the absent role really errors (the discriminator, not a vacuous 0)",
              m is not None and int(m.group(1)) >= 1, m.group(0) if m else "no line")

        print("  [C] a roles file MISSING the role the grant names:")
        roles.write_text("\n".join(ln for ln in (Path(td) / "held.sql").read_text().splitlines()
                                   if FXROLE not in ln) + "\n")
        rc, out = drill(dump)
        check("C: exit 1, the restore named INCOMPLETE", rc == 1 and "the restore is INCOMPLETE" in out, f"rc {rc}")

        print("  [D] a roles file carrying a password verifier (pg_dumpall's default, hand-made at disaster time):")
        roles.write_text((Path(td) / "held.sql").read_text()
                         + "ALTER ROLE genesis WITH PASSWORD 'SCRAM-SHA-256$4096:AAAA$BBBB:CCCC';\n")
        rc, out = drill(dump)
        check("D: refused BEFORE apply, rc 1, naming password material", rc == 1 and "carries password material" in out
              and "the paired roles file applied" not in out, f"rc {rc}")
        check("D: …and the reconcile still holds (the restored pgpass value logs in)",
              "✓ restore-drill: after pg_role_sync apply the restored pgpass value logs in" in out)

        names = set(subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True,
                                   text=True).stdout.split())
        vols = set(subprocess.run(["docker", "volume", "ls", "-q"], capture_output=True, text=True).stdout.split())
        check("teardown: none of THIS test's drill containers or volumes remain (scoped by name: others drill too)",
              len(MINE) >= 4 and not (MINE & names) and not (MINE & vols),
              f"mine {len(MINE)}, left: containers {MINE & names}, volumes {MINE & vols}")
finally:
    live.execute(f"DROP ROLE IF EXISTS {FXROLE}")   # after the fixture DB (and its grant) is gone
    live.close()

print(f"\n{'FAIL: ' + str(len(fails)) + ' arm(s)' if fails else 'ALL PASS'}")
sys.exit(1 if fails else 0)
