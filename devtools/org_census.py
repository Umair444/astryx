#!/usr/bin/env python3
"""plan-11324 S3a's census (BC-S1(2), BC-S2(2), BC-S3(3)): every read of an ORG's state must go through the HOME
resolver, found by WALKING the code, never by a list of files.

  dsn     a read of ASTRYX_DSN (the environment's, or the .env line's) anywhere but the two resolvers
          (src/astryx/config.py, channel/home.mjs)                                                       BC-S1(2)
  estate  a path to an ORG-class .gitignore entry (data/estate_partition.json) built on a CHECKOUT base
          (REPO, ROOT, repo_root(), parents[n], $PWD in init.sh), and a literal DSN                       BC-S2(2)
  env     an environment-first read of a name an org's .env holds, anywhere but the resolvers         BC-S3(3)
  namespace  a name the HOST shares, built from an agent name (#58435 S3b). Kind `tmux`: a tmux call on the
          default socket, where `ax-<agent>` means every org's agent of that name. It must go through the org's
          server: python `[*orgs.tmux(), …]`; shell, a file that sources scripts/org_tmux.sh before the call
          (`exec tmux` / `command tmux` bypass that function, so they spell `${AX_SOCK:+-L "$AX_SOCK"}`); or an
          explicit -L/-S (a private test server). Grammar: a python LIST display whose first element is the
          literal "tmux" (an argv; a tuple of tool names is not one); a shell `tmux` in command position (quoted messages stripped); a js spawn/exec of
          'tmux'. Outside it (stated; a2 #59955 A-1 planted the last four): a tmux reached through a variable
          (`T = "tmux"; [T, …]`), a TUPLE argv (`run(("tmux", "ls"))`), an absolute path (`["/usr/bin/tmux", …]`),
          a shell wrapper (`["sh", "-c", "tmux ls"]`) and concatenation (`"tmux" + " ls"`).
          Kind `unit`: a unit name written out (`"astryx-pulse.timer"`), one org's name; a cog of several orgs's is
          `<stem>@<org>.<suffix>` (orgs.unit(); init.sh units() writes through _uw). Python: a string literal that IS
          one; shell: one in code (quoted messages stripped). Not in tests/: a test's one-org unit name is the one-org
          contract it asserts, not a consumer of a running org's unit.
  triggers   the same tmux rule over the org's OWN trigger bodies, HOME/triggers/**/*.py (gitignored, so outside
          the walk): an argv list, or a call whose first argument is a `tmux …` shell line. Read-only, file:line only.

THE GRAMMAR (stated, so a miss in review reopens it, a2 #58452): text over EXECUTABLE lines (comments and
docstrings stripped) of every .py / .sh / .mjs / .js / .cjs / .ts file git does not ignore, and every extensionless one whose
shebang is a shell, python or node (init.sh): the walk is DERIVED (EXCLUDED_ROOTS declares any root it skips). A DSN assembled from PG* parts is outside
it; construction (spawn's and the units' built environment) is the half that covers that (a1's caveat). A base
is matched where the path is JOINED onto it; a two-hop base (`B = REPO / "bridges"`, then `B / "routes-x.json"`)
is outside the grammar (stated; partition B's review fixed the two it found by hand).

A site may be DECLARED on its own line with `# org-home: <why>` (`// org-home:` in js): it is then listed, never
silent. That is for a site that names an estate path in the tree it AUDITS (a scanner over a checkout), and for a
test's fixture-bound read (a4 #58439 precision 2). Everything else is a finding.

  python devtools/org_census.py [--json] [--root R]     exit 0 no findings · 1 findings
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import io
import json
import re
import subprocess
import sys
import tokenize
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
# THE WALK IS DERIVED, never a list of roots (a2 #58917 R-1: a hand-kept DOMAIN missed skills/, harness/, nucleus/):
# every file git does not ignore whose suffix is code, or an extensionless file whose shebang names a shell or python
# (init.sh). A root the census does NOT read is DECLARED here with its reason, so a new top-level directory defaults IN.
EXCLUDED_ROOTS: dict[str, str] = {}
SHEBANG = re.compile(rb"^#!.*\b(?:ba|z|da|k)?sh\b|^#!.*\bpython[0-9.]*\b|^#!.*\bnode\b")
SUFFIX = (".py", ".sh", ".mjs", ".js", ".cjs", ".ts")   # .cjs/.ts: a2 #59037 (a node-side reader)
SKIP_PARTS = {"node_modules", "__pycache__", "dist", "upstream", ".git"}
RESOLVERS = {"src/astryx/config.py", "channel/home.mjs", "src/astryx/orgs.py", "src/astryx/paths.py",
             "devtools/org_census.py"}
DECLARE = re.compile(r"(#|//)\s*org-home:\s*\S")


def code_lines(path: Path) -> list[tuple[int, str, str]]:
    """(lineno, executable text, raw line). Python: tokenize, so comments and string-only statements (docstrings)
    drop out but string literals inside code stay. Shell/JS: the text before a comment marker at line start."""
    raw = path.read_text(errors="replace").splitlines()
    if path.suffix != ".py":
        out = []
        for i, ln in enumerate(raw, 1):
            s = ln.lstrip()
            if s.startswith("#") or s.startswith("//") or s.startswith("*"):
                continue
            out.append((i, ln, ln))
        return out
    try:
        toks = list(tokenize.generate_tokens(io.StringIO("\n".join(raw) + "\n").readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return [(i, ln, ln) for i, ln in enumerate(raw, 1) if not ln.lstrip().startswith("#")]
    code = {i: ln for i, ln in enumerate(raw, 1)}     # each line's own text, columns kept (`.parents[2] / ".env"`)
    drop: set[int] = set()
    prev = None
    for t in toks:
        if t.type == tokenize.COMMENT:
            code[t.start[0]] = code[t.start[0]][:t.start[1]]
        elif t.type == tokenize.STRING and (prev is None or prev.type in (tokenize.NEWLINE, tokenize.NL,
                                                                          tokenize.INDENT, tokenize.DEDENT)):
            drop.update(range(t.start[0], t.end[0] + 1))    # a docstring / bare string statement: not executable
        if t.type not in (tokenize.NL, tokenize.COMMENT):
            prev = t
    return [(i, code[i], raw[i - 1]) for i in sorted(code) if i not in drop and code[i].strip()]


def _not_ignored(root: Path) -> set | None:
    """The tree's files that are NOT gitignored (tracked, or new and not ignored), or None outside a git checkout (an
    archive of a commit, C2's tree: tracked files only by construction). A gitignored file is the ORG's estate (its
    triggers/, a personal bridge): its code is the org's own, moved with the estate (seed's step, not S3a), and the
    census reads only the core's. merge_check links the live estate into its tree; without this it read it."""
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                       capture_output=True)
    if r.returncode:
        return None
    return {root / x for x in r.stdout.decode(errors="replace").split("\0") if x}


