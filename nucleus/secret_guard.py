"""PreToolUse secret guard (plan-5497 S1b): keep declared secrets OUT of an agent's context.

a2 #27600: whatever enters context has already left the box (it goes to the model provider), and
in 8 of 8 leaking transcripts the FIRST occurrence was a read-back. So the guard denies, BEFORE the
tool runs:
  1. READ-BACK: the Read/Grep tools on a declared holder file (the manifest's files, any file
     named .env or .pgpass, the quarantine dir); a Bash CONTENT PRINTER (cat, grep, sed, head, …)
     or COPIER (cp, rsync, tar) aimed at a holder. A command substitution's output is consumed,
     not printed, so `X=$(grep … .env | cut …)` and `psql "$(grep … .env | cut …)"` pass: that is
     the idiom the hint teaches.
  2. VALUE: any tool input carrying a secret_set() value in any form (the second layer: it keeps a
     literal out of process args and logs, and teaches the idiom).

GRADE: PARTIAL, accident-grade (a3 G4). It bounds the most common SHAPES, not the flow: printenv, a
script that prints what it parsed, `docker inspect`, /proc/*/environ, a traceback all pass it on
purpose or by accident. S1c (the password leaves .env) is what carries the DB password; this
guard is load-bearing for the tokens and ASTRYX_SECRET_KEY that stay in .env (BC-b).

DOMAIN: resident sessions (ASTRYX_AGENT set) — the fleet this plan measured. POLARITY (a2): this
is an actuator on every tool call of every agent, so its unknown is ALLOW: decide() raising is the
CALLER's cue to allow and log loudly, never to block the fleet.

decide(tool, tool_input) -> None (allow) | str (the named reason to deny)
"""
import json
import os
import re
from pathlib import Path

from nucleus import secretset as ss

QUARANTINE = Path.home() / ".astryx-quarantine"

# Bash: a DENYLIST of content printers aimed at a holder. Measured 09-30 on 2543 real Bash calls
# (3 days, 16 transcripts): a syntactic "names a holder" rule denied 9%, almost all SILENT uses
# (python parsing .env for a DSN, `source .env`, `psql "$(grep … .env)"`, prose mentioning .env).
# A guard that noisy trains agents to route around it, so the Bash rule is narrow on purpose: the
# read-back shapes the leaking transcripts actually show (Read of .env; cat/grep/sed printing it).
PRINTERS = frozenset({"cat", "head", "tail", "grep", "egrep", "fgrep", "rg", "sed", "awk", "gawk",
                      "less", "more", "strings", "xxd", "od", "hexdump", "nl", "tac", "sort", "uniq",
                      "cut", "jq", "tr", "column", "bat", "diff",
                      # print nothing but MINT an undeclared copy (a2 #27600: 20 review copies)
                      "cp", "rsync", "tar", "scp", "install"})
