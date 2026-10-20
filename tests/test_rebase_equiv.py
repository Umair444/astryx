"""devtools/rebase_equiv.py: a rebased range is PROVEN the same work only by a per-commit replay (merge-tree of each
reviewed commit onto its rebased twin's parent, the tree equal to the twin's); a conflicted commit is HAND-RESOLVED (rc 3)
unless its weaker fallback finds a difference; messages compare as raw bytes; a merge in a range is refused.
Hermetic: one temp git repo per case, GIT_* scrubbed, no global or system config, no estate, no DB.
Cases: 10-20's real shapes (a context edit near a hunk; an adjacent one, resolved by hand; a '#'-stripped message; a
branch that no longer lands), a3's six bypasses of the first cut (#61571 X1-X6), and the fallback's own REDs.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = os.environ.get("REBASE_EQUIV_SRC") or str(REPO / "devtools" / "rebase_equiv.py")   # mutation_probe's copy
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


# the host's GIT_* (a hook's GIT_DIR, GIT_CONFIG_PARAMETERS) would point every call at another repo; the rest inherits
ENV = {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, "GIT_AUTHOR_NAME": "t",
       "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1",
       "GIT_CONFIG_GLOBAL": os.devnull}
TEN = "".join(f"line {i}\n" for i in range(1, 11))
TWO = "def f():\n    a = 1\n    return a\n\n\ndef g():\n    b = 2\n    return b\n"
MSG = "change it\n\nwhy, wrapped so the next line starts with a msg id:\n#61157) lands after.\n"


class Repo:
    def __init__(self, path):
        self.r = path
        self.git("init", "-q", "-b", "main")

    def git(self, *a, inp=None):
        return subprocess.run(["git", *a], cwd=self.r, env=ENV, capture_output=True, text=True, input=inp,
                              check=True).stdout.strip()

    def commit(self, files=None, msg=MSG, modes=None, delete=(), verbatim=True):
        for name, data in (files or {}).items():
            p = self.r / name
            p.write_bytes(data) if isinstance(data, bytes) else p.write_text(data)
        for name in delete:
            (self.r / name).unlink()
        for name, m in (modes or {}).items():
            os.chmod(self.r / name, m)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "--cleanup=" + ("verbatim" if verbatim else "strip"), "-F", "-",
                 inp=msg)
        return self.git("rev-parse", "HEAD")

    def tool(self, *a):
        p = subprocess.run([sys.executable, TOOL, *a], cwd=self.r, env=ENV, capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr


def scenario(t, base, reviewed, rebased, main=None):
    """-> (repo, reviewed range, rebased range). reviewed/rebased: lists of Repo.commit kwargs; main: files main
    commits before the rebased side is built on it (default: an unrelated file, so main always moved)."""
    rp = Repo(Path(tempfile.mkdtemp(dir=t)))
    b0 = rp.commit(base, "base\n")
    rp.git("checkout", "-q", "-b", "rev")
    for c in reviewed:
        tip = rp.commit(**c)
    rp.git("checkout", "-q", "main")
    m1 = rp.commit(main or {"other.txt": "main moved\n"}, "main moves\n")
    rp.git("checkout", "-q", "-b", "reb")
    for c in rebased:
        rtip = rp.commit(**c)
    rp.git("checkout", "-q", "main")
    return rp, f"{b0}..{tip}", f"{m1}..{rtip}"


def main():
    with tempfile.TemporaryDirectory(prefix="rebase-equiv-") as t:
        five = TEN.replace("line 5\n", "line FIVE\n")

        # ── PROVEN: main edited line 3, inside the hunk's CONTEXT but not adjacent: the replay merges clean ─────────
        rp, rv, rb = scenario(t, {"a.py": TEN, "b.py": "b\n"},
                              [dict(files={"a.py": five}), dict(files={"b.py": "b\nmore\n"}, msg="add to b\n")],
                              [dict(files={"a.py": five.replace("line 3\n", "line three\n")}),
                               dict(files={"b.py": "b\nmore\n"}, msg="add to b\n")],
                              main={"a.py": TEN.replace("line 3\n", "line three\n")})
        rc, out = rp.tool(rv, rb, "--onto", "")
        check("a rebase over a main edit in the hunk's CONTEXT is SAME WORK, each commit PROVEN by replay, rc 0",
              rc == 0 and out.count(": PROVEN (") == 2 and "SAME WORK: 2 commit(s)" in out, out)
        line = next((ln for ln in out.split("\n") if ln.startswith("  a.py:")), "")
        check("…while a.py's blob AND patch-id both moved (neither can be the verdict: the discriminator is real)",
              "blob EQUAL" not in line and " both " not in line and "(information)" in line, line or out)
        stripped = scenario(t, {"a.py": TEN}, [dict(files={"a.py": five})], [dict(files={"a.py": five}, verbatim=False)])
        rc, out = stripped[0].tool(stripped[1], stripped[2], "--onto", "")
        check("a rebase whose cleanup dropped the '#61157)' message line DIFFERS, naming the commit and the line",
              rc == 1 and "MESSAGE of commit 1" in out and "#61157) lands after." in out and ": PROVEN (" in out, out)
        rp, rv, rb = scenario(t, {"a.py": TEN}, [dict(files={"a.py": five})],
                              [dict(files={"a.py": TEN.replace("line 5\n", "line 5ive\n")})])
        rc, out = rp.tool(rv, rb, "--onto", "")
        check("a rebase that CHANGED a line DIFFERS: the replay is clean, its tree isn't the rebased one",
              rc == 1 and "the replay is clean but its tree differs from the rebased one in ['a.py']" in out, out)
        rp, rv, rb = scenario(t, {"a.py": TEN, "b.py": "b\n"},
                              [dict(files={"a.py": five}), dict(files={"b.py": "b\nmore\n"}, msg="add to b\n")],
                              [dict(files={"a.py": five})])
        rc, out = rp.tool(rv, rb, "--onto", "")
        check("a rebase that dropped a commit DIFFERS on the count (the file set is information only)",
              rc == 1 and "COMMITS: 2 reviewed vs 1 rebased" in out and "files (information):" in out, out)
        # a3 #61585: main RENAMED the file the commit edits. The replay follows the rename and proves it; a file set
        # compared by path would read r.py vs s.py as a difference, a false alarm on unchanged work
        body = "".join(f"row {i} of a file long enough for rename detection\n" for i in range(1, 21))
        edited = body.replace("row 10 ", "row TEN ")
        rp = Repo(Path(tempfile.mkdtemp(dir=t)))
        b0 = rp.commit({"r.py": body}, "base\n")
        rp.git("checkout", "-q", "-b", "rev")
        tip = rp.commit({"r.py": edited})
        rp.git("checkout", "-q", "main")
        rp.git("mv", "r.py", "s.py")
        m1 = rp.commit(msg="main renames r.py to s.py\n")
        rp.git("checkout", "-q", "-b", "reb")
        rtip = rp.commit({"s.py": edited})
        rp.git("checkout", "-q", "main")
        rc, out = rp.tool(f"{b0}..{tip}", f"{m1}..{rtip}", "--onto", "")
        check("a commit over a main-side RENAME is SAME WORK, rc 0 (the replay follows it; the file set is information)",
              rc == 0 and ": PROVEN (" in out and "files (information): only reviewed ['r.py'], only rebased ['s.py']"
              in out, out)

        # ── a3 #61571's six bypasses of the first cut: each does DIFFERENT work with identical messages ─────────────
        for name, base, rev, reb in (
                ("X1 the same added line in g(), not f()", {"m.py": TWO},
                 [dict(files={"m.py": TWO.replace("    a = 1\n", "    a = 1\n    assert a\n")})],
                 [dict(files={"m.py": TWO.replace("    b = 2\n", "    b = 2\n    assert a\n")})]),
                ("X2 a binary's content differs", {"x.bin": b"\x00\x01base"},
                 [dict(files={"x.bin": b"\x00\x01REVIEWED"})], [dict(files={"x.bin": b"\x00\x01OTHER!!!"})]),
                ("X3 the exec bit the reviewed commit set is dropped", {"s.sh": "echo hi\n"},
                 [dict(files={"s.sh": "echo hi\necho two\n"}, modes={"s.sh": 0o755})],
                 [dict(files={"s.sh": "echo hi\necho two\n"}, modes={"s.sh": 0o644})]),
                ("X4 a file deleted vs emptied", {"d.py": "x = 1\n"}, [dict(delete=["d.py"])],
                 [dict(files={"d.py": ""})]),
                ("X5 the change moved from commit 1 to commit 2", {"a.py": "a\n", "b.py": "b\n"},
                 [dict(files={"a.py": "a\nA\n"}, msg="one\n"), dict(files={"b.py": "b\nB\n"}, msg="two\n")],
                 [dict(files={"a.py": "a\nA\n", "b.py": "b\nB\n"}, msg="one\n"), dict(msg="two\n")]),
                ("X6 'p NEW q r' vs 'p q NEW r'", {"o.py": "p\nq\nr\n"},
                 [dict(files={"o.py": "p\nNEW\nq\nr\n"})], [dict(files={"o.py": "p\nq\nNEW\nr\n"})])):
            rp, rv, rb = scenario(t, base, rev, reb)
            rc, out = rp.tool(rv, rb, "--onto", "")
            check(f"a3 {name}: DIFFERS (rc 1), never SAME WORK", rc == 1 and "SAME WORK" not in out, out)

        # ── HAND-RESOLVED: main edited line 4, ADJACENT to the reviewed line 5, so the replay conflicts ─────────────
        adj = {"a.py": TEN.replace("line 4\n", "line four\n")}
        resolved = five.replace("line 4\n", "line four\n")
        rp, rv, rb = scenario(t, {"a.py": TEN}, [dict(files={"a.py": five})], [dict(files={"a.py": resolved})], main=adj)
        rc, out = rp.tool(rv, rb, "--onto", "")
        check("a commit resolved by hand (adjacent edits) is HAND-RESOLVED, rc 3, never SAME WORK",
              rc == 3 and "HAND-RESOLVED in ['a.py']" in out and "PLACEMENT UNPROVEN" in out and "SAME WORK" not in out,
              out)
        check("…and the rebased hunk is printed for the reviewer", "      +line FIVE" in out, out)
        rp, rv, rb = scenario(t, {"a.py": TEN, "c.py": "c\n"}, [dict(files={"a.py": five, "c.py": "c\nC\n"})],
                              [dict(files={"a.py": resolved, "c.py": "c\nOTHER\n"})], main=adj)
        rc, out = rp.tool(rv, rb, "--onto", "")
        check("…a hand-resolved commit whose CLEANLY merged file differs DIFFERS (per-file proof inside a conflict)",
              rc == 1 and "files the replay merged CLEANLY differ from the rebased commit: ['c.py']" in out, out)
        rp, rv, rb = scenario(t, {"a.py": TEN}, [dict(files={"a.py": five})],
                              [dict(files={"a.py": resolved.replace("line FIVE\n", "line 5ive\n")})], main=adj)
        rc, out = rp.tool(rv, rb, "--onto", "")
        check("…a hand resolution whose +/- lines differ DIFFERS (the fallback)",
              rc == 1 and "HAND-RESOLVED a.py, and its +/- lines differ" in out, out)
        rp, rv, rb = scenario(t, {"s.sh": TEN}, [dict(files={"s.sh": five}, modes={"s.sh": 0o755})],
                              [dict(files={"s.sh": resolved}, modes={"s.sh": 0o644})],
                              main={"s.sh": TEN.replace("line 4\n", "line four\n")})
        rc, out = rp.tool(rv, rb, "--onto", "")
        check("…a hand resolution that dropped the exec bit DIFFERS (the fallback reads the mode)",
              rc == 1 and "HAND-RESOLVED s.sh, and its mode or presence differs" in out, out)
        rp, rv, rb = scenario(t, {"x.bin": b"\x00base"}, [dict(files={"x.bin": b"\x00REVIEWED"})],
                              [dict(files={"x.bin": b"\x00REVIEWED"})], main={"x.bin": b"\x00MAIN"})
        rc, out = rp.tool(rv, rb, "--onto", "")
        check("…a binary both sides edited DIFFERS: its ends can't be byte-equal, so it fails closed",
              rc == 1 and "HAND-RESOLVED x.bin, and a BINARY whose ends aren't byte-equal" in out, out)

        # ── refusals, --onto, usage ─────────────────────────────────────────────────────────────────────────────────
        rp, rv, rb = scenario(t, {"a.py": TEN}, [dict(files={"a.py": five})], [dict(files={"a.py": five})])
        rp.git("checkout", "-q", "-b", "side", rv.split("..")[0])
        rp.commit({"z.py": "z\n"}, "side\n")
        rp.git("checkout", "-q", "rev")
        rp.git("merge", "-q", "--no-ff", "-m", "merge side", "side")
        rc, out = rp.tool(f"{rv.split('..')[0]}..rev", rb, "--onto", "")
        check("a range holding a MERGE commit is refused, rc 2 (positional pairing can't place one)",
              rc == 2 and "REFUSED, a range holds a merge commit" in out, out)
        rp, rv, rb = scenario(t, {"a.py": TEN}, [dict(files={"a.py": five})], [dict(files={"a.py": resolved})], main=adj)
        rc, out = rp.tool(rv, rv, "--onto", "main")
        check("--onto: the un-rebased branch CONFLICTS with main, so it isn't SAME WORK as it stands",
              rc == 1 and "CONFLICTS in ['a.py']" in out, out)
        rc, out = rp.tool(rv, rv, "--onto", "")
        check("…with --onto '' the same range against itself is SAME WORK", rc == 0 and "SAME WORK" in out, out)
        rc, out = rp.tool(rv, rb)
        check("…the rebased range onto main (its own base) merges clean",
              "merges clean (the rebased base IS it)" in out, out)
        m2 = rp.commit({"elsewhere.txt": "e\n"}, "main moves on\n")
        rc, out = rp.tool(rv, rb)
        check("…and onto a main that moved on, elsewhere, still clean (not 'IS it')",
              f"onto main@{m2[:7]}: merges clean\n" in out, out)
        rc, out = rp.tool("nope..x", rb)
        check("a ref that doesn't resolve is rc 2, named", rc == 2 and "no such commit: nope" in out, out)
        rc, out = rp.tool(rv.split("..")[0], rb)
        check("an argument that isn't a range is rc 2", rc == 2, out)
    print(f"\n{'FAIL' if fails else 'PASS'}: rebase_equiv ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
