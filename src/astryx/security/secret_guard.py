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

TIMEOUT: the deny is printed before any DB work; if the 5s hook timeout kills the process first,
the decision is lost and the call is ALLOWED, the declared polarity (a2 #28956).

DOMAIN: resident sessions (ASTRYX_AGENT set) — the fleet this plan measured. POLARITY (a2): this
is an actuator on every tool call of every agent, so its unknown is ALLOW: decide() raising is the
CALLER's cue to allow and log loudly, never to block the fleet.

decide(tool, tool_input) -> None (allow) | str (the named reason to deny)
"""
import json
import os
import re
from pathlib import Path

from astryx.security import secretset as ss

QUARANTINE = Path.home() / ".astryx-quarantine"

# Bash: a DENYLIST of content printers aimed at a holder. Measured 09-30 on 2543 real Bash calls
# (3 days, 16 transcripts): a syntactic "names a holder" rule denied 9%, almost all SILENT uses
# (python parsing .env for a DSN, `source .env`, `psql "$(grep … .env)"`, prose mentioning .env).
# A guard that noisy trains agents to route around it, so the Bash rule is narrow on purpose: the
# read-back shapes the leaking transcripts actually show (Read of .env; cat/grep/sed printing it).
PRINTERS = frozenset({"cat", "head", "tail", "grep", "egrep", "fgrep", "rg", "sed", "awk", "gawk",
                      "less", "more", "strings", "xxd", "od", "hexdump", "nl", "tac", "sort", "uniq",
                      "cut", "jq", "tr", "column", "bat", "diff", "xargs", "base64", "base32", "basenc", "dd",
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
        "src/astryx/data/secret_holders.json (plan-5497).")


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
# a process environment: a unit with EnvironmentFile=.env holds every secret there (a2 #28956 B2)
_PROC_ENVIRON = re.compile(r"^/proc/[^/]+/(task/[^/]+/)?environ$")


def _expand(p: str) -> str:
    """~ and $HOME/${HOME} only, as src/astryx/security/grep_guard.py (a3 BC-3: `cat "$HOME/.config/gh/hosts.yml"`
    passed). Any other variable stays unexpanded, so it names no holder: the declared ALLOW polarity."""
    home = str(Path.home())
    return os.path.expanduser(p.replace("${HOME}", home).replace("$HOME", home))


def _at(p: str, here: Path | None) -> str:
    """p as the shell would open it: ~/$HOME expanded, a relative path taken from the tracked `cd`."""
    e = _expand(p)
    return str(here / e) if here is not None and not os.path.isabs(e) else e


def _is_holder_path(p: str, holders: list[Path], here: Path | None = None) -> bool:
    try:
        rp = Path(os.path.realpath(_at(p, here)))
    except (OSError, ValueError):
        return False
    return (rp in holders or Path(p).name in BY_NAME or rp.name in BY_NAME
            or bool(_PROC_ENVIRON.match(_expand(p))) or bool(_PROC_ENVIRON.match(str(rp)))
            or QUARANTINE in rp.parents or rp == QUARANTINE)


def _tokens(cmd: str) -> list[str]:
    import shlex
    try:                                                  # an unquoted ( or ) is its own word, as in
        lex = shlex.shlex(cmd, posix=True, punctuation_chars="()")   # grep_guard (a3 #42348)
        lex.whitespace_split, lex.commenters = True, ""
        return list(lex)
    except ValueError:                                    # an unbalanced quote: fall back
        return cmd.split()


def _names_holder(args: list[str], holders: list[Path], here: Path | None = None) -> bool:
    """A whole TOKEN is a holder path (by name, by the manifest, or in the quarantine). A regex or
    prose that merely CONTAINS ".env" is not (the first draft denied grep -E '(\\.env|venv)')."""
    for t in args:
        t = t.lstrip("<>")                                # `cat <.env`, `2>x`
        t = t[3:] if t.startswith("if=") else t           # dd's input operand (a3 #42337)
        if not t or t.startswith("-"):
            continue
        if Path(t).name in BY_NAME or ".astryx-quarantine" in t or _is_holder_path(t, holders, here):
            return True
        if any(c in t for c in "*?["):                    # `cat ~/.ssh/*`: the shell globs, so do we
            import glob
            if any(_is_holder_path(g, holders) for g in glob.glob(_at(t, here))):
                return True
    return False


# printers that descend into a DIRECTORY argument: grep -r prints every file under it (a3 BC-3)
_RECURSE_FLAGS = {"grep": set("rR"), "egrep": set("rR"), "fgrep": set("rR"), "cp": set("rRa"),
                  "scp": set("r")}
_RECURSE_ALWAYS = frozenset({"rg", "rsync", "tar"})


def _recurses(first: str, args: list[str]) -> bool:
    if first in _RECURSE_ALWAYS:
        return True
    short = _RECURSE_FLAGS.get(first)
    return bool(short) and any(a in ("--recursive", "--dereference-recursive", "--archive") or
                               (a.startswith("-") and not a.startswith("--") and short & set(a[1:]))
                               for a in args)


def _names_holder_ancestor(args: list[str], holders: list[Path], here: Path | None = None) -> bool:
    """A directory argument that CONTAINS a holder outside the repo (~/.ssh, ~/.config/gh). In-repo
    holders are left out on purpose: `grep -rn X .` from the repo root is the org's commonest search,
    and denying it would train agents around the guard (the measured-noise rule above)."""
    outside = [h for h in holders if ss.REPO not in h.parents]
    for t in args:
        if not t or t.startswith("-"):
            continue
        try:
            d = Path(os.path.realpath(_at(t, here)))
        except (OSError, ValueError):
            continue
        if d.is_dir() and any(d in h.parents for h in outside):
            return True
    return False


# Commands that print the GitHub write token with no file named (a3 BC-3 #42315, #42337). Nobody
# needs it in context: gh and git's credential helper read it themselves. One place: the next
# token-printing verb is a one-line add here. (command word, leading args, a flag that must appear
# (None = any), the short-flag letter that means the same thing)
TOKEN_PRINTERS = (
    ("gh", ["auth", "token"], None, None),
    ("gh", ["auth", "status"], "--show-token", "t"),
    ("gh", ["config", "get", "oauth_token"], None, None),
    ("gh", ["auth", "git-credential", "get"], None, None),
    ("git", ["credential", "fill"], None, None),          # answers password=<token> via gh's helper
)


def _prints_token(first: str, args: list[str]) -> bool:
    for cmd, lead, flag, short in TOKEN_PRINTERS:
        if first != cmd or args[:len(lead)] != lead:
            continue
        rest = args[len(lead):]
        if flag is None or any(a == flag or (short and a.startswith("-") and not a.startswith("--")
                                             and short in a[1:]) for a in rest):
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
        elif w.startswith("<") and "xargs" in map(os.path.basename, words[:i]):
            return "xargs", words[i:]                    # bare xargs runs echo: it PRINTS its input
        else:
            return os.path.basename(w), words[i + 1:]
    return "", []


def _bash_reason(cmd: str, holders: list[Path]) -> str | None:
    quiet, prev = cmd, None
    while quiet != prev:                                  # innermost-first: a command
        prev, quiet = quiet, _SUBST.sub(" ", quiet)       # substitution's output is consumed
    here, stack, sub = None, [], []                       # here unknown = the hook's own cwd
    for simple in _simple_commands(quiet):
        words = _tokens(simple)
        while words[:1] == ["("]:                         # `(cd ~/.ssh && cat id_ed25519)` (a3 #42348):
            sub.append(here)                              # the subshell's cd holds until its `)`
            words = words[1:]
        closes = 0
        while words[-1:] == [")"]:
            closes, words = closes + 1, words[:-1]
        if words[:1] == ["cd"] or (words[:1] == ["pushd"] and len(words) > 1):   # `cd ~/.ssh && cat
            target = words[1] if len(words) > 1 else "~"  # id_ed25519` (a3 #42337; grep_guard.py's loop)
            if not target.startswith(("-", "+")):         # cd - / pushd +N: here kept, as before
                if words[0] == "pushd":
                    stack.append(here)
                here = Path(os.path.realpath(_at(target, here)))
        elif words[:1] == ["popd"]:
            here = stack.pop() if stack else here
        else:
            first, args = _command_word(words)
            if first in PRINTERS and not _prints_nothing(first, args) and _names_holder(args, holders, here):
                return f"Bash `{first}` on a declared secret holder would print or copy it. {HINT}"
            if (first in PRINTERS and not _prints_nothing(first, args) and _recurses(first, args)
                    and _names_holder_ancestor(args, holders, here)):
                return f"Bash `{first}` would descend into a directory holding a declared secret. {HINT}"
            if _prints_token(first, args):
                return f"`{first} {' '.join(args[:3])}` prints the GitHub write token; gh and git read it themselves. {HINT}"
        for _ in range(closes):
            here = sub.pop() if sub else here
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