def _is_code(p: Path) -> bool:
    if p.suffix in SUFFIX:
        return True
    if p.suffix:
        return False
    try:
        with p.open("rb") as fh:
            return bool(SHEBANG.match(fh.readline(200)))
    except OSError:
        return False


def walk(root: Path):
    keep = _not_ignored(root)
    files = keep if keep is not None else {p for p in root.rglob("*")}
    for p in sorted(files):
        rel = p.relative_to(root)
        if p.is_symlink() or not p.is_file() or SKIP_PARTS & set(rel.parts):
            continue
        if any(rel.as_posix().startswith(r) for r in EXCLUDED_ROOTS):
            continue
        if _is_code(p):
            yield p


# ── dsn ─────────────────────────────────────────────────────────────────────────────────────────────────────────
DSN_READ = [
    re.compile(r"""environ\s*\.\s*get\s*\(\s*["']ASTRYX_DSN["']"""),
    re.compile(r"""environ\s*\[\s*["']ASTRYX_DSN["']\s*\](?!\s*=[^=])"""),
    re.compile(r"""getenv\s*\(\s*["']ASTRYX_DSN["']"""),
    re.compile(r"""\.get\s*\(\s*["']ASTRYX_DSN["']"""),
    re.compile(r"""\[\s*["']ASTRYX_DSN["']\s*\](?!\s*=[^=])"""),
    re.compile(r"""["']\^?ASTRYX_DSN=["']"""),
    re.compile(r"""process\.env\.ASTRYX_DSN|\benv\.ASTRYX_DSN"""),
    re.compile(r"""\$\{?ASTRYX_DSN\b"""),
    re.compile(r"""\^ASTRYX_DSN="""),
]


