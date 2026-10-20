"""devtools/rebase_equiv.py: a rebased range is the SAME WORK a reviewer PASSed exactly when its commits, file set,
changed lines and raw messages are equal, and it merges into --onto. Hermetic: one temp git repo, no estate, no DB.
The fixtures are 10-20's three real shapes (a4 #61445/#61452): a base commit that edits a line NEXT to a reviewed hunk
(blob and patch-id both move, the work doesn't), a conflicted rebase whose cleanup dropped a '#'-led message line, and
a branch that no longer applies on main. Their RED twins: a rebase that changes a line, and one that drops a commit.
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


def main():
    with tempfile.TemporaryDirectory(prefix="rebase-equiv-") as t:
        r = Path(t)

        def git(*a, inp=None):
            return subprocess.run(["git", *a], cwd=r, env=ENV, capture_output=True, text=True, input=inp,
                                  check=True).stdout.strip()

        def tool(*a):
            p = subprocess.run([sys.executable, TOOL, *a], cwd=r, env=ENV, capture_output=True, text=True)
            return p.returncode, p.stdout + p.stderr

        def commit(msg, verbatim=True, **edits):
            for name, body in edits.items():
                (r / name.replace("_", ".")).write_text(body)
            git("add", "-A")
            git("commit", "-q", "--cleanup=" + ("verbatim" if verbatim else "strip"), "-F", "-", inp=msg)
            return git("rev-parse", "HEAD")

        lines = [f"line {i}" for i in range(1, 11)]
        a0 = "\n".join(lines) + "\n"
        git("init", "-q", "-b", "main")
        base = commit("base\n", a_py=a0, b_py="b\n")
        msg1 = "change line 5\n\nwhy it matters, wrapped so the next line starts with a msg id:\n#61157) lands after.\n"
        msg2 = "add to b\n"
        a1 = a0.replace("line 5\n", "line FIVE\n")
        # the reviewed branch, off base
        git("checkout", "-q", "-b", "rev", base)
        c1 = commit(msg1, a_py=a1)
        c2 = commit(msg2, b_py="b\nmore\n")
        # main moves: it edits line 4, NEXT to the reviewed hunk (context, never the change)
        git("checkout", "-q", "main")
        m1 = commit("main edits line 4\n", a_py=a0.replace("line 4\n", "line four\n"))
        on_m1 = a1.replace("line 4\n", "line four\n")

        def rebased(name, m1_msg=msg1, a_body=on_m1, verbatim=True, drop2=False):
            git("checkout", "-q", "-b", name, m1)
            commit(m1_msg, verbatim, a_py=a_body)
            if not drop2:
                commit(msg2, b_py="b\nmore\n")
            git("checkout", "-q", "main")
            return git("rev-parse", name)

        good = rebased("good")
        rc, out = tool(f"{base}..{c2}", f"{m1}..{good}")
        check("a context-only rebase (main edited the line NEXT to the hunk) is SAME WORK, rc 0",
              rc == 0 and "SAME WORK: 2 commit(s)" in out and "a.py: changed lines EQUAL" in out, out)
        check("…its a.py blob AND patch-id both moved, so neither can be the verdict (the discriminator is real)",
              "a.py: changed lines EQUAL · blob " in out and "blob EQUAL" not in out.split("a.py:")[1].split("\n")[0]
              and "(context moved)" in out.split("a.py:")[1].split("\n")[0], out)
        check("…and b.py, which main never touched, reads blob EQUAL",
              "b.py: changed lines EQUAL · blob EQUAL" in out, out)

        stripped = rebased("stripped", verbatim=False)          # --continue's cleanup=strip, as 10-20's 1e8dbc0
        rc, out = tool(f"{base}..{c2}", f"{m1}..{stripped}")
        check("a rebase whose message cleanup dropped the '#61157)' line DIFFERS, naming the commit and the line",
              rc == 1 and "MESSAGE of commit 1" in out and "#61157) lands after." in out
              and "changed lines DIFFER" not in out, out)

        edited = rebased("edited", a_body=on_m1.replace("line FIVE\n", "line 5ive\n"))
        rc, out = tool(f"{base}..{c2}", f"{m1}..{edited}")
        check("a rebase that CHANGED a line DIFFERS, naming the file (messages equal)",
              rc == 1 and "CHANGE in a.py" in out and "MESSAGE" not in out, out)

        dropped = rebased("dropped", drop2=True)
        rc, out = tool(f"{base}..{c2}", f"{m1}..{dropped}")
        check("a rebase that dropped a commit DIFFERS on the count AND the file set",
              rc == 1 and "COMMITS: 2 reviewed vs 1 rebased" in out and "FILES:" in out, out)

        rc, out = tool(f"{base}..{c2}", f"{base}..{c2}", "--onto", "main")
        check("--onto: the un-rebased branch CONFLICTS with main (adjacent edits), so it isn't SAME WORK as it stands",
              rc == 1 and "CONFLICTS in ['a.py']" in out, out)
        rc, out = tool(f"{base}..{c2}", f"{base}..{c2}", "--onto", "")
        check("…and with --onto '' the same range against itself is SAME WORK (the conflict was the only difference)",
              rc == 0 and "onto" not in out.lower().replace("rebase_equiv", ""), out)
        rc, out = tool(f"{base}..{c2}", f"{m1}..{good}")
        check("…the good rebase onto main (its own base) merges clean", "merges clean (the rebased base IS it)" in out, out)
        git("checkout", "-q", "main")
        m2 = commit("main moves on, elsewhere\n", c_py="c\n")
        rc, out = tool(f"{base}..{c2}", f"{m1}..{good}")
        check("…and onto a main that moved on, elsewhere, still clean (not 'IS it')",
              rc == 0 and f"onto main@{m2[:7]}: merges clean\n" in out, out)

        # a BINARY diff has no +/- lines: two different binary changes must not read as the same work (a4 10-21)
        git("checkout", "-q", "-b", "bin1", base)
        (r / "x.bin").write_bytes(b"a\0CHANGE1"); git("add", "-A"); git("commit", "-q", "-m", "bin")
        git("checkout", "-q", "-b", "bin2", base)
        (r / "x.bin").write_bytes(b"a\0OTHER2"); git("add", "-A"); git("commit", "-q", "-m", "bin")
        git("checkout", "-q", "-b", "bin3", base)
        (r / "x.bin").write_bytes(b"a\0CHANGE1"); git("add", "-A"); git("commit", "-q", "-m", "bin")
        git("checkout", "-q", "main")
        b1, b2, b3 = (git("rev-parse", n) for n in ("bin1", "bin2", "bin3"))
        rc, out = tool(f"{base}..{b1}", f"{base}..{b2}", "--onto", "")
        check("two DIFFERENT binary changes DIFFER (a binary diff has no +/- lines to compare)",
              rc == 1 and "CHANGE in x.bin: a BINARY" in out, out)
        rc, out = tool(f"{base}..{b1}", f"{base}..{b3}", "--onto", "")
        check("…and the byte-identical binary change, re-committed, is SAME WORK", rc == 0 and "SAME WORK" in out, out)

        rc, out = tool("nope..x", f"{m1}..{good}")
        check("a ref that doesn't resolve is rc 2, named", rc == 2 and "no such commit: nope" in out, out)
        rc, out = tool(f"{base}", f"{m1}..{good}")
        check("an argument that isn't a range is rc 2", rc == 2, out)
    print(f"\n{'FAIL' if fails else 'PASS'}: rebase_equiv ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
