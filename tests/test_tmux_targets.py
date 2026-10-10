#!/usr/bin/env python3
"""Static: no PANE-targeting tmux command uses a bare exact-match SESSION target ("=name" with no ":").

`tmux capture-pane -t =ax-x` errors "can't find pane" (the "=" form names a session; a pane target needs
"=ax-x:"). Behind 2>/dev/null the error is silent, so a gate built on it reads a constant: the 09-29 idle
gates passed instantly and killed busy agents (twice), and the 10-10 restart's ready check read all 16 live
residents as never-ready (seed fa8f108). Session commands (has-session, kill-session, attach, ...) take "=name"
correctly and are not checked. Literal targets only: a target built at run time is not seen.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANE_CMDS = ("capture-pane", "send-keys", "display-message", "pipe-pane", "respawn-pane", "select-pane",
             "split-window", "resize-pane", "clear-history", "copy-mode", "paste-buffer")
CMD = re.compile(r"\b(" + "|".join(PANE_CMDS) + r")\b")
# -t / -pt / -lt …: a short-flag cluster ending in t, then the target (optionally quoted, optionally an f-string)
TARGET = re.compile(r"""-[A-Za-z]*t["',\s]+f?["']?(=[^"'\s,\]\)]*)""")


def bare(line: str) -> list:
    if not CMD.search(line):
        return []
    return [t for t in TARGET.findall(line) if ":" not in t]


def main() -> int:
    fails = []
    # the detector itself: RED and GREEN controls, so a regex that stops matching can't pass silently
    ctl = [('tmux capture-pane -pt "=ax-$a" 2>/dev/null', True), ('tmux capture-pane -pt "=ax-$a:"', False),
           ('tmux send-keys -t "=$SESS" Enter', True), ('["tmux", "send-keys", "-t", f"=ax-{a}", "x"]', True),
           ('["tmux", "send-keys", "-t", f"=ax-{a}:", "x"]', False), ('tmux has-session -t "=ax-seed"', False),
           ('tmux kill-session -t "=ax-$a"', False)]
    for line, want in ctl:
        got = bool(bare(line))
        print(f"  {'ok  ' if got == want else 'FAIL'} control: {'flags' if want else 'passes'} {line}")
        if got != want:
            fails.append(line)
    files = subprocess.run(["git", "ls-files", "*.sh", "*.py", "*.bash"], cwd=REPO, capture_output=True,
                           text=True).stdout.split()
    hits = []
    for f in files:
        if f == "tests/test_tmux_targets.py" or not (REPO / f).is_file():
            continue
        for n, line in enumerate((REPO / f).read_text(errors="replace").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for t in bare(line):
                hits.append(f"{f}:{n}: {t}  ← a pane command with a SESSION target; write {t}:")
    print(f"  {'ok  ' if not hits else 'FAIL'} {len(files)} tracked scripts: no pane command targets a bare =session")
    for h in hits:
        print("       " + h)
    fails += hits
    print("ALL PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
