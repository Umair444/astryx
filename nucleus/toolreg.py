#!/usr/bin/env python3
"""astryx · toolreg — the tool registry: ONE authority for "which registered tool is this".

    venv/bin/python nucleus/toolreg.py find <words…>   # the registry door, from a shell
    venv/bin/python nucleus/toolreg.py list            # every entry, one line each

Goal 4227 (the tool-centered economy) measures tools, so every reader has to agree on what a
tool IS and what it is called. This module is that agreement. hooks/step.py stamps each call
with the id it resolves here, the registry door (mcp/tools) finds and runs by it, and the econ
rollup reads authorship from it. Two copies of the rule would drift, so there is one.

A tool is either
  mcp:<server>/<tool>      a tool on a server in mcp/registry.json (or the core wire, astryx)
  script:<path>            a script under TOOL_ROOTS, path relative to the repo
The org's real tools are mostly scripts run through Bash (a1 F4, plan-4227): a ledger keyed on
MCP servers alone would read the org's GDP as ~0.

PRIVACY (I5). An id is a repo-relative path under TOOL_ROOTS, or a server/tool name. Nothing
else from the call is kept. The command text, prompt text and arguments never leave this
module: resolve() reads them and returns only the id. tier/ is never a root, and a path that
normalises outside a root is not a tool.

AUTHORSHIP comes from the steps ledger, never from git (agents commit as the owner, and
triggers/ is gitignored) and never from registry.json's hand-declared field (anyone can write
it). The author is the agent whose Write was the FIRST ledger event on the source path. The
contributors are the other agents who wrote to it afterwards. If there is no record, the author
is 'unknown'. It is graded DETECTION: steps rows are forgeable by anyone at the same uid.
"""
import json
import math
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPO_S = str(REPO)

# The version of the CALL SEMANTICS every ledger row is stamped with (meta "v"). Bump it whenever
# what counts as a call changes, so a reader filters by version rather than by a remembered
# timestamp (I1). Rows WITHOUT "v" are the ledger's first live minutes, when any token naming a
# script counted as a call (inflated), and they must not be read as calls.
#   1  execution positions only; heredoc bodies are data; bash -n is not a run (a8fbd4a)
LEDGER_V = 1

# Where a reusable tool lives. tests/ are oracles, triggers/ are evaluated by the pulse rather
# than run by an agent, and tier/ is private. None of those is a tool.
TOOL_ROOTS = ("nucleus/", "skills/", "mcp/")
SCRIPT_SUFFIXES = (".py", ".sh", ".mjs", ".js")
# The core wire is not in registry.json (it's the channel server spawn.sh wires in), but its
# tools are the org's most-called ones. tools is the registry door.
CORE_SERVERS = ("astryx", "tools")
WRITE_TOOLS = ("Write",)
EDIT_TOOLS = ("Edit", "MultiEdit", "NotebookEdit")
# The door's run tool names its target in this input field (mcp/tools/server.py).
DOOR_RUN = "mcp__tools__run"


def servers() -> dict:
    try:
        return json.loads((REPO / "mcp" / "registry.json").read_text())
    except Exception:
        return {}


def script_id(path: str, must_exist: bool = True) -> str | None:
    """script:<rel> for a path under a tool root, else None. Absolute paths are made relative
    to the repo. '..' is resolved BEFORE the root test, so nucleus/../tier/x is not a tool."""
    if not path or not isinstance(path, str):
        return None
    p = path.strip().strip("'\"")
    if p.startswith(REPO_S + "/"):
        p = p[len(REPO_S) + 1:]
    elif p.startswith("/"):
        return None
    p = os.path.normpath(p)
    if p.startswith("..") or not p.startswith(TOOL_ROOTS):
        return None
    if must_exist:
        if not p.endswith(SCRIPT_SUFFIXES) or not (REPO / p).is_file():
            return None
    return "script:" + p


def _module_path(tok: str) -> str | None:
    """`python -m nucleus.econ` → nucleus/econ.py, when that file exists."""
    if re.fullmatch(r"[A-Za-z_][\w.]*", tok) and "." in tok:
        cand = tok.replace(".", "/") + ".py"
        if (REPO / cand).is_file():
            return cand
    return None


