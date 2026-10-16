#!/usr/bin/env python3
"""Oracle for devtools/land.sh: the merger's half of a merge-ready marker (seed night-review 10-16). Hermetic: each
arm gets a throwaway work repo with a bare origin, so a push and a refused push are both real git.

Arms: a green range lands, pushes and prints a receipt read from git; the child test runs WITHOUT ASTRYX_AGENT (measured
by the test itself); a red test rolls main back and pushes nothing; a non-ff range, a dirty tracked tree, a wrong live
body sha and a range with no test are refused with main untouched; an A that isn't B's ancestor is refused; a push that
fails exits 3 and says NOT PUSHED.

    venv/bin/python tests/test_land.py      (LAND_SRC: mutation_probe's channel)
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("LAND_SRC") or (REPO / "devtools" / "land.sh"))
fails = []

OK_TEST = """import os, sys
from pathlib import Path
Path(sys.argv[0]).resolve().parent.parent.joinpath("ran.txt").write_text(
    "agent=" + os.environ.get("ASTRYX_AGENT", "<absent>"))
print("1/1 passed")
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
ENV.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
           PY=sys.executable, ASTRYX_AGENT="seed", LAND_PROBE=str(REPO / "devtools" / "mutation_probe.py"))

SUB_ORACLE = """import os, sys
from pathlib import Path
src = Path(os.environ.get("SUB_SRC") or Path(__file__).resolve().parent.parent / "sub.py")
ns = {}
try:
    exec(src.read_text(), ns)
except Exception:
    sys.exit(1)
sys.exit(0 if ns.get("VALUE") == 1 else 1)
"""


def mutants(old, new):
    return ("from pathlib import Path\nREPO = Path(__file__).resolve().parent.parent\n"
            "SUBJECT = REPO / 'sub.py'\nORACLE = REPO / 'tests' / 'test_sub.py'\nENV = 'SUB_SRC'\n"
            f"MUTANTS = {{'m': ({old!r}, {new!r})}}\n")


