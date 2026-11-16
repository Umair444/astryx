#!/usr/bin/env python3
"""Oracle: restore_verify.sh verifies as the PROVISIONER when the root-only superuser file is readable (cog-rls slice 2,
backup.sh's own switch). An org DSN (org_<key>) can't CREATE DATABASE and counts only the rows its row-level security
shows, so on a provisioned host the weekly verify failed at "cannot create scratch db" and the backups were never
restore-verified (medic 11-16). DB-free: the block between `# >>> super dsn` and `# <<< super dsn` runs in bash with
synthetic DSNs, and its DSN / SCRATCH_DSN are read back.

  S1 a URL superuser file: DSN is the superuser's on the ORG's database, SCRATCH_DSN the superuser's on the scratch
  S2 a key=value superuser file: both stay key=value (their spaces survive), on the org's and the scratch database
  S3 no superuser file: the org DSN is kept (and CREATE DATABASE fails loud later, as before)
  S4 a superuser file this user can't read: the org DSN is kept (skipped when run as root, which reads anything)
  S5 a superuser file that isn't a DSN: exit 1, said
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
ORG = "postgresql://org_fx:pw@db.invalid:5432/fxorg"
SCRATCH = "fxorg_restorecheck"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def block():
    m = re.search(r"^# >>> super dsn$.*?^# <<< super dsn$", VERIFY.read_text(), re.S | re.M)
    return m.group(0) if m else None


def interpreter() -> str | None:
    """The python the block will run as $ROOT/venv/bin/python: the checkout's venv when it has one, else this one;
    None when neither imports psycopg (a clean clone without its deps: the arms can't say anything, 77)."""
    for py in (REPO / "venv" / "bin" / "python", Path(sys.executable)):
        if py.exists() and subprocess.run([str(py), "-c", "import psycopg"], capture_output=True).returncode == 0:
            return str(py)
    return None


PY = interpreter()


def run(td: Path, super_file: Path):
    """The block in bash: its DSN and SCRATCH_DSN after it, its rc and stderr."""
    root = td / "root"
    (root / "venv" / "bin").mkdir(parents=True, exist_ok=True)
    py = root / "venv" / "bin" / "python"
    if not py.exists():     # a wrapper, not a symlink: a venv's python moved out of its venv loses its packages
        py.write_text(f"#!/bin/sh\nexec {PY} \"$@\"\n")
        py.chmod(0o755)
    src = (f"set -uo pipefail\nROOT={root}\nDSN='{ORG}'\nSCRATCH='{SCRATCH}'\nSCRATCH_DSN=\"${{DSN%/*}}/$SCRATCH\"\n"
           f"{block()}\nprintf '%s\\n%s\\n' \"$DSN\" \"$SCRATCH_DSN\"\n")
    r = subprocess.run(["bash", "-c", src], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "ASTRYX_PG_SUPER_FILE": str(super_file)})
    out = r.stdout.splitlines()
    return (out + ["", ""])[:2], r.returncode, r.stderr


def main() -> int:
    if block() is None:
        check("restore_verify.sh carries the super-dsn block", False, "no `# >>> super dsn` block")
        print(f"\nFAIL: restore-verify as the provisioner ({len(fails)} failing)")
        return 1
    if PY is None:
        print("  SKIP (77): no python here imports psycopg (the block's DSN rewrite needs it); nothing was verified")
        return 77
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        sf = td / "pg-super.dsn"

        sf.write_text("postgresql://super_fx:pw@db.invalid:5432/postgres\n")
        (dsn, scratch), rc, err = run(td, sf)
        check("S1 a URL superuser file: DSN is the superuser's, on the org's database",
              rc == 0 and dsn == "postgresql://super_fx:pw@db.invalid:5432/fxorg", f"rc {rc} {dsn!r} {err[-200:]}")
        check("S1 ...and SCRATCH_DSN is the superuser's, on the scratch database",
              scratch == f"postgresql://super_fx:pw@db.invalid:5432/{SCRATCH}", repr(scratch))

        sf.write_text("host=db.invalid port=5432 user=super_fx password=pw dbname=postgres\n")
        (dsn, scratch), rc, err = run(td, sf)
        check("S2 a key=value superuser file: DSN stays key=value, spaces and all, on the org's database",
              rc == 0 and "user=super_fx" in dsn and "dbname=fxorg" in dsn and " " in dsn, f"rc {rc} {dsn!r} {err[-200:]}")
        check("S2 ...and SCRATCH_DSN names the scratch database",
              "user=super_fx" in scratch and f"dbname={SCRATCH}" in scratch, repr(scratch))

        (dsn, scratch), rc, err = run(td, td / "absent.dsn")
        check("S3 no superuser file: the org DSN is kept", rc == 0 and dsn == ORG
              and scratch == f"postgresql://org_fx:pw@db.invalid:5432/{SCRATCH}", f"rc {rc} {dsn!r} {scratch!r}")

        if os.geteuid() == 0:
            print("  SKIP  S4 run as root: root reads a mode-000 file, so the arm can't say anything")
        else:
            sf.write_text("postgresql://super_fx:pw@db.invalid:5432/postgres\n")
            sf.chmod(0)
            (dsn, _), rc, _ = run(td, sf)
            sf.chmod(0o600)
            check("S4 a superuser file this user can't read: the org DSN is kept", rc == 0 and dsn == ORG, f"rc {rc} {dsn!r}")

        sf.write_text("this is not a dsn = = =\n")
        (_, _), rc, err = run(td, sf)
        check("S5 a superuser file that isn't a DSN: exit 1, said", rc == 1 and "unreadable as a DSN" in err,
              f"rc {rc} {err[-200:]}")
    print(f"\n{'PASS' if not fails else 'FAIL'}: restore-verify as the provisioner ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
