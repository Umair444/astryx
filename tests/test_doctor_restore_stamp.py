#!/usr/bin/env python3
"""doctor's restore-verify line reads the stamp's OUTCOME, and only an OK it can read is green (medic 11-20).

The live false green: restore_weekly runs restore_verify.sh under `sudo -n` with umask 077, so backups/.last-restore-ok
was root's 0600. doctor (non-root) read it as empty, empty is not "FAILED", the mtime was fresh, and it printed
"✓ backup restore-verified (, <8d — proven-restorable)" over a stamp that said FAILED.

The block is EXTRACTED from init.sh (between its `# >>> restore stamp` / `# <<< restore stamp` markers) and run in
bash with ok/bad/warn stubs against a temp ORGH. No database, no root.
  S1 an OK stamp, fresh: ok
  S2 a FAILED stamp: bad, naming FAILED and its time
  S3 a stamp doctor cannot read (mode 000): bad, never ok (the 11-20 case)
  S4 any other content (empty, garbage): bad
  S5 an OK stamp older than 8 days: bad STALE
  S6 no stamp, a dump present: warn never restore-verified
  S7 restore_verify.sh makes the stamp readable (chmod 644) after each write, the OK and the FAILED one
Exit 0 · 1 · 77 (run as root: mode 000 can't hide a file from root, S3 can't be shown).
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INIT = Path(os.environ.get("INIT_STAMP_SRC") or (REPO / "init.sh"))       # a mutant points this elsewhere
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    if os.geteuid() == 0:
        print("NOT SEARCHED: run as root, a mode-000 stamp is still readable; no arm ran.")
        return 77
    m = re.search(r"^ *# >>> restore stamp.*?^ *# <<< restore stamp$", INIT.read_text(), re.S | re.M)
    check("init.sh carries the restore stamp block between its markers", bool(m))
    if not m:
        return 1

    def doctor(stamp=None, mode=0o644, age_d=0):
        with tempfile.TemporaryDirectory() as td:
            bk = Path(td) / "backups"
            bk.mkdir()
            (bk / "astryx-x.dump").write_bytes(b"PGDMP")
            st = bk / ".last-restore-ok"
            if stamp is not None:
                st.write_text(stamp)
                t = time.time() - age_d * 86400
                os.utime(st, (t, t))
                st.chmod(mode)
            prog = ('ok() { echo "OK: $*"; }\nbad() { echo "BAD: $*"; }\nwarn() { echo "WARN: $*"; }\n'
                    f'ORGH="{td}"\nnewest_bk="{bk}/astryx-x.dump"\n' + m.group(0) + "\n")
            try:
                return subprocess.run(["bash", "-c", prog], capture_output=True, text=True, timeout=30).stdout
            finally:
                if stamp is not None:
                    st.chmod(0o644)

    out = doctor("OK 2026-11-20T01:33:21Z\n")
    check("S1 an OK stamp, fresh: green", out.startswith("OK: backup restore-verified (OK 2026-11-20"), out)
    out = doctor("FAILED 2026-11-19T15:32:46Z\n")
    check("S2 a FAILED stamp: red, naming its time", out.startswith("BAD:") and "FAILED" in out
          and "2026-11-19T15:32:46Z" in out, out)
    out = doctor("FAILED 2026-11-19T15:32:46Z\n", mode=0)
    check("S3 a stamp doctor can't read: red, never green (11-20)", out.startswith("BAD:") and "UNREADABLE" in out
          and "OK:" not in out, out)
    out = doctor("")
    out2 = doctor("garbage\n")
    check("S4 empty or other content: red", out.startswith("BAD:") and out2.startswith("BAD:"), out + out2)
    out = doctor("OK 2026-11-01T00:00:00Z\n", age_d=9)
    check("S5 an OK stamp older than 8 days: red STALE", out.startswith("BAD:") and "STALE" in out, out)
    out = doctor()
    check("S6 no stamp with a dump: never restore-verified", out.startswith("WARN:") and "never" in out, out)
    rv = (REPO / "scripts" / "restore_verify.sh").read_text()
    writes = [i for i, ln in enumerate(rv.splitlines()) if '> "$BK/.last-restore-ok"' in ln]
    lines = rv.splitlines()
    check("S7 restore_verify.sh chmods the stamp 644 after each of its writes (OK and FAILED)",
          len(writes) == 2 and all('chmod 644 "$BK/.last-restore-ok"' in lines[i + 1] for i in writes), str(writes))
    print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: doctor restore stamp")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
