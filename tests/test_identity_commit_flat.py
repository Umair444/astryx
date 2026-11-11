"""The identity scribe's flat-charter migration on a GITIGNORED agents/ (medic 11-12).

A flat charter (agents/<name>.md) moves to folder form (agents/<name>/<name>.md) on its first self_edit. Where agents/
is gitignored in the shared repo (this deployment's layout), the charter is untracked, so `git mv` exited 128: every
flat charter's first self_edit crashed with a traceback and left the empty folder behind (medic's, 11-12).

Hermetic: a temp git repo whose .gitignore holds agents/, the scribe loaded from THIS tree with AGENTS pointed there.
  F1  a flat gitignored charter's first self_edit succeeds: the folder-form charter holds the new content
  F2  ...the flat file is gone (moved, not copied: one charter, no name collision on the next edit)
  F3  ...nothing was staged or committed into the shared repo (a private charter never enters the pushable genome)
  F4  ...and a SECOND self_edit then edits the folder-form charter in place
  F5  CORE is still refused on the migrated path (Heartbeat changed → REFUSED, charter unchanged)
  C1  control: a TRACKED flat charter still migrates through `git mv` (the rename is staged)
Run: venv/bin/python tests/test_identity_commit_flat.py   (also wired into devtools/check.sh)
"""
import importlib.util
import io
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True).stdout.strip()


def scribe(agents: Path):
    spec = importlib.util.spec_from_file_location("ic_under_test", REPO / "src/astryx/core/identity_commit.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.AGENTS = agents
    return m


def edit(m, agent, rel, text):
    """Run the scribe's main() as self_edit does: argv + content on stdin. (rc, stdout+stderr)."""
    argv, stdin, out, err = sys.argv, sys.stdin, sys.stdout, sys.stderr
    sys.argv = ["identity_commit.py", agent, rel]
    sys.stdin = io.TextIOWrapper(io.BytesIO(text.encode()))
    sys.stdout = sys.stderr = buf = io.StringIO()
    rc = 0
    try:
        m.main()
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    except Exception as e:                                # the 11-12 crash: CalledProcessError out of main()
        rc, _ = 99, buf.write(f"{type(e).__name__}: {e}")
    finally:
        sys.argv, sys.stdin, sys.stdout, sys.stderr = argv, stdin, out, err
    return rc, buf.getvalue()


CHARTER = "# zz\n\nModel: opus\nHeartbeat: 30 6 * * *\n\n## Method\nold step\n\n## Law\n- never\n"

with tempfile.TemporaryDirectory() as td:
    r = Path(td) / "repo"
    (r / "agents").mkdir(parents=True)
    git(Path(td), "init", "-q", "-b", "main", str(r))
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        git(r, "config", k, v)
    (r / ".gitignore").write_text("agents/*\n!agents/tracked/\n")
    (r / "agents" / "zz.md").write_text(CHARTER)
    git(r, "add", ".gitignore")
    git(r, "commit", "-qm", "base")
    m = scribe(r / "agents")

    rc, out = edit(m, "zz", "zz.md", CHARTER.replace("old step", "new step"))
    moved = r / "agents" / "zz" / "zz.md"
    want("F1 a flat GITIGNORED charter's first self_edit succeeds and the folder-form charter holds the new content",
         rc == 0 and moved.is_file() and "new step" in moved.read_text(), f"rc={rc} {out[-200:]}")
    want("F2 ...the flat file is gone (moved, not copied)", not (r / "agents" / "zz.md").exists())
    want("F3 ...nothing staged or committed into the shared repo",
         git(r, "status", "--porcelain", "--", "agents") == "" and git(r, "log", "--oneline").count("\n") == 0,
         git(r, "status", "--porcelain"))
    rc, out = edit(m, "zz", "zz.md", CHARTER.replace("old step", "third step"))
    want("F4 ...and a second self_edit edits the folder-form charter in place",
         rc == 0 and moved.is_file() and "third step" in moved.read_text() and not (r / "agents" / "zz" / "zz").exists(), out[-200:])
    before = moved.read_text() if moved.is_file() else ""
    rc, out = edit(m, "zz", "zz.md", before.replace("30 6 * * *", "* * * * *"))
    want("F5 CORE is still refused on the migrated path (Heartbeat change → REFUSED, charter unchanged)",
         rc == 1 and "REFUSED" in out and moved.is_file() and moved.read_text() == before, f"rc={rc} {out[-200:]}")

    (r / "agents" / "tracked").mkdir()
    (r / "agents" / "tracked" / "yy.md").write_text(CHARTER)
    git(r, "add", "agents/tracked/yy.md")
    git(r, "commit", "-qm", "a tracked flat charter")
    rc, out = edit(m, "yy", "yy.md", CHARTER.replace("old step", "new step"))
    want("C1 control: a TRACKED flat charter still migrates via git mv (the rename is in the index)",
         rc == 0 and (r / "agents" / "tracked" / "yy" / "yy.md").is_file()
         and "agents/tracked/yy/yy.md" in git(r, "ls-files", "agents/tracked"), f"rc={rc} {out[-200:]}")

if fails:
    print(f"FAIL: {len(fails)} arm(s)")
    sys.exit(1)
print("PASS: a flat charter's first self_edit migrates it to folder form on a gitignored agents/, CORE still guarded")