GENERIC = (3, 4)     # `.get("ASTRYX_DSN")` / `["ASTRYX_DSN"]` on any mapping: in tests that is INSPECTION of a rendered env


def dsn_sites(rel: str, lines) -> list:
    if rel in RESOLVERS:
        return []
    test = rel.startswith("tests/")
    out = []
    for n, code, raw in lines:
        k = next((i for i, r in enumerate(DSN_READ) if r.search(code) and not (test and i in GENERIC)), None)
        if k is not None:
            out.append((n, raw, f"ASTRYX_DSN [{DSN_READ[k].pattern[:28]}]"))
    return out


# ── estate ──────────────────────────────────────────────────────────────────────────────────────────────────────
def estate_entries(root: Path) -> list[str]:
    doc = json.loads((root / "src/astryx/data/estate_partition.json").read_text())
    return sorted(e for e, c in doc["classes"].items() if c == "org")


def estate_token(entry: str) -> str:
    """One .gitignore entry as the regex of a path's FIRST component(s) after a checkout base: `**/` and the anchoring
    `/` dropped, a trailing `/` or `/*` meaning the directory, a `*` inside a name matching name characters."""
    e = entry.strip("/").removeprefix("**/").removesuffix("/*")
    return r"/".join(re.escape(x).replace(r"\*", r"[\w.*-]*") for x in e.split("/")) + r"(?![\w-])"


# A checkout base, then the path's first component: `REPO / "x"`, `join(REPO, 'x')`, f"{REPO}/x", "$ROOT/x".
BASE = (r"""(?:\b(?:REPO|ROOT|ROOT_DIR|REPO_ROOT|CHECKOUT|HERE)\b|repo_root\s*\([^)]*\)|\.parents\s*\[\s*\d+\s*\]|"""
        r"""paths\.code\s*\(\s*\)|Path\(\s*__file__\s*\)(?:\.resolve\(\))?(?:\.parent)+|\$\{?(?:ROOT|REPO|PWD)\}?|\$\(pwd\))""")
JOIN = r"""[\s)\]}]*(?:/|,)\s*f?["']?/?"""
# a shell file that cds to its checkout reads bare relative paths from there (backup.sh:15 then :280)
CD_BASE = re.compile(r"""\bcd\s+["']?(?:\$\{?(?:ROOT|REPO)\}?|\$\(dirname[^)]*\)/\.\.|\$\(cd\s)""")
# a literal DSN in a DEFAULT position (a2's restore_drill.sh:31 class): `${X:-dsn}`, `or "dsn"`, `|| 'dsn'`,
# `?? "dsn"`, `default="dsn"`, `.get(k, "dsn")`. A test's unreachable sentinel argument is neither.
LITERAL_DSN = re.compile(r"""(?::-|\bor\s+|\|\|\s*|\?\?\s*|default\s*=\s*|\.get\s*\([^,()]+,\s*)["']?"""
                         r"""postgres(?:ql)?://""")


# a bare relative path in a shell file that cds to its checkout. A FILE entry (local.md, .env) is its word; a DIRECTORY
# entry (backups/, triggers/, agents/*) is a path only when a component follows it (`backups/x`) or a file command
# takes it (`ls backups`, `[ -d memory ]`): the same word bare is a SQL table, a case label or a JSON key
PATH_CMD = r"""(?:\b(?:cd|ls|mkdir|rm|rmdir|find|tar|du|cp|mv|rsync|chmod|chown|cat|touch|ln)\s+(?:-\S+\s+)*|-[defrswx]\s+)"""


def _unlabel(code: str) -> str:
    """A quoted label or message (it has a space) is not code: it becomes "". Quotes pair left to right (every "…" is
    consumed in turn), so the close of "$X" never pairs with the open of the next string. A quoted COMMAND
    SUBSTITUTION ("$(ls backups/x)", `…`) is code, not a label: it stays."""
    return re.sub(r'"[^"]*"', lambda m: '""' if re.search(r"\s", m.group()) and not re.search(r"\$\(|`", m.group())
                  else m.group(), code)