class Fx:
    """A work repo on main (1 commit, pushed to a bare origin) with branch feat forked from it."""

    def __init__(self, feat_files, base_files=None):
        root = Path(tempfile.mkdtemp(prefix="land-"))
        self.origin, self.w = root / "origin.git", root / "w"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], env=ENV, check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.w)], env=ENV, check=True)
        (self.w / ".gitignore").write_text("ran.txt\nbody.py\n__pycache__/\n")
        (self.w / "README").write_text("r\n")
        for rel, body in (base_files or {}).items():
            p = self.w / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body)
        self.git("add", "."); self.git("commit", "-qm", "base")
        self.git("remote", "add", "origin", str(self.origin)); self.git("push", "-q", "origin", "main")
        self.base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-qb", "feat")
        for rel, body in feat_files.items():
            p = self.w / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body)
        self.git("add", "."); self.git("commit", "-qm", "feat")
        self.head = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "main")

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.w, env=ENV, capture_output=True, text=True, check=True).stdout.strip()

    def land(self, *a):
        p = subprocess.run(["bash", str(SRC), *a], cwd=self.w, env=ENV, capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout + p.stderr

    def main(self):
        return self.git("rev-parse", "main")

    def origin_main(self):
        return subprocess.run(["git", "--git-dir", str(self.origin), "rev-parse", "main"], env=ENV,
                              capture_output=True, text=True).stdout.strip()


def main():
    # L1 green: lands, pushes, receipt from git, child has no ASTRYX_AGENT
    f = Fx({"tests/test_ok.py": OK_TEST})
    rc, out = f.land(f"{f.base[:12]}..{f.head[:12]}")
    check("L1 a green range fast-forwards main and pushes (rc 0, main = origin/main = B)",
          rc == 0 and f.main() == f.head and f.origin_main() == f.head, out)
    rec = [l for l in out.splitlines() if l.startswith("RECEIPT:")]
    check("L1 one RECEIPT line: LANDED + PUSHED, 'range tests (not check.sh)', the test's rc, origin/main read back from git",
          len(rec) == 1 and "LANDED + PUSHED" in rec[0] and "range tests (not check.sh)" in rec[0] and "test_ok.py rc 0" in rec[0]
          and f"origin/main = {f.head[:12]}" in rec[0], out)
    ran = f.w / "ran.txt"
    check("L1 the range's test RAN (anti-vacuity: it wrote its marker)", ran.exists(), out)
    check("L1 the child ran WITHOUT ASTRYX_AGENT (the caller's was 'seed')",
          ran.exists() and ran.read_text() == "agent=<absent>", ran.read_text() if ran.exists() else "no marker")

    # L2 red: rolled back, nothing pushed
    f = Fx({"tests/test_red.py": "import sys; print('boom'); sys.exit(1)\n"})
    rc, out = f.land(f"{f.base}..{f.head}")
    check("L2 a red test exits 1, rolls main back to where it was, and pushes nothing",
          rc == 1 and f.main() == f.base and f.origin_main() == f.base and "rolled back" in out, out)
    check("L2 the red test's output is shown", "boom" in out, out)

    # L3 non-ff
    f = Fx({"tests/test_ok.py": OK_TEST})
    (f.w / "other").write_text("o\n"); f.git("add", "."); f.git("commit", "-qm", "main moved")
    moved = f.main()
    rc, out = f.land(f"{f.base}..{f.head}")
    check("L3 a range that doesn't fast-forward main is refused by land's own check (naming B and main), main untouched",
          rc == 1 and "does not fast-forward main" in out and f.main() == moved and not (f.w / "ran.txt").exists(), out)

    # L4 dirty tracked tree (the 10-15 stash round-trip)
    f = Fx({"tests/test_ok.py": OK_TEST})
    (f.w / "README").write_text("edited, unstaged\n")
    rc, out = f.land(f"{f.base}..{f.head}")
    check("L4 tracked changes in the tree are refused before any merge",
          rc == 1 and "tracked changes" in out and f.main() == f.base, out)
    f.git("add", "README")
    rc, out = f.land(f"{f.base}..{f.head}")
    check("L4 …and a STAGED change is refused too", rc == 1 and "tracked changes" in out and f.main() == f.base, out)

    # L5 live body sha
    f = Fx({"tests/test_ok.py": OK_TEST})
    (f.w / "body.py").write_text("x = 1\n")
    import hashlib
    good = hashlib.sha256(b"x = 1\n").hexdigest()
    rc, out = f.land(f"{f.base}..{f.head}", "--body", "body.py=" + ("0" if good[0] != "0" else "1") + good[1:12])
    check("L5 a live body whose sha256 isn't the PASSed prefix is refused, main untouched",
          rc == 1 and "body body.py" in out and f.main() == f.base, out)
    for short in (good[:1], good[:11], good[:12].upper(), good[:12] + "zz"):
        rc, out = f.land(f"{f.base}..{f.head}", "--body", f"body.py={short}", "--no-push")
        check(f"L5 a body sha that isn't 12-64 lowercase hex ({short!r}) is a usage error, even when it IS a prefix "
              "(steward #56607)", rc == 2 and "12-64 lowercase hex" in out and f.main() == f.base, out)
    rc, out = f.land(f"{f.base}..{f.head}", "--body", f"body.py={good[:12]}", "--no-push")
    check("L5 …and the PASSed prefix lands, the receipt naming the live sha (--no-push: origin untouched)",
          rc == 0 and f.main() == f.head and f.origin_main() == f.base and f"body.py {good[:12]}" in out
          and "LANDED (not pushed" in out, out)

    # L6 no test in the range
    f = Fx({"docs/x.md": "doc\n"})
    rc, out = f.land(f"{f.base}..{f.head}")
    check("L6 a range touching no test, with no --test, is refused", rc == 1 and "touches no tests" in out and f.main() == f.base, out)

    # L7 A not an ancestor of B
    f = Fx({"tests/test_ok.py": OK_TEST})
    f.git("checkout", "-qb", "side", f.base); (f.w / "s").write_text("s\n"); f.git("add", "."); f.git("commit", "-qm", "side")
    side = f.git("rev-parse", "HEAD"); f.git("checkout", "-q", "main")
    rc, out = f.land(f"{side}..{f.head}")
    check("L7 an A that isn't B's ancestor is refused", rc == 1 and "not an ancestor" in out and f.main() == f.base, out)

    # L8 push fails
    f = Fx({"tests/test_ok.py": OK_TEST})
    f.git("remote", "set-url", "origin", str(f.w.parent / "nowhere.git"))
    rc, out = f.land(f"{f.base}..{f.head}")
    check("L8 a failed push exits 3 and says NOT PUSHED (main merged and green, origin unchanged)",
          rc == 3 and "NOT PUSHED" in out and f.main() == f.head and f.origin_main() == f.base, out)

    # L9 commits between main and A (a4 #56483 R1): c1 is nobody's PASS
    f = Fx({"secret_change": "x\n"})
    c1 = f.head
    f.git("checkout", "-q", "feat"); (f.w / "tests").mkdir(exist_ok=True)
    (f.w / "tests" / "test_ok.py").write_text(OK_TEST); f.git("add", "."); f.git("commit", "-qm", "c2")
    c2 = f.git("rev-parse", "HEAD"); f.git("checkout", "-q", "main")
    rc, out = f.land(f"{c1}..{c2}", "--no-push")
    check("L9 an A newer than main is refused (OLD..A would land unreviewed), main untouched",
          rc == 1 and "would land unreviewed" in out and f.main() == f.base and not (f.w / "secret_change").exists(), out)
    rc, out = f.land(f"{f.base}..{c2}", "--no-push")
    check("L9 …and the whole range from main lands", rc == 0 and f.main() == c2, out)

    # L10 a mutants-only range runs through mutation_probe (a4 #56483 R2)
    sub = {"sub.py": "VALUE = 1\nOTHER = 5\n", "tests/test_sub.py": SUB_ORACLE}
    f = Fx({"tests/mutants_sub.py": mutants("VALUE = 1", "VALUE = 2")}, sub)
    rc, out = f.land(f"{f.base}..{f.head}", "--no-push")
    check("L10 a mutants-only range runs the PROBE (its CAUGHT line is in the output) and lands",
          rc == 0 and f.main() == f.head and "1 CAUGHT by the probe" in out and "mutants_sub.py rc 0" in out, out)
    f = Fx({"tests/mutants_sub.py": mutants("OTHER = 5", "OTHER = 6")}, sub)
    rc, out = f.land(f"{f.base}..{f.head}", "--no-push")
    check("L10 …and a mutant the oracle misses is RED: rolled back, never 'rc 0 ()'",
          rc == 1 and f.main() == f.base and "rolled back" in out, out)

    # L11 a test that writes the tracked tree (a4 #56483 R3)
    writer = ("import sys\nfrom pathlib import Path\np = Path(__file__).resolve().parent.parent / 'f'\n"
              "p.write_text(p.read_text() + 'more\\n')\nsys.exit({rc})\n")
    f = Fx({"f": "one\n", "tests/test_w.py": writer.format(rc=1)})
    rc, out = f.land(f"{f.base}..{f.head}")
    check("L11 red and the rollback FAILS (the test dirtied a file the range changed): rc 4, a RECEIPT says main is "
          "NOT rolled back, nothing pushed",
          rc == 4 and "RECEIPT: RED, main NOT rolled back" in out and f.main() == f.head and f.origin_main() == f.base, out)
    f = Fx({"f": "one\n", "tests/test_w.py": writer.format(rc=0)})
    rc, out = f.land(f"{f.base}..{f.head}")
    check("L11 a GREEN test that dirtied the tracked tree is red too, naming the file; nothing pushed",
          rc in (1, 4) and "DIRTIED" in out and " f" in out.split("DIRTIED", 1)[1].splitlines()[0]
          and f.origin_main() == f.base, out)

    # L12 untracked files where a test could import them (a4 #56483 MC2)
    f = Fx({"tests/test_ok.py": OK_TEST})
    (f.w / "tests").mkdir(exist_ok=True); (f.w / "tests" / "stray.py").write_text("X = 1\n")
    rc, out = f.land(f"{f.base}..{f.head}")
    check("L12 an untracked file under tests/ is refused before any merge",
          rc == 1 and "untracked" in out and "stray.py" in out and f.main() == f.base, out)

    # L13 a refused push names its gate (10-16: the label of a pre-push red was lost to tail -2)
    f = Fx({"tests/test_ok.py": OK_TEST})
    hook = f.w / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho 'lots of earlier output'\n"
                    + "".join(f"echo '  ✗ a gate arm decoy {i}'\n" for i in range(13))
                    + "echo 'FAILED (1):'\necho '  ✗ gate named here'\n"
                    + "".join(f"echo 'trailing line {i}'\n" for i in range(5)) + "exit 1\n")
    hook.chmod(0o755)
    rc, out = f.land(f"{f.base}..{f.head}")
    check("L13 a refused push prints the pre-push gate's FAILED and ✗ lines as 'push gate:' (rc 3), past 13 decoy ✗ arms",
          rc == 3 and "push gate: FAILED (1):" in out and "push gate:   ✗ gate named here" in out, out)

    # L14 a --test the range already names runs once, not twice
    f = Fx({"tests/test_ok.py": OK_TEST})
    rc, out = f.land(f"{f.base}..{f.head}", "--test", "./tests/test_ok.py", "--no-push")
    check("L14 a --test already in the range runs once, even spelled ./tests/…", rc == 0 and out.count("test_ok.py: rc 0") == 1, out)

    print(f"\n{'PASS' if not fails else 'FAIL'}: land ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
