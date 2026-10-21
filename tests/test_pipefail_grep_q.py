"""No `producer | grep -q` in a tracked shell file that turns on `set -o pipefail` (plan-10224 S2F, seed #61794).

grep -q exits at its first match, the producer takes SIGPIPE writing the rest, and pipefail reports the whole pipeline
FAILED though grep matched. Whether it fires depends on the producer outrunning the pipe buffer, so it hides at small
sizes and bites at large ones, and the org has hit it three times: restore_verify (08-14, a false RED), check.sh's
skip belt (fail OPEN, fixed by shape) and sqlsite.sh (10-21, the timer red). land.sh:150 and referral_guard.sh would
have failed OPEN on a big enough producer. The fix is the SHAPE: capture, then `grep -q PAT <<<"$v"` (or `[[ ]]`).

Arms: the race itself, measured (RED for the pipe form, never for the here-string); the parser on fixture lines (a pipe
into grep -q in any spelling, a pipe split across a continuation, and the lookalikes it must not flag: `||`, a here-
string, a comment, a file without pipefail); then the LIVE tree, every tracked shell file, zero findings.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


PIPEFAIL_ON = re.compile(r"\bset\s+(?:-[A-Za-z]*o|-o)\s+pipefail\b")
# a SINGLE pipe (never ||), then grep with -q in any short-option cluster or --quiet, before the command ends
PIPE_GREP_Q = re.compile(r"(?<!\|)\|(?!\|)\s*grep\b(?P<opts>(?:\s+-[-A-Za-z]+)*)")


def strip_comment(line):
    """The line without its comment: a `#` that starts a word outside quotes (so `$#`, `${#x}` and a quoted '#' stay)."""
    q = None
    for i, c in enumerate(line):
        if q:
            if c == q and (q == "'" or line[i - 1] != "\\"):
                q = None
        elif c in "'\"":
            q = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t;"):
            return line[:i]
    return line


def code_lines(text):
    """Logical lines: comments dropped, a line ending in `|` or a backslash joined to the next, numbered by its first."""
    out, buf, start = [], "", 0
    for n, raw in enumerate(text.split("\n"), 1):
        line = strip_comment(raw)
        if not buf:
            start = n
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
            continue
        if stripped.endswith("|") and not stripped.endswith("||"):
            buf += stripped + " "
            continue
        out.append((start, buf + line))
        buf = ""
    if buf:
        out.append((start, buf))
    return out


def findings(text):
    """[(line, text)] of every pipe into grep -q, or [] when the file never turns pipefail on."""
    if not any(PIPEFAIL_ON.search(ln) for _, ln in code_lines(text)):
        return []
    hits = []
    for n, ln in code_lines(text):
        for m in PIPE_GREP_Q.finditer(ln):
            opts = m.group("opts").split()
            if any(o == "--quiet" or (o.startswith("-") and not o.startswith("--") and "q" in o) for o in opts):
                hits.append((n, ln.strip()[:160]))
    return hits


def shell_files():
    out = []
    for p in subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split("\n"):
        f = REPO / p
        if not p or f.is_symlink() or not f.is_file():
            continue
        if p.endswith(".sh"):
            out.append(p)
            continue
        try:
            head = f.open("rb").readline(200)
        except OSError:
            continue
        if head.startswith(b"#!") and re.search(rb"\b(ba)?sh\b", head):
            out.append(p)
    return sorted(out)


def race(cmd, n=20):
    """How many of n runs of `cmd` under pipefail read as a FAILED match."""
    return sum(subprocess.run(["bash", "-c", "set -o pipefail; " + cmd], capture_output=True).returncode != 0
               for _ in range(n))


def main():
    big = "seq 1 200000"          # ~1.2 MB: far past the 64 KB pipe buffer, the match on its first line
    piped, here = race(f"{big} | grep -q '^1$'"), race(f"grep -q '^1$' <<<\"$({big})\"")
    check("RED: `producer | grep -q` under pipefail reads a MATCHED grep as failed (SIGPIPE), on a big producer",
          piped >= 15, f"{piped}/20 failed")
    check("…and the here-string shape never does (the fix is the shape, not the size)", here == 0, f"{here}/20 failed")

    pf = "#!/usr/bin/env bash\nset -euo pipefail\n"
    flagged = {
        "plain": "x | grep -q y", "cluster -qx": 'docker ps | grep -qx "$PG"', "cluster -Eq": "a | grep -Eq 'b|c'",
        "two flags": "a | grep -i -q b", "--quiet": "a | grep --quiet b", "in a condition": "if a | grep -q b; then :; fi",
        "split across a continuation": "a |\n  grep -q b", "after a backslash": "a \\\n  | grep -q b",
        "after a $# (not a comment)": 'echo "$#" | grep -q 1', "a quoted '#' in the producer": "echo '#x' | grep -q x",
        "set -o pipefail spelling": None,
    }
    for name, body in flagged.items():
        text = (pf + body) if body else "#!/bin/bash\nset -o pipefail\nps | grep -q x\n"
        check(f"parser flags a pipe into grep -q: {name}", len(findings(text)) == 1, str(findings(text)))
    clean = {
        "|| is not a pipe": "[ $rc -ne 0 ] || grep -qi 'refusing' <<<\"$out\"",
        "a here-string": "grep -q b <<<\"$a\"", "a comment": "# never `printf | grep -q`",
        "a TRAILING comment quoting the pipe form": "grep -q b <<<\"$a\"   # never `printf | grep -q` (land.sh:150)",
        "a quoted '#' before a real here-string": "grep -q '#x' <<<\"$a\"",
        "grep -c through a pipe": "a | grep -c b", "plain grep through a pipe": "a | grep b | sed s/x/y/",
        "grep -q on a file": "grep -q b file",
    }
    for name, body in clean.items():
        check(f"parser leaves alone: {name}", findings(pf + body) == [], str(findings(pf + body)))
    check("parser leaves alone a file that never turns pipefail on", findings("#!/bin/bash\nx | grep -q y\n") == [])
    check("…and a file that only MENTIONS pipefail in a comment", findings("#!/bin/bash\n# set -o pipefail\nx | grep -q y\n") == [])

    files = shell_files()
    live = {p: findings((REPO / p).read_text(errors="ignore")) for p in files}
    live = {p: h for p, h in live.items() if h}
    on = sum(1 for p in files if findings((REPO / p).read_text(errors="ignore")) is not None
             and any(PIPEFAIL_ON.search(ln) for _, ln in code_lines((REPO / p).read_text(errors="ignore"))))
    check(f"LIVE: no pipe into grep -q in any of the {len(files)} tracked shell files ({on} turn pipefail on)",
          files and on and not live, "; ".join(f"{p}:{n} {t}" for p, h in live.items() for n, t in h))
    print(f"\n{'FAIL' if fails else 'PASS'}: pipefail grep -q ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
