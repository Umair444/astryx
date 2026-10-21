"""devtools/marker.sh: the author's half of a merge-ready marker is read from git and pushed_tree_check, never typed.
Hermetic: a temp git repo, and stub pushed_tree_checks (MARKER_PTC) that print a green, a red, no verdict, or move the
branch mid-run. Arms: full shas equal git's; the clause copies rc and FAILED set; a check with no verdict line, or a
branch that moved during it, prints NO clause (rc 2); no `merge-ready:` line is ever printed (never self-mark).

    venv/bin/python tests/test_marker.py      (MARKER_SRC: mutation_probe's channel)
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = os.environ.get("MARKER_SRC") or str(REPO / "devtools" / "marker.sh")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


ENV = {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, "GIT_AUTHOR_NAME": "t",
       "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1",
       "GIT_CONFIG_GLOBAL": os.devnull}
GREEN = "echo \"$1\" > \"$(dirname \"$0\")/got\"; echo; echo 'check: 99 verified, 172 UNVERIFIED (skips allowed here) — NOT a full pass'; exit 0"
RED = ("echo 'FAILED (2):'; echo '  ✗ gate census: no literal port'; echo '  ✗ mutants files point at something real';"
       " echo 'UNVERIFIED (172) — …'; echo '  ○ x'; echo; echo 'check: 97 verified, 172 UNVERIFIED'; exit 1")
SILENT = "echo 'started'; exit 124"


def main():
    with tempfile.TemporaryDirectory(prefix="marker-") as t:
        r = Path(t) / "w"

        def git(*a):
            return subprocess.run(["git", *a], cwd=r, env=ENV, capture_output=True, text=True, check=True).stdout.strip()

        def run(stub, *a):
            s = Path(t) / "ptc.sh"
            s.write_text("#!/bin/bash\n" + stub + "\n")
            p = subprocess.run(["bash", SRC, *a], cwd=r, env={**ENV, "MARKER_PTC": f"bash {s}"},
                               capture_output=True, text=True, timeout=60)
            return p.returncode, p.stdout + p.stderr

        r.mkdir()
        git("init", "-q", "-b", "main")
        (r / "a").write_text("a\n"); git("add", "."); git("commit", "-qm", "base")
        base = git("rev-parse", "HEAD")
        git("checkout", "-qb", "feat")
        (r / "b").write_text("b\n"); git("add", "."); git("commit", "-qm", "feat")
        tip = git("rev-parse", "HEAD")
        git("checkout", "-q", "main")
        (r / "c").write_text("c\n"); git("add", "."); git("commit", "-qm", "main moves")   # base = merge-base, not main

        rc, out = run(GREEN, "feat")
        check("green: the full-sha range is the MERGE-BASE..the branch head, both read from git",
              rc == 0 and f"range (full): feat {base}..{tip}" in out, out)
        check("green: the clause carries the check's own rc, FAILED none and its counts, on the exact tip",
              f"marker clause: feat {base[:12]}..{tip[:12]} · pushed_tree_check {tip[:12]} (author): rc 0, FAILED none, "
              "99 verified, 172 UNVERIFIED" in out, out)
        got = (Path(t) / "got").read_text().strip() if (Path(t) / "got").exists() else ""
        check("green: the stub was handed the FULL head sha (the check runs on the exact tip)", got == tip, got)
        check("no `merge-ready:` line is ever printed (the marker is the reviewer's)", "merge-ready:" not in out, out)
        rc, out = run(RED, "feat")
        check("red: the clause states rc 1 and the FAILED set copied verbatim, in order",
              rc == 0 and "rc 1, FAILED gate census: no literal port; mutants files point at something real, 97 verified"
              in out, out)
        rc, out = run(SILENT, "feat")
        check("a check that printed no verdict line (killed: rc 124) gets NO clause, rc 2, naming why",
              rc == 2 and "marker clause" not in out and "printed no verdict line (rc 124)" in out, out)
        moved = f"cd {r} && git checkout -q feat && echo x > d && git add d && git commit -qm moved && git checkout -q main; " \
                + GREEN
        rc, out = run(moved, "feat")
        check("a branch that MOVED during the check gets NO clause, rc 2 (a marker names the tip that was checked)",
              rc == 2 and "moved during the check" in out and "marker clause" not in out, out)
        rc, out = run(GREEN, "nope")
        check("an unknown branch is rc 2", rc == 2 and "unknown branch" in out, out)
        rc, out = run(GREEN, "main")
        check("a branch with nothing beyond the base is rc 2 (nothing to mark)", rc == 2 and "nothing to mark" in out, out)
    print(f"\n{'FAIL' if fails else 'PASS'}: marker ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