# A path is CALLED only where the shell would execute it: as the command word itself, or as
# the script an interpreter is handed. Everywhere else (git add nucleus/x.py, grep … x.py,
# sed -n … x.py) the path is only mentioned. Counting a mention as a call would inflate
# usage-GDP with every review and every commit, and it did, for the first minutes this ledger
# was live (plan-4227, 09-29).
_OPERATORS = {";", "&&", "||", "|", "&", "(", ")", "|&", ";;"}
_WRAPPERS = {"env", "nohup", "exec", "time", "command", "builtin", "sudo", "nice", "stdbuf"}
_TAKES_ARG = {"timeout": 1, "nice": 0}     # wrappers whose first plain argument is not the command
_INTERP = re.compile(r"^(python[0-9.]*|bash|sh|zsh|dash|node|deno|bun|uv|pipx)$")
_SHELLS = ("bash", "sh", "zsh", "dash")
# Shell reserved words that can precede a command in the same simple command.
_RESERVED = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}"}
_SOURCE = ("source", ".")
_BUILTINS = {"cd", "echo", "printf", "export", "set", "unset", "test", "[", "read", "exit",
             "true", "false", "for", "case", "wait", "kill", "type", "alias", "pwd", "ulimit",
             "trap", "eval", "exec", "local", "return", "shift", "declare", "mapfile", "cat"}
_HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")


def _strip_heredocs(cmd: str) -> str:
    """Drop heredoc BODIES, keeping the line that opens each one. A body is data fed to a
    command, not commands. Parsed as commands it inflated calls (a body line naming a script)
    and dropped real ones (one apostrophe in a body made the whole command unparseable).
    abstractor-4's review of 3ba7f0d, plan-4227."""
    out, pending = [], []
    for line in cmd.split("\n"):
        if pending:
            dash, word = pending[0]
            if (line.lstrip("\t") if dash else line) == word:
                pending.pop(0)
            continue
        out.append(line)
        pending = [(m.group(1) == "-", m.group(3)) for m in _HEREDOC.finditer(line)
                   if not line[max(0, m.start() - 1):m.start()] == "<"]   # <<< is a here-string
    return "\n".join(out)


def _simple_commands(cmd: str) -> list[list[str]]:
    lex = shlex.shlex(_strip_heredocs(cmd).replace("\n", " ; "), posix=True,
                      punctuation_chars=";&|()")
    lex.whitespace_split = True
    out, cur = [], []
    for t in lex:
        if t in _OPERATORS or set(t) <= set(";&|()"):
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def _invoked(words: list[str]) -> str | None:
    """The registry id this one simple command executes, if any."""
    i = 0
    while i < len(words):
        w = words[i]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w) or w in _RESERVED:   # FOO=1 cmd
            i += 1
        elif w in _WRAPPERS or w in _TAKES_ARG:
            i += 1
            while i < len(words) and words[i].startswith("-"):     # wrapper flags
                i += 1
            if w in _TAKES_ARG and _TAKES_ARG[w] and i < len(words):
                i += _TAKES_ARG[w]                                   # timeout's duration
        else:
            break
    if i >= len(words):
        return None
    head = words[i]
    if head in _SOURCE:                               # `source x.sh` / `. x.sh` executes it
        return script_id(words[i + 1]) if i + 1 < len(words) else None
    rid = script_id(head)
    if rid:
        return rid
    if not _INTERP.match(os.path.basename(head)):
        return None
    j = i + 1
    if os.path.basename(head) == "uv" and j < len(words) and words[j] == "run":
        # uv run's own flags take values (--with pkg), so scan to the first word that is a
        # script or an interpreter instead of parsing uv's flag grammar.
        j += 1
        while j < len(words):
            rid = script_id(words[j])
            if rid:
                return rid
            if _INTERP.match(os.path.basename(words[j])):
                j += 1
                break
            j += 1
    while j < len(words):
        a = words[j]
        if a == "-m" and j + 1 < len(words):
            return script_id(_module_path(words[j + 1]) or "")
        if a == "-c" or a == "-":                    # inline code / stdin: no script file
            return None
        if a == "-n" and os.path.basename(head) in _SHELLS:   # a syntax check, not a run
            return None
        if a.startswith("-"):
            j += 1
            continue
        return script_id(a)
    return None


