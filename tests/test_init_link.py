#!/usr/bin/env python3
"""Oracle for init.sh's dispatcher link (seed #38930): the TRACKED `astryx` symlink stays the RELATIVE `init.sh`.
`ln -sf "$PWD/init.sh" "$PWD/astryx"` rewrote it to an absolute host path on every run: the tree went dirty, and a host
path sat one `git add -A` from a commit. The block between `# >>> dispatcher link` / `# <<< dispatcher link` is
extracted and run in temp dirs. Hermetic: no database, no network.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INIT = Path(os.environ.get("INIT_LINK_SRC") or (REPO / "init.sh"))          # mutation_probe points this at a mutant
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    src = INIT.read_text()
    m = re.search(r"^# >>> dispatcher link.*?^# <<< dispatcher link$", src, re.S | re.M)
    check("init.sh carries the dispatcher-link block between its markers", bool(m))
    if not m:
        return 1
    check("setup calls _link_dispatcher, and no line rewrites the repo link to an absolute $PWD path",
          "\n  _link_dispatcher\n" in src and not re.search(r'ln -s\w* "\$PWD/init\.sh" "\$PWD/astryx"', src))

    def run(d):
        return subprocess.run(["bash", "-c", m.group(0) + "\n_link_dispatcher\n"], cwd=d, capture_output=True,
                              text=True, timeout=30)
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "init.sh").write_text("#!/bin/sh\n")
        run(d)
        check("absent: the link is created RELATIVE (astryx -> init.sh)", os.readlink(d / "astryx") == "init.sh",
              os.readlink(d / "astryx") if (d / "astryx").is_symlink() else "no link")
        (d / "astryx").unlink()
        os.symlink(str(d / "init.sh"), d / "astryx")                      # the bug's state: an absolute host path
        run(d)
        check("absolute: the link is REWRITTEN relative", os.readlink(d / "astryx") == "init.sh",
              os.readlink(d / "astryx"))
        st = os.lstat(d / "astryx").st_mtime_ns
        run(d)
        check("already relative: it is left untouched (no rewrite, so a tracked link never churns)",
              os.lstat(d / "astryx").st_mtime_ns == st)
    with tempfile.TemporaryDirectory() as td:                              # ~/.local/bin: init.sh is itself a link
        d = Path(td)
        os.symlink("/somewhere/repo/init.sh", d / "astryx")
        run(d)
        check("where no REAL init.sh sits (run through the PATH link), nothing is touched",
              os.readlink(d / "astryx") == "/somewhere/repo/init.sh" and not (d / "init.sh").exists(),
              os.readlink(d / "astryx"))
    r = subprocess.run(["git", "ls-files", "-s", "astryx"], cwd=REPO, capture_output=True, text=True)
    blob = r.stdout.split()[1] if r.stdout else ""
    tgt = subprocess.run(["git", "cat-file", "-p", blob], cwd=REPO, capture_output=True, text=True).stdout if blob else ""
    check("the TRACKED link's target is the relative init.sh", r.stdout.startswith("120000") and tgt == "init.sh",
          f"{r.stdout.strip()} -> {tgt!r}")
    print(f"\n{'FAIL' if fails else 'PASS'}: init dispatcher link ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
