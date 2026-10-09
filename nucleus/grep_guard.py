"""PreToolUse grep guard: a recursive sweep must not silently skip the gitignored estate.

THE DEFECT (a ratified rule since 2026-08-20, #12548/#12728, re-raised #40752 from a2 #39993). In a resident's
shell `grep` is a SHELL FUNCTION that runs ugrep with `--ignore-files`. ugrep reads every .gitignore in the
directories it descends, so a recursive search whose root CONTAINS the repo's .gitignore silently skips
memory/, triggers/, homes/, agents/, sensors/: exactly where tier-sensitive and gitignored code lives. Measured
2026-10-10 on the live tree: `grep -rlI 'kg\\.claim' .` finds 7 files, the real binary 24. The rule has been a
DISCIPLINE twice, and it still cost at least four reviews (the plan-8018 kg reader lists, the people-gate sweeps,
a3's own first sweep). A discipline is a promise; this is the mechanical leg.

WHAT IS DENIED, measured before it was written (a3, 4 days of resident transcripts: 99 sessions, 5882 Bash
calls). A blanket "no plain recursive grep" would deny 308 calls (5.2% of all Bash), and ~90% of those search a
subdirectory, which is NOT blind: starting inside memory/, nucleus/ or a home, the function and the real
binary agree exactly (measured). A noisy guard trains agents to route around it (secret_guard's lesson), so
the rule is the precise one: a PLAIN `grep` in command position, with a recursive flag, whose search root holds
a .gitignore at its top or one level down (the repo root, a worktree, a parent of either). 26 of the 308.

NOT DENIED, on purpose: `command grep`, `/usr/bin/grep`, `timeout … grep`, `xargs grep` (each execs the real
binary, not the function: measured in bash); a non-recursive grep; a recursive grep rooted in a subdirectory.
DENIED although it looks exempt: `\\grep`. A backslash suppresses ALIAS expansion, never FUNCTION lookup, so it
still runs the function (measured: `grep(){ echo FUNCTION; }; \\grep x` prints FUNCTION).

GRADE: accident-grade. It bounds the SHAPE that has actually recurred, not every blind search (a script that
calls ugrep, `rg` without -u, a find|grep pipeline). DOMAIN: Bash `grep` only. Claude Code's built-in Grep TOOL
is ripgrep, and with rg's defaults it is EQUALLY blind (a2 #41004, by proxy: `rg -l` 7 against `rg -uu` 47 at the
live root). It is NOT covered: measured 0 Grep-tool calls in the same 4-day corpus, and residents' toolsets don't
carry it. If that changes, the seam is the same (step.py's PreToolUse, which already branches on tool == "Grep"). POLARITY: its unknown is ALLOW. It is an actuator on every
Bash call of every agent, so an unparseable command, an unreadable directory or an exception all allow;
decide() raising is the caller's cue to allow and log, never to block the fleet (secret_guard's rule, a2 #27600).

decide(command, cwd) -> None (allow) | str (the named reason to deny)
"""
import os
import re
import shlex
from pathlib import Path

HINT = ("Use `command grep -r …` (the real binary) or `bash nucleus/estate_grep.sh <root> <token>`; searching a "
        "subdirectory directly is unaffected. Rule #12548/#40752.")
# a word that ends one simple command and starts the next
_SEPS = {"&&", "||", ";", "|", "&", "\n", "(", ")", "{", "}", "then", "do", "else", "elif"}
# grep options that consume the NEXT word as their argument (so it is never mistaken for the pattern or a path)
_ARG_OPTS = {"-e", "-f", "-m", "-A", "-B", "-C", "-d", "-D", "--regexp", "--file", "--max-count", "--include",
             "--exclude", "--exclude-dir", "--include-dir", "--context", "--after-context", "--before-context"}
_ENV = re.compile(r"^[A-Za-z_]\w*=")


def _words(command: str):
    lex = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=";&|()")
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


def _simple_commands(words):
    cur = []
    for w in words:
        if w in _SEPS or set(w) <= set(";&|()"):
            if cur:
                yield cur
            cur = []
        else:
            cur.append(w)
    if cur:
        yield cur


def _recursive(args) -> bool:
    for i, a in enumerate(args):
        if a in ("--recursive", "--dereference-recursive", "--directories=recurse"):
            return True
        if a == "-d" and i + 1 < len(args) and args[i + 1] == "recurse":     # a2 #41004: -d recurse IS -r
            return True
        if re.fullmatch(r"-[A-Za-z]+", a) and ("r" in a[1:] or "R" in a[1:]):
            return True
    return False


def _roots(args):
    """The search roots a grep's argv names: every operand after the pattern (no -e/-f), else '.'."""
    operands, skip, pattern_given = [], False, False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a == "--":
            operands += args[i + 1:]
            break
        if a in _ARG_OPTS:
            skip = True
            if a in ("-e", "-f", "--regexp", "--file"):
                pattern_given = True
            continue
        if a.startswith("--regexp=") or a.startswith("--file="):
            pattern_given = True
            continue
        if a.startswith("-") and a != "-":
            continue
        operands.append(a)
    paths = operands if pattern_given else operands[1:]
    return paths or ["."]


def _blind_root(p: Path) -> bool:
    """Does a search rooted at p descend through a .gitignore? At its top, or one level down."""
    try:
        if not p.is_dir():
            return False
        if (p / ".gitignore").is_file():
            return True
        with os.scandir(p) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False) and (Path(e.path) / ".gitignore").is_file():
                    return True
    except OSError:
        return False
    return False


def _expand(path: str) -> str:
    """~ and $HOME/${HOME} only: residents reach the repo as `$HOME/astryx` from homes/<agent> (a2 #41004). Any
    other variable is left unexpanded (its value is the shell's, not ours to guess), so it resolves to a path that
    doesn't exist and is ALLOWED: the declared polarity."""
    home = str(Path.home())
    return os.path.expanduser(path.replace("${HOME}", home).replace("$HOME", home))


def decide(command: str, cwd: str = None):
    try:
        words = _words(command or "")
    except ValueError:
        return None                                   # unparseable: allow (the declared polarity)
    here = Path(cwd or os.getcwd())
    for argv in _simple_commands(words):
        while argv and _ENV.match(argv[0]):
            argv = argv[1:]
        if not argv:
            continue
        if argv[0] == "cd":
            target = argv[1] if len(argv) > 1 else str(Path.home())
            here = (here / _expand(target)).resolve() if not target.startswith("-") else here
            continue
        if argv[0] != "grep" or not _recursive(argv[1:]):
            continue
        for r in _roots(argv[1:]):
            root = (here / _expand(r)).resolve()
            if _blind_root(root):
                return (f"plain `grep` is a shell function (ugrep --ignore-files): a recursive search from {root} "
                        f"silently skips every gitignored path under it (memory/, triggers/, homes/, agents/ …). "
                        f"{HINT}")
    return None