def _bare_path(entry: str, tok: str, bare: str) -> bool:
    lead = r"""(?:^|[\s"'=(<>|;]|:-)(?:\./)?"""          # `:-`: a default (`${STAMP:-backups/.last-check}`)
    if not entry.rstrip("*").endswith("/"):
        return bool(re.search(lead + tok + r"""(?:/|\b)""", bare))
    return bool(re.search(lead + tok + r"/", bare) or re.search(PATH_CMD + r"""["']?(?:\./)?""" + tok, bare))


def estate_sites(rel: str, lines, toks, cd_base: bool) -> list:
    if rel in RESOLVERS:
        return []
    out = []
    for n, code, raw in lines:
        if LITERAL_DSN.search(code):
            out.append((n, raw, "literal DSN default"))
            continue
        hit = next((e for e, t in toks if re.search(BASE + JOIN + t, code)), None)
        bare = _unlabel(code)
        if hit is None and cd_base:
            hit = next((e for e, t in toks if _bare_path(e, t, bare)
                        and not re.search(r"""^\s*(?:echo|say|printf|warn|note)\b""", code)), None)
        if hit:
            out.append((n, raw, hit))
    return out


# ── namespace ───────────────────────────────────────────────────────────────────────────────────────────────────
SOURCES_ORG_TMUX = re.compile(r"""^\s*(?:\.|source)\s+["']?\$\{?ROOT\}?/scripts/org_tmux\.sh\b""")
SH_TMUX = re.compile(r"""(?:^|[;&|({`]|\$\(|\b(?:then|do|else|if|while|until|time)\s|!\s)\s*"""
                     r"""(?P<pre>(?:exec|command|nohup|sudo|setsid)\s+|env\s+(?:\w+=\S*\s+)*|timeout\s+\S+\s+)?"""
                     r"""tmux(?!\s*\(\))(?=\s|$|;|\)|&|\|)(?P<rest>.*)""")
SOCKET_ARG = re.compile(r"""^\s*(?:\$\{AX_SOCK:\+-L\s+"\$AX_SOCK"\}|-[LS]\b)""")
JS_TMUX = re.compile(r"""\b(?:spawn|spawnSync|execFile|execFileSync)\s*\(\s*['"`]tmux['"`]|"""
                     r"""\b(?:exec|execSync)\s*\(\s*['"`]tmux\s""")


def _py_tmux(src: Path) -> list[int]:
    """Lines where a python LIST display starts with the literal "tmux" and no -L/-S follows it (an argv; a tuple of
    tool names, `for t in ("tmux", "psql")`, is not one)."""
    try:
        toks = [t for t in tokenize.generate_tokens(io.StringIO(src.read_text(errors="replace")).readline)
                if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT)]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []
    out = []
    for i in range(1, len(toks)):
        t, prev = toks[i], toks[i - 1]
        if t.type != tokenize.STRING or prev.type != tokenize.OP or prev.string != "[":
            continue
        try:
            if ast.literal_eval(t.string) != "tmux":
                continue
        except (ValueError, SyntaxError):
            continue
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if nxt is None or nxt.type != tokenize.OP or nxt.string not in (",", "]", ")"):
            continue                                    # "tmux" + x, ("tmux" in y): not an argv's first element
        arg = toks[i + 2] if i + 2 < len(toks) and nxt.string == "," else None
        try:
            if arg is not None and arg.type == tokenize.STRING and ast.literal_eval(arg.string) in ("-L", "-S"):
                continue
        except (ValueError, SyntaxError):
            pass
        out.append(t.start[0])
    return out


_LIT_PREFIX = re.compile(r"""^[rbfuRBFU]*(?:\"\"\"|'''|"|')""")


def _py_tmux_shell(src: Path) -> list[int]:
    """Lines where a CALL's first argument is a string literal (f-strings too) that starts with `tmux ` (a shell line:
    `os.system("tmux ls")`, `run(f"tmux send-keys …", shell=True)`). An advice string inside a message is not a call's
    first argument, or doesn't start with it ("    tmux kill-session …")."""
    try:
        toks = [t for t in tokenize.generate_tokens(io.StringIO(src.read_text(errors="replace")).readline)
                if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT)]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []
    lit = (tokenize.STRING, getattr(tokenize, "FSTRING_START", -1))
    out = []
    for i in range(2, len(toks)):
        t = toks[i]
        if t.type not in lit or toks[i - 1].string != "(" or toks[i - 2].type != tokenize.NAME:
            continue
        text = t.string if t.type == tokenize.STRING else t.string + (toks[i + 1].string if i + 1 < len(toks) else "")
        if _LIT_PREFIX.sub("", text, count=1).startswith("tmux "):
            out.append(t.start[0])
    return out


