"""No `producer | grep -q` in a tracked shell file that turns on `set -o pipefail` (plan-10224 S2F, seed #61794).

grep -q exits at its first match, the producer takes SIGPIPE writing the rest, and pipefail reports the whole pipeline
FAILED though grep matched. Whether it fires depends on the producer outrunning the pipe buffer, so it hides at small
sizes and bites at large ones, and the org has hit it three times: restore_verify (08-14, a false RED), check.sh's
skip belt (fail OPEN, fixed by shape) and sqlsite.sh (10-21, the timer red). land.sh:150 and referral_guard.sh would
have failed OPEN on a big enough producer. The fix is the SHAPE: capture, then `grep -q PAT <<<"$v"` (or `[[ ]]`).

The CLASS is wider than grep -q (a3 #61806): any EARLY-EXIT reader whose pipeline status is a CONDITION fails the
same way. grep -m N/--max-count and -l/-L (--files-with[out]-match) stop at a match; `head` stops at N lines; `sed …q`
stops at its q. Those are flagged only in a condition (if/elif/while/until/!, or a pipeline joined by && or ||), never
inside a $( ) assignment: there the VALUE is still right, and under -e a SIGPIPE fails CLOSED. grep -q is always flagged,
since its status is all it produces.

Arms: the race itself, measured (RED for the pipe form, never for the here-string); the parser on fixture lines (every
early-exit reader in a condition, a pipe split across a continuation, and the lookalikes it must not flag: `||`, a here-
string, a comment, a $( ) assignment, a file without pipefail); then the LIVE tree, every tracked shell file, zero
findings. A tree git can't list (a no-.git extract) is 77 NOT SEARCHED, never a pass or a fail.
RESIDUAL (declared): pipefail shell embedded in another language (python's `bash -c '…set -o pipefail…'`) is outside
this file domain.
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


# the other early-exit readers: a single pipe into head or sed (its script's last command a q), or grep -m/-l/-L
PIPE_READER = re.compile(r"(?<!\|)\|(?!\|)\s*(?P<cmd>head|sed)\b")
SED_QUIT = re.compile(r"(?:^|[;{}\s/\d])[qQ]\d*\s*}*\s*$")       # the script's LAST command is q/Q (`5q`, `/x/q`, `{p;q}`)


def _words(ln, at):
    """The command's argument words from `at` to its first UNQUOTED | ; & (quotes kept out of the words)."""
    words, cur, q = [], "", None
    for c in ln[at:]:
        if q:
            if c == q:
                q = None
            else:
                cur += c
        elif c in "'\"":
            q = c
        elif c in "|;&":
            break
        elif c.isspace():
            words, cur = (words + [cur]) if cur else words, ""
        else:
            cur += c
    return words + ([cur] if cur else [])
CONDITION = re.compile(r"^\s*(?:if|elif|while|until|!)\s|&&|\|\|")


def _in_substitution(ln, at):
    """Is position `at` inside a $( ) (an assignment's value, where an early exit fails CLOSED under -e)?"""
    return ln[:at].count("$(") > ln[:at].count(")")


def _grep_reader(opts):
    """'q' (always flagged) / 'stop' (flagged in a condition) / None, from a grep's option words."""
    shorts = "".join(o[1:] for o in opts if o.startswith("-") and not o.startswith("--"))
    if "--quiet" in opts or "--silent" in opts or "q" in shorts:
        return "q"
    if any(o.startswith(("--max-count", "--files-with-matches", "--files-without-match")) for o in opts) \
            or any(c in shorts for c in "mlL"):
        return "stop"
    return None


def findings(text):
    """[(line, text)] of every early-exit reader whose pipeline status counts, or [] when pipefail is never on."""
    if not any(PIPEFAIL_ON.search(ln) for _, ln in code_lines(text)):
        return []
    hits = []
    for n, ln in code_lines(text):
        cond = bool(CONDITION.search(ln))
        for m in PIPE_GREP_Q.finditer(ln):
            kind = _grep_reader(m.group("opts").split())
            if kind == "q" or (kind == "stop" and cond and not _in_substitution(ln, m.start())):
                hits.append((n, ln.strip()[:160]))
        for m in PIPE_READER.finditer(ln):
            quits = m.group("cmd") == "head" or any(SED_QUIT.search(w) for w in _words(ln, m.end()))
            if quits and cond and not _in_substitution(ln, m.start()):
                hits.append((n, ln.strip()[:160]))
    return hits


def shell_files():
    """The tracked shell files, or None when git can't list this tree (no .git: an extract)."""
    r = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        return None
    out = []
    for p in r.stdout.split("\n"):
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
    stop_flagged = {
        "grep -m1 in an if": "if a | grep -m1 b; then :; fi", "grep --max-count && ": "a | grep --max-count=1 b && x",
        "grep -l || ": "a | grep -l b || x", "grep -L in a while": "while a | grep -L b; do :; done",
        "head in an if": "if a | head -1 >/dev/null; then :; fi", "head with !": "! a | head -n1 && x",
        "sed q in an if": "if a | sed -n '/x/{p;q}'; then :; fi", "sed 5q && ": "a | sed 5q && x",
    }
    for name, body in stop_flagged.items():
        check(f"parser flags an early-exit reader in a condition: {name}", len(findings(pf + body)) == 1,
              str(findings(pf + body)))
    clean.update({
        "head inside a $( ) assignment": "v=$(a | head -1)", "grep -m1 inside $( ) in an if": 'if [ -n "$(a | grep -m1 b)" ]; then :; fi',
        "a bare head statement (not a condition)": "a | head -5", "sed without q": "if a | sed 's/q/x/' >f; then :; fi",
        "plain grep in a condition": "if a | grep b >/dev/null; then :; fi",
    })
    for name, body in clean.items():
        check(f"parser leaves alone: {name}", findings(pf + body) == [], str(findings(pf + body)))
    check("parser leaves alone a file that never turns pipefail on", findings("#!/bin/bash\nx | grep -q y\n") == [])
    check("…and a file that only MENTIONS pipefail in a comment", findings("#!/bin/bash\n# set -o pipefail\nx | grep -q y\n") == [])

    files = shell_files()
    if files is None:
        print(f"  NOT SEARCHED  LIVE: git can't list this tree ({REPO}), so no tracked shell file is knowable here")
        print(f"\n{'FAIL' if fails else 'NOT SEARCHED (77)'}: pipefail early-exit readers ({len(fails)} failing)")
        return 1 if fails else 77
    live = {p: findings((REPO / p).read_text(errors="ignore")) for p in files}
    live = {p: h for p, h in live.items() if h}
    on = sum(1 for p in files if findings((REPO / p).read_text(errors="ignore")) is not None
             and any(PIPEFAIL_ON.search(ln) for _, ln in code_lines((REPO / p).read_text(errors="ignore"))))
    check(f"LIVE: no early-exit reader in a pipefail condition in any of the {len(files)} tracked shell files ({on} turn pipefail on)",
          files and on and not live, "; ".join(f"{p}:{n} {t}" for p, h in live.items() for n, t in h))
    print(f"\n{'FAIL' if fails else 'PASS'}: pipefail early-exit readers ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
