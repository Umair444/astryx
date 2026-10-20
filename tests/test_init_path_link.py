#!/usr/bin/env python3
"""Oracle for init.sh's PATH link (plan-10224 S3): ~/.local/bin/astryx is written only where nothing else owns it.

`ln -sf "$PWD/init.sh" ~/.local/bin/astryx` ran on every setup and replaced the pip console script (the Python CLI)
with init.sh. The block between `# >>> path link` / `# <<< path link` is extracted and run with HOME pointed at a
temp dir, against each state the name can be in. Hermetic: no database, no network, never the real ~/.local/bin.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INIT = Path(os.environ.get("INIT_PATH_LINK_SRC") or (REPO / "init.sh"))
fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    src = INIT.read_text()
    m = re.search(r"^# >>> path link.*?^# <<< path link$", src, re.S | re.M)
    arm("init.sh carries the path-link block between its markers", bool(m))
    if not m:
        print("\nFAIL: init path link")
        return 1
    arm("setup calls _link_path, and no line outside the block links ~/.local/bin/astryx",
        "\n  _link_path\n" in src and not re.search(r'ln -s\w*[^\n]*\.local/bin/astryx', src.replace(m.group(0), "")))

    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        repo, home = t / "repo", t / "home"
        repo.mkdir()
        (repo / "init.sh").write_text("#!/bin/sh\n")
        binp = home / ".local" / "bin"
        link = binp / "astryx"

        def run():
            env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
            # own-env: runs init.sh's _link_path alone (readlink/ln, no python, no orgs.py)
            return subprocess.run(["bash", "-c", "say() { echo \"$*\"; }\n" + m.group(0) + "\n_link_path\n"],
                                  cwd=repo, env=env, capture_output=True, text=True, timeout=30)

        home.mkdir()
        run()
        arm("no ~/.local/bin: nothing is created", not binp.exists())
        binp.mkdir(parents=True)
        run()
        arm("absent: linked to this repo's init.sh", link.is_symlink() and os.readlink(link) == str(repo / "init.sh"),
            os.readlink(link) if link.is_symlink() else "no link")
        st = os.lstat(link).st_mtime_ns
        run()
        arm("already ours: left untouched", os.lstat(link).st_mtime_ns == st)
        link.unlink()
        os.symlink("/old/clone/init.sh", link)
        run()
        arm("a link to ANOTHER init.sh is re-pointed here", os.readlink(link) == str(repo / "init.sh"),
            os.readlink(link))
        link.unlink()
        script = "#!/usr/bin/python3\nfrom astryx.cli import main\nmain()\n"
        link.write_text(script)
        r = run()
        arm("a regular file (the pip console script) is never replaced",
            not link.is_symlink() and link.read_text() == script and "linked" not in r.stdout, r.stdout)
        link.unlink()
        os.symlink("/opt/pipx/venvs/astryx/bin/astryx", link)
        run()
        arm("a link to something that isn't init.sh (pipx) is never replaced",
            os.readlink(link) == "/opt/pipx/venvs/astryx/bin/astryx", os.readlink(link))
    print(f"\n{'FAIL' if fails else 'ALL PASS'}: init path link ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