# THE ORG'S TRIGGER BODIES (plan-11324 S3b, a2 #59697 via seed #59699): agents write pulse triggers into the org's
# estate (HOME/triggers/, gitignored), outside the walk above by construction. A unit-run pulse has no $TMUX, so a bare
# tmux there reads the DEFAULT socket: in a cog of several orgs it sees no residents (agent_dark alarms every tick) or
# another org's. This reads HOME/triggers/**/*.py ONLY, read-only, and reports file:line, never a line's text; a HOME
# with no triggers/ is skipped (stated, never a pass of an empty set).
def trigger_sites(home: Path) -> tuple[list, bool]:
    d = home / "triggers"
    if not d.is_dir():
        return [], False
    out = []
    for p in sorted(d.rglob("*.py")):
        if "__pycache__" in p.parts or p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(home).as_posix()
        bad = unparsed(p, ".py")
        if bad:                                         # fails closed, as the walk's own `unparsed` axis (a2 A-2)
            out.append({"kind": "triggers", "file": rel, "line": 0, "what": f"unparsed trigger body: {bad}"})
            continue
        for n in _py_tmux(p):
            out.append({"kind": "triggers", "file": rel, "line": n, "what": "tmux argv on the default socket"})
        for n in _py_tmux_shell(p):
            out.append({"kind": "triggers", "file": rel, "line": n, "what": "tmux shell line on the default socket"})
    return out, True


UNIT_NAME = re.compile(r"astryx-[a-z0-9-]+\.(?:service|timer)")


def _py_unit(src: Path) -> list[int]:
    """Lines where a string literal IS a unit name (`"astryx-pulse.timer"`): one org's name, wrong in a cog of several orgs,
    where the org's unit is `<stem>@<org>.<suffix>` (orgs.unit()). A message that mentions one (it has a space) is not."""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src.read_text(errors="replace")).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []
    out = []
    for t in toks:
        if t.type != tokenize.STRING:
            continue
        try:
            v = ast.literal_eval(t.string)
        except (ValueError, SyntaxError):
            continue
        if isinstance(v, str) and UNIT_NAME.fullmatch(v):
            out.append(t.start[0])
    return out


def namespace_sites(rel: str, src: Path, lines) -> list:
    if rel in RESOLVERS:
        return []
    out = []
    if src.suffix == ".py" or (rel.endswith(".py")):
        raw = {n: r for n, _, r in lines}
        allraw = src.read_text(errors="replace").splitlines()
        for n in _py_tmux(src):
            out.append((n, raw.get(n, allraw[n - 1] if n <= len(allraw) else ""), "tmux on the default socket"))
        for n in ([] if rel.startswith("tests/") else _py_unit(src)):   # a test's one-org name IS the one-org contract
            if n in raw:                                 # a docstring's mention is not code
                out.append((n, raw[n], "a one-org unit name (orgs.unit() gives this org's)"))
        return out
    if rel.endswith((".mjs", ".js", ".cjs", ".ts")):
        return [(n, raw, "tmux spawned on the default socket") for n, code, raw in lines if JS_TMUX.search(code)]
    sourced_at = next((n for n, c, _ in lines if SOURCES_ORG_TMUX.search(c)), None)
    for n, code, raw in lines:
        bare = _unlabel(code)
        if UNIT_NAME.search(bare) and not rel.startswith("tests/"):
            out.append((n, raw, "a one-org unit name"))
        for m in SH_TMUX.finditer(bare):
            if SOCKET_ARG.search(m.group("rest")):
                continue
            if not m.group("pre") and sourced_at is not None and sourced_at < n:
                continue
            out.append((n, raw, "tmux on the default socket" + (f" ({m.group('pre').strip()} bypasses org_tmux's "
                                                                 "function)" if m.group("pre") else "")))
            break
    return out


