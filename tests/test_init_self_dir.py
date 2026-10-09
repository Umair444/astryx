#!/usr/bin/env python3
"""Oracle for init.sh's start directory (a2 #39198): however init.sh is invoked (directly, through the PATH link in
~/.local/bin, through a CHAIN of links, through a RELATIVE link), it runs in the directory that holds the real init.sh.
The block between `# >>> self dir` / `# <<< self dir` is extracted and run with $0 set to each invocation path, in
temp dirs. Hermetic: nothing of init.sh beyond that block runs.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INIT = Path(os.environ.get("INIT_SELF_SRC") or (REPO / "init.sh"))          # mutation_probe points this at a mutant
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    src = INIT.read_text()
    m = re.search(r"^# >>> self dir.*?^# <<< self dir$", src, re.S | re.M)
    check("init.sh carries the self-dir block between its markers, before anything else runs", bool(m)
          and src.index("# >>> self dir") < src.index("say() {"))
    if not m:
        return 1
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]   # a MENTION in a comment is not a READ
    check("no executable line still cds to the dirname of $0 (the old start directory)",
          not any('cd "$(dirname "$0")"' in ln for ln in code))

    def where(zero, cwd):
        r = subprocess.run(["bash", "-c", m.group(0) + "\npwd -P\n", zero], cwd=cwd, capture_output=True, text=True,
                           timeout=30)
        return r.stdout.strip(), r.stderr.strip()
    with tempfile.TemporaryDirectory() as td:
        t = Path(td).resolve()
        repo = t / "repo"
        repo.mkdir()
        (repo / "init.sh").write_text("#!/bin/sh\n")
        binp = t / "bin"
        binp.mkdir()
        os.symlink(str(repo / "init.sh"), binp / "astryx")                  # the PATH link: absolute
        os.symlink("../repo/init.sh", binp / "astryx-rel")                  # a RELATIVE link
        os.symlink(str(binp / "astryx"), t / "chain")                       # a CHAIN: link → link → init.sh
        elsewhere = t / "elsewhere" / "deep"        # NOT a sibling of bin/: "../repo" from here is a different path,
        elsewhere.mkdir(parents=True)              # so a target taken relative to the CWD can't land right by luck
        for label, zero in (("direct", str(repo / "init.sh")), ("the absolute PATH link", str(binp / "astryx")),
                            ("a relative link", str(binp / "astryx-rel")), ("a chain of links", str(t / "chain"))):
            out, err = where(zero, elsewhere)
            check(f"invoked via {label} from another directory → runs in the repo", out == str(repo), f"{out} {err}")
    with tempfile.TemporaryDirectory() as td:                              # a2 #39682: a CYCLE fails loud, never hangs
        t = Path(td)
        os.symlink(str(t / "loopB"), t / "loopA")
        os.symlink(str(t / "loopA"), t / "loopB")
        try:
            r = subprocess.run(["bash", "-c", m.group(0) + "\npwd -P\n", str(t / "loopA")], cwd=t, capture_output=True,
                               text=True, timeout=10)
            rc, err = r.returncode, r.stderr
        except subprocess.TimeoutExpired:
            rc, err = "TIMEOUT (hangs)", ""
        check("a link CYCLE exits 1 naming the loop, within seconds (never a silent hang)",
              rc == 1 and "init.sh: link loop at" in err, f"rc={rc} {err[-120:]}")
    print(f"\n{'FAIL' if fails else 'PASS'}: init start directory ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
