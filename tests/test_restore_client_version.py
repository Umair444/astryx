#!/usr/bin/env python3
"""Oracle: restore_verify.sh restores with a pg_restore that can read the dump. backup.sh dumps with the container's
client when the host's is older than the server (host_pg_ok), so a dump from a 17 server is format 1.16, which the
distro's pg_restore 16 refuses ("unsupported version (1.16) in file header"). restore_verify.sh took the host's
pg_restore whenever it existed, so on 11-19 every core table read "did NOT restore" from a sound dump (medic).
DB-free: the block between `# >>> restore client` and `# <<< restore client` runs in bash after scripts/pgcontainer.sh,
with stand-in psql (the server's version) and pg_restore (its own) on PATH; its RMODE is read back.

  V1 host pg_restore 16, server 17: the container's (the 11-19 failure)
  V2 host pg_restore 17, server 17: the host's
  V3 host pg_restore 18, server 17: the host's
  V4 no host psql/pg_restore (MODE=docker): the container's
Seam: RESTORE_VERIFY_SRC (a mutant copy). Exit 0 · 1.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFY = Path(os.environ.get("RESTORE_VERIFY_SRC") or REPO / "scripts" / "restore_verify.sh")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def block():
    m = re.search(r"^# >>> restore client$.*?^# <<< restore client$", VERIFY.read_text(), re.S | re.M)
    return m.group(0) if m else None


def run(td: Path, client: int, server: int, mode: str = "host"):
    bin_ = td / f"bin{client}"
    bin_.mkdir(exist_ok=True)
    for name, body in (("psql", f"echo {server * 10000 + 11}"),
                       ("pg_restore", f"echo 'pg_restore (PostgreSQL) {client}.4'"),
                       ("docker", "exit 1")):          # never the real container
        (bin_ / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_ / name).chmod(0o755)
    src = (f". {REPO / 'scripts' / 'pgcontainer.sh'}\nDSN='postgresql://super_fx:pw@db.invalid:5432/fxorg'\n"
           f"MODE={mode}\n{block()}\necho \"$RMODE\"\n")
    r = subprocess.run(["bash", "-c", src], capture_output=True, text=True, timeout=30, cwd=td,
                       env={"PATH": f"{bin_}:/usr/bin:/bin", "ASTRYX_PG_CONTAINER": "fx-pg"})
    return r.stdout.strip(), r.stderr[-200:]


def main() -> int:
    if block() is None:
        check("restore_verify.sh carries the restore-client block", False, "no `# >>> restore client` block")
        print(f"\nFAIL: restore-verify's client reads the dump ({len(fails)} failing)")
        return 1
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        got, err = run(td, 16, 17)
        check("V1 host pg_restore 16, server 17: the container's (the 11-19 failure)", got == "docker", f"{got!r} {err}")
        got, err = run(td, 17, 17)
        check("V2 host pg_restore 17, server 17: the host's", got == "host", f"{got!r} {err}")
        got, err = run(td, 18, 17)
        check("V3 host pg_restore 18, server 17: the host's", got == "host", f"{got!r} {err}")
        got, err = run(td, 18, 17, mode="docker")
        check("V4 no host client (MODE=docker): the container's", got == "docker", f"{got!r} {err}")
    print(f"\n{'PASS' if not fails else 'FAIL'}: restore-verify's client reads the dump ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