# ── env ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def org_names(root: Path) -> dict:
    """The names an org's .env holds, DERIVED from the code (a3 BC-S3(3)): every name a .env WRITER sets (config.
    set_env, federate's set_env dict, init.sh's `KEY=… >> .env`) and every name a .env READER reads (config.get /
    is_set, read_env()[…], `grep '^KEY=' …/.env`). A name the code treats as a .env key IS an org name."""
    names: dict[str, set] = {}

    def add(n, where):
        names.setdefault(n, set()).add(where)
    pats = [
        re.compile(r"""set_env\s*\(\s*["']([A-Z][A-Z0-9_]+)["']"""),
        re.compile(r"""config\.(?:get|is_set)\s*\(\s*["']([A-Z][A-Z0-9_]+)["']"""),
        re.compile(r"""read_env\s*\([^)]*\)\s*(?:\.get\s*\(|\[)\s*["']([A-Z][A-Z0-9_]+)["']"""),
        re.compile(r"""["']\^([A-Z][A-Z0-9_]+)=["'].*\.env"""),
        re.compile(r"""echo\s+"?([A-Z][A-Z0-9_]+)=[^>]*>>\s*"?[^ ]*\.env"""),
        re.compile(r"""^\s*print\(\s*["']([A-Z][A-Z0-9_]+)=""" ),
    ]
    # a PRIVATE .env parser (people.py's `_salt()`, a3 #58597): in a file that reads a .env path, a `"KEY="` literal
    # (startswith / split / find) is a .env key whatever the parser's shape
    private = re.compile(r"""["']\^?([A-Z][A-Z0-9_]{2,})=["']|(?<!environ)(?<!os\.environ)\.get\(\s*["']([A-Z][A-Z0-9_]{2,})["']|"""
                         r"""(?<!environ)\[\s*["']([A-Z][A-Z0-9_]{2,})["']\s*\](?!\s*=[^=])""")
    reads_env = re.compile(r"""["'/]\.env["')]|\.env\b["']?\s*\)""")
    dict_writer = re.compile(r"""set_env\s*\(\s*\w+\s*,\s*\{([^}]*)\}""")
    for p in walk(root):
        rel = p.relative_to(root).as_posix()
        if rel.startswith("tests/"):
            continue
        lines = code_lines(p)
        if any(reads_env.search(c) for _, c, _ in lines):
            for _, c, _ in lines:
                for m in private.finditer(c):
                    add(next(g for g in m.groups() if g), rel)
        for n, code, raw in lines:
            for r in pats[:5]:
                for m in r.finditer(code if r is not pats[3] else raw):
                    add(m.group(1), rel)
            m = dict_writer.search(code)
            if m:
                for k in re.findall(r"""["']([A-Z][A-Z0-9_]+)["']\s*:""", m.group(1)):
                    add(k, rel)
    # not org names, whatever a parser's shape suggests: the HOME class is set per process from the HOME (spawn,
    # orgenv), and PG* is libpq's own environment, which no org's .env defines and the built environment drops
    home = set(json.loads((root / "src/astryx/data/org_env.json").read_text())["classes"]["home"])
    return {n: w for n, w in names.items() if n not in home and not n.startswith("PG")}


def env_read(name: str) -> re.Pattern:
    q = re.escape(name)
    return re.compile(r"""environ\s*\.\s*get\s*\(\s*["']""" + q + r"""["']|environ\s*\[\s*["']""" + q +
                      r"""["']\s*\](?!\s*=[^=])|getenv\s*\(\s*["']""" + q + r"""["']|process\.env\.""" + q +
                      r"""\b|\$\{?""" + q + r"""\b(?!=)""")


# an environment read by a COMPUTED name (people.py:78, `for k in ("PEOPLE_SALT", "ASTRYX_ORG"): os.environ.get(k)`):
# the census can't tell which name, so it's a finding wherever the file holds an org name's literal
COMPUTED = re.compile(r"""environ\s*\.\s*get\s*\(\s*[A-Za-z_]\w*\s*[,)]|environ\s*\[\s*[A-Za-z_]\w*\s*\](?!\s*=[^=])|"""
                      r"""getenv\s*\(\s*[A-Za-z_]\w*\s*[,)]""")


def env_sites(rel: str, lines, readers, names) -> list:
    if rel in RESOLVERS:
        return []
    out = []
    holds = None
    for n, code, raw in lines:
        hit = next((name for name, r in readers if r.search(code)), None)
        if hit is None and not rel.startswith("tests/") and COMPUTED.search(code):
            if holds is None:
                text = "\n".join(c for _, c, _ in lines)
                holds = sorted(x for x in names if re.search(rf"""["']{x}["']""", text))
            if holds:
                hit = "computed name, file names " + ",".join(holds)
        if hit:
            out.append((n, raw, hit))
    return out