WRAPPERS = frozenset({"sudo", "env", "timeout", "nice", "nohup", "xargs", "command", "exec"})
_SUBST = re.compile(r"\$\([^()]*\)|`[^`]*`")
def _simple_commands(cmd: str) -> list[str]:
    """Split on ; | || && & and newlines OUTSIDE quotes (a quoted regex like '(\\.env|x)' is one
    word, not two commands: the first draft split it and denied the grep that held it)."""
    out, cur, q, i = [], [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            elif ch == "\\" and q == '"' and i + 1 < len(cmd):
                cur.append(cmd[i + 1])
                i += 1
        elif ch in "'\"":
            q = ch
            cur.append(ch)
        elif ch in ";|&\n":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


# flags under which a printer prints NO content: grep -q/-c/-l/-L, sed -i (edits in place)
_QUIET = {"grep": set("qclL"), "egrep": set("qclL"), "fgrep": set("qclL"), "rg": set("qclL"),
          "sed": set("i")}
_QUIET_LONG = {"--quiet", "--silent", "--count", "--files-with-matches",
               "--files-without-match", "--in-place"}


def _prints_nothing(first: str, args: list[str]) -> bool:
    short = _QUIET.get(first)
    if not short:
        return False
    for a in args:
        if a in _QUIET_LONG or a.startswith("--in-place"):
            return True
        if a.startswith("-") and not a.startswith("--") and short & set(a[1:]):
            return True
    return False
_ENV_TOKEN = re.compile(r"(?<![\w.-])(?:[\w./~-]*/)?\.env(?![\w.-])")
_WORDS = re.compile(r"[^\s\"'<>()]+")

HINT = ('use the value without printing it: X=$(grep ^NAME= .env | cut -d= -f2-), then "$X"; '
        "for a worktree, `ln -s` the .env, never copy it. Holders are named in "
        "nucleus/secret_holders.json (plan-5497).")


def holder_files() -> list[Path]:
    """Every declared holder that is a FILE path, plus .env, the pgpass file and the quarantine."""
    m = ss.holders()
    out = [ss.ENV_FILE, ss.PGPASS_FILE]
    for h in m["holders"] + m.get("expiring", []):
        p = h["path"]
        if p.startswith("docker:") or " " in p:          # a container env or a rule, not a file
            continue
        out.extend(ss._expand(p))
    return [Path(os.path.realpath(p)) for p in out]


BY_NAME = frozenset({".env", ".pgpass"})     # secret-bearing by convention, wherever they sit


def _is_holder_path(p: str, holders: list[Path]) -> bool:
    try:
        rp = Path(os.path.realpath(os.path.expanduser(p)))
    except (OSError, ValueError):
        return False
    return (rp in holders or Path(p).name in BY_NAME or rp.name in BY_NAME
            or QUARANTINE in rp.parents or rp == QUARANTINE)


def _tokens(cmd: str) -> list[str]:
    import shlex
    try:
        return shlex.split(cmd, comments=False, posix=True)
    except ValueError:                                    # an unbalanced quote: fall back
        return cmd.split()


def _names_holder(args: list[str], holders: list[Path]) -> bool:
    """A whole TOKEN is a holder path (by name, by the manifest, or in the quarantine). A regex or
    prose that merely CONTAINS ".env" is not (the first draft denied grep -E '(\\.env|venv)')."""
    for t in args:
        t = t.lstrip("<>")                                # `cat <.env`, `2>x`
        if not t or t.startswith("-"):
            continue
        if Path(t).name in BY_NAME or ".astryx-quarantine" in t or _is_holder_path(t, holders):
            return True
    return False


# wrapper flags that take a VALUE (sudo -u USER, timeout -s SIG, nice -n N, env -u VAR)
_VALUE_FLAGS = {"-u", "-g", "-s", "-k", "-n", "-C", "-D", "--user", "--group", "--signal"}


def _command_word(words: list[str]) -> tuple[str, list[str]]:
    """(the command's own name, its args), past VAR=val prefixes and wrappers with their flags."""
    i, wrapped = 0, False
    while i < len(words):
        w = words[i]
        if ("=" in w and not w.startswith(("=", "-"))) or os.path.basename(w) in WRAPPERS:
            wrapped = wrapped or os.path.basename(w) in WRAPPERS
            i += 1
        elif wrapped and w in _VALUE_FLAGS:
            i += 2
        elif wrapped and (w.startswith("-") or re.fullmatch(r"\d+(\.\d+)?[smhd]?", w)):
            i += 1                                        # a wrapper's flag, timeout's duration
        else:
            return os.path.basename(w), words[i + 1:]
    return "", []


def _bash_reason(cmd: str, holders: list[Path]) -> str | None:
    quiet, prev = cmd, None
    while quiet != prev:                                  # innermost-first: a command
        prev, quiet = quiet, _SUBST.sub(" ", quiet)       # substitution's output is consumed
    for simple in _simple_commands(quiet):
        first, args = _command_word(_tokens(simple))
        if first in PRINTERS and not _prints_nothing(first, args) and _names_holder(args, holders):
            return f"Bash `{first}` on a declared secret holder would print or copy it. {HINT}"
    return None


def decide(tool: str, tool_input: dict, secrets=None) -> str | None:
    holders = holder_files()
    secrets = ss.secret_set() if secrets is None else secrets
    hits = ss.scan(json.dumps(tool_input, ensure_ascii=False), secrets)
    if hits:
        return (f"the tool input carries a declared secret ({', '.join(sorted(hits))}). "
                f"Reference it through a shell variable instead. {HINT}")
    if tool in ("Read", "NotebookRead", "Grep"):
        p = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
        if p and _is_holder_path(p, holders):
            return f"{tool} on a declared secret holder ({Path(p).name}). {HINT}"
        return None
    if tool == "Bash":
        return _bash_reason(tool_input.get("command") or "", holders)
    return None