def ids_in_command(cmd: str) -> list[str]:
    """Every registered script a shell command EXECUTES, in order, without duplicates. A
    script that is only named (an argument to git, grep, sed, cat …) is not a call."""
    if not isinstance(cmd, str) or not cmd:
        return []
    try:
        cmds = _simple_commands(cmd)
    except ValueError:                   # an unbalanced quote: the command can't be read
        return []
    out = []
    for words in cmds:
        rid = _invoked(words)
        if rid and rid not in out:
            out.append(rid)
    return out


def command_label(cmd: str) -> str:
    """What a shell command RAN, without its arguments: the first registered script it
    executes, else the program name of its first simple command. This is what the public wall
    (steps.content) shows for a Bash call that has no description. Arguments are where secrets
    live, and so is a VAR=value prefix (PGPASSWORD=… psql), so both are dropped.
    The program name is shown only when it IS a program: an executable on PATH, or a shell
    builtin. A shape test would pass a secret that happens to sit in command position (a bare
    token, a mistyped paste), so anything that isn't a known program becomes "(command)"."""
    try:
        ids = ids_in_command(cmd)
        if ids:
            return ids[0]
        for words in _simple_commands(cmd):
            i = 0
            while i < len(words) and (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[i])
                                      or words[i] in _RESERVED or words[i] in _WRAPPERS):
                i += 1
            if i < len(words):
                name = os.path.basename(words[i])
                if re.fullmatch(r"[A-Za-z0-9_.+-]{1,40}", name) and (
                        name in _BUILTINS or shutil.which(name)):
                    return name
                return "(command)"
    except Exception:
        pass
    return "(command)"