# A shell file that REFUSES in a cog of several orgs before any estate read (THE predicate, then a non-zero exit, within
# its first lines): its checkout-relative reads only ever run where the checkout IS the org's HOME. Listed as
# `guarded`, never silent, and tests/test_org_home_census.py RUNS each one under a two-org registry to prove it.
GUARD = re.compile(r"""orgs\.py\s+multi""")
GUARD_LINES = 40


def guarded(p: Path, lines) -> bool:
    return (p.suffix == ".sh" or p.name == "init.sh") and any(GUARD.search(c) for n, c, _ in lines if n <= GUARD_LINES)


def unparsed(path: Path, suffix: str) -> str | None:
    """Why a file can't be READ as code, or None. The grammar scans executable lines; a file that doesn't parse has
    none it can trust, so it is a finding of its own (fail closed), never a file with nothing to report."""
    if suffix == ".py":
        try:
            with warnings.catch_warnings():          # a subject's own invalid escape is its linter's, not the census's
                warnings.simplefilter("ignore")
                ast.parse(path.read_text(errors="replace"))
        except (SyntaxError, ValueError) as e:
            return f"not python ({type(e).__name__}: line {getattr(e, 'lineno', '?')})"
    elif suffix == ".sh":
        r = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        if r.returncode:
            return f"bash -n: {r.stderr.strip()[:80]}"
    return None


def census(root: Path, overrides: dict | None = None, home: Path | None = None) -> dict:
    """`overrides` {repo-relative path: file}: read that file's text in place of the tree's (mutation seams).
    `home`: the org HOME whose trigger bodies are read (default `root`: one org's HOME is its checkout)."""
    toks = [(e, estate_token(e)) for e in estate_entries(root)]
    names = org_names(root)
    readers = [(n, env_read(n)) for n in sorted(names)]
    res = {"dsn": [], "estate": [], "env": [], "namespace": [], "unparsed": [], "declared": [], "guarded": [],
           "guarded_files": [],
           "org_names": sorted(names)}
    for p in walk(root):
        rel = p.relative_to(root).as_posix()
        src = Path((overrides or {}).get(rel, p))
        bad = unparsed(src, p.suffix)
        if bad:
            res["unparsed"].append({"kind": "unparsed", "file": rel, "line": 0, "what": bad})
        lines = code_lines(src)
        cd_base = p.suffix == ".sh" and any(CD_BASE.search(c) for _, c, _ in lines) or rel == "init.sh"
        g = guarded(p, lines)
        if g:
            res["guarded_files"].append(rel)
        for kind, sites in (("dsn", dsn_sites(rel, lines)),
                            ("estate", estate_sites(rel, lines, toks, cd_base)),
                            ("env", env_sites(rel, lines, readers, names)),
                            ("namespace", namespace_sites(rel, src if src.suffix else p, lines))):
            for n, raw, what in sites:
                row = {"kind": kind, "file": rel, "line": n, "what": what}
                (res["declared"] if DECLARE.search(raw) else res["guarded"] if g else res[kind]).append(row)
    res["triggers"], res["triggers_read"] = trigger_sites(home or root)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(HERE))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = census(Path(a.root).resolve())
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(f"org names derived from the code's .env writers and readers: {len(res['org_names'])}")
        for k in ("dsn", "estate", "env", "namespace", "triggers", "unparsed"):
            print(f"{k}: {len(res[k])} finding(s)")
            for r in res[k]:
                print(f"  {r['file']}:{r['line']}  {r['what']}")
        print(f"guarded (the file refuses in a cog of several orgs first): {len(res['guarded'])} site(s) in "
              f"{len(res['guarded_files'])} file(s): {', '.join(res['guarded_files'])}")
        print(f"declared (org-home: …): {len(res['declared'])}")
        for r in res["declared"]:
            print(f"  {r['kind']:6} {r['file']}:{r['line']}  {r['what']}")
        if not res["triggers_read"]:
            print("triggers: NOT READ (this HOME has no triggers/)")
    return 1 if any(res[k] for k in ("dsn", "estate", "env", "namespace", "triggers", "unparsed")) else 0


if __name__ == "__main__":
    sys.exit(main())