def mcp_id(tool_name: str) -> str | None:
    """mcp__<server>__<tool> → mcp:<server>/<tool>, for registered servers only."""
    if not isinstance(tool_name, str) or not tool_name.startswith("mcp__"):
        return None
    parts = tool_name.split("__", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        return None
    server, tool = parts[1], parts[2]
    if server not in servers() and server not in CORE_SERVERS:
        return None
    return f"mcp:{server}/{tool}"


def valid_id(rid) -> bool:
    """True when rid names something the registry could hold. Used on the door's input, which
    comes from a model and is therefore untrusted."""
    if not isinstance(rid, str):
        return False
    if rid.startswith("script:"):
        return script_id(rid[len("script:"):]) == rid
    m = re.fullmatch(r"mcp:([\w.-]+)/([\w.-]+)", rid)
    return bool(m) and (m.group(1) in servers() or m.group(1) in CORE_SERVERS)


def resolve(tool_name: str, tool_input) -> dict:
    """The ledger meta for one tool call, and nothing else.

    {"registry_id": id}        a CALL of a registered tool (Bash running a script, an MCP tool,
                               or the door running something on the caller's behalf)
    {"edits": id}              a Write/Edit of a tool's source. This is authorship evidence,
                               NOT a call, so it gets its own key and a call count never
                               includes it.
    {}                         anything else (Read, Grep, an unregistered server …)
    Extra ids from a pipeline that runs several scripts are kept in "also"."""
    m = _resolve(tool_name, tool_input)
    return {**m, "v": LEDGER_V} if m else {}


def _resolve(tool_name: str, tool_input) -> dict:
    ti = tool_input if isinstance(tool_input, dict) else {}
    if tool_name == DOOR_RUN:
        rid = ti.get("id")
        return {"registry_id": rid} if valid_id(rid) else {"registry_id": "mcp:tools/run"}
    if tool_name == "Bash":
        ids = ids_in_command(ti.get("command"))
        if not ids:
            return {}
        return {"registry_id": ids[0], **({"also": ids[1:]} if len(ids) > 1 else {})}
    if tool_name in WRITE_TOOLS + EDIT_TOOLS:
        rid = script_id(ti.get("file_path") or ti.get("notebook_path"), must_exist=False)
        return {"edits": rid} if rid else {}
    rid = mcp_id(tool_name)
    return {"registry_id": rid} if rid else {}


def source_path(rid: str) -> str | None:
    """The file whose authorship a registry id inherits. An MCP tool inherits its server's."""
    if rid.startswith("script:"):
        return rid[len("script:"):]
    m = re.fullmatch(r"mcp:([\w.-]+)/[\w.-]+", rid)
    if not m:
        return None
    spec = servers().get(m.group(1))
    if m.group(1) == "tools":
        return "mcp/tools/server.py"
    if m.group(1) == "astryx":
        return "channel/server.mjs"
    if not spec:
        return None
    for a in spec.get("args", []):
        if a.endswith(SCRIPT_SUFFIXES):
            return a
    return None


_LEGACY = re.compile(r"^(Write|Edit|MultiEdit|NotebookEdit): (\S+)")


def authorship(cur, ids=None) -> dict:
    """{registry_id: {"author", "contributors", "provenance"}} from the steps ledger.

    A row counts as a write to a path in either of two forms. The first is the current one,
    meta.edits. The second is the legacy step content "Write: /abs/path": before 4227, step.py
    fell back to the file_path as the step detail for Write/Edit, so history has the path in
    content. Legacy content is capped at 400 characters, so a truncated path matches nothing,
    which leaves the result 'unknown' rather than wrong.
    The FIRST event on a path decides the author. If it's a Write, that agent is the author.
    If it's an Edit, the file predates the record, so the author is 'unknown'."""
    cur.execute(
        "SELECT agent, split_part(content, ':', 1), meta->>'edits', content FROM steps "
        "WHERE kind = 'tool' AND (meta ? 'edits' "
        "  OR content ~ '^(Write|Edit|MultiEdit|NotebookEdit): ') ORDER BY id")
    events: dict = {}
    for agent, tool, edits, content in cur.fetchall():
        path = edits[len("script:"):] if edits else None
        if path is None:
            m = _LEGACY.match(content or "")
            rid = script_id(m.group(2), must_exist=False) if m else None
            if not rid:
                continue
            path = rid[len("script:"):]
        events.setdefault(path, []).append((agent, tool))

    want = ids if ids is not None else None
    if want is None:
        cur.execute("SELECT DISTINCT meta->>'registry_id' FROM steps "
                    "WHERE meta ? 'registry_id'")
        want = [r[0] for r in cur.fetchall() if r[0]]
    out = {}
    for rid in want:
        path = source_path(rid) if isinstance(rid, str) else None
        ev = events.get(path or "", [])
        if ev and ev[0][1] in WRITE_TOOLS:
            author = ev[0][0]
            contributors = sorted({a for a, _ in ev[1:] if a != author})
            out[rid] = {"author": author, "contributors": contributors,
                        "provenance": "ledger"}
        else:
            out[rid] = {"author": "unknown",
                        "contributors": sorted({a for a, _ in ev}),
                        "provenance": "unknown"}
    return out


def _describe(path: Path) -> str:
    """First line of a script's docstring or header comment. This is the door's search text."""
    try:
        head = path.read_text(errors="replace").splitlines()[:40]
    except Exception:
        return ""
    # Docstrings are Python's. In a shell script a triple quote is code or heredoc data (mcp/new.sh's
    # template, a `tr -d '"'\''` quote strip), and matching it described the tool by its body.
    if path.suffix == ".py":
        m = re.search(r'("""|\'\'\')\s*(.+?)\s*$', "\n".join(head), re.M)
        if m:
            return m.group(2).strip().rstrip('"\'')[:200]
    for line in head:
        s = line.strip()
        if s.startswith(("#!", "# -*-")) or not s:
            continue
        if s.startswith(("#", "//")):
            return s.lstrip("#/ ").strip()[:200]
        break
    return ""


def entries() -> list[dict]:
    """Every registered tool: {id, kind, description}. Scripts are DERIVED from TOOL_ROOTS, so
    no hand-kept list exists that a new tool could be missing from. MCP tools come from the
    manifest that mcp/scan.py generates."""
    out = []
    for root in TOOL_ROOTS:
        base = REPO / root
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if "__pycache__" in p.parts or "node_modules" in p.parts or not p.is_file():
                continue
            rel = str(p.relative_to(REPO))
            rid = script_id(rel)
            if rid:
                out.append({"id": rid, "kind": "script", "description": _describe(p)})
    try:
        man = json.loads((REPO / "mcp" / "manifest.json").read_text())
        for s in man.get("servers", []):
            for t in s.get("tools", []):
                out.append({"id": f"mcp:{s['server']}/{t['name']}", "kind": "mcp",
                            "description": t.get("description", "")})
    except Exception:
        pass
    return out


# Words a question is made of but no tool is ABOUT. A closed list: the ranking below discounts any
# word that's everywhere anyway, so this only has to catch the words too short to discount well.
_STOP = frozenset("a an and are be can do does for from how i in into is it its me my of on or "
                  "please that the this to up what when where which who why with you your".split())


RELATIVE_FLOOR = 0.4    # keep results scoring >= this fraction of the best one


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _match(q: str, t: str) -> bool:
    """Whole tokens only, never substrings ("is" must not hit "list"). A token of 4+ characters also
    matches by prefix either way, which covers the inflections a question uses (healthy/health,
    checks/check, rendered/render) without a stemmer's rules to get wrong."""
    if q == t:
        return True
    return len(q) >= 4 and len(t) >= 4 and (t.startswith(q) or q.startswith(t))


def find(query: str, limit: int = 10, pool: list | None = None) -> list[dict]:
    """Rank registered tools against a question, matching id and description.

    Each distinct query word counts once, weighted by how RARE it is across the registry
    (log N/df, plain IDF): "org" is in almost every description, so it barely counts, while
    "health" picks out one tool. Stopwords are dropped. It's still deliberately simple, with no
    embeddings and no model: the result stays explainable to the agent that asked, and it costs
    nothing to run. `pool` is the entry list to search (default: the live registry)."""
    pool = entries() if pool is None else pool
    words = sorted({w for w in _tokens(query) if w not in _STOP and len(w) > 1})
    if not words or not pool:
        return []
    docs = [set(_tokens(e["id"] + " " + e["description"])) for e in pool]
    n = len(docs)
    df = {w: sum(1 for d in docs if any(_match(w, t) for t in d)) for w in words}
    scored = []
    for e, d in zip(pool, docs):
        hit = [w for w in words if any(_match(w, t) for t in d)]
        if hit:
            score = sum(math.log((n + 1) / (df[w] + 0.5)) for w in hit)
            # Ties are common at this N. A query word in the tool's own ID is what the tool is
            # ABOUT; a description hit may be a passing mention ("list of model ids"). So the ID
            # breaks ties, before the alphabetical fallback (abstractor-4, review of 231b679).
            id_toks = _tokens(e["id"])
            id_hits = sum(1 for w in hit if any(_match(w, t) for t in id_toks))
            scored.append((-score, -id_hits, e["id"], e))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    # RELATIVE cutoff: a result held up by common words alone ("org") is dropped once a far stronger
    # match exists, while near-ties stay. A single-word query is unaffected (its hits all score alike).
    best = -scored[0][0] if scored else 0
    return [e for sc, _, _, e in scored if -sc >= RELATIVE_FLOOR * best][:limit]


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "find":
        for e in find(" ".join(sys.argv[2:])):
            print(f"{e['id']}  —  {e['description']}")
    elif len(sys.argv) >= 2 and sys.argv[1] == "list":
        for e in entries():
            print(f"{e['id']}  —  {e['description']}")
    else:
        print(__doc__.strip().splitlines()[2])
        print(__doc__.strip().splitlines()[3])
        sys.exit(2)
