#!/usr/bin/env python3
"""The host-global census (plan-10108 D4, a4 #50739): what check.sh's per-gate dir (D1) can't make impossible.

A gate that claims a HOST-GLOBAL resource silently assumes it is the only gate on the host, and concurrent check.sh runs
are routine. D1 gives every gate its own TMPDIR, so whatever derives from it is per gate by construction; this census
finds the rest, over the same domain as branch_check's dark lists (each gate's oracle files, the files they name, and
everything those import, transitively):

  (a)  a LITERAL port handed to a listener: a spawn argv carrying `--port N`, `--remote-debugging-port=N` (N != 0) or
       docker's `-p host:N:`; `bind((h, N))`, an HTTPServer/TCPServer((h, N)), `uvicorn.run(port=N)`, `.listen(N)` (js)
  (b)  a PROBE-THEN-RELEASE: a socket used only to bind and read getsockname()[1], then closed (explicitly, by `with`,
       or by its process exiting in a shell `$(...)`), so the number is handed back for any concurrent gate to take
  (d') a WRITE to a root that is provably SHARED: an absolute literal, Path.home()/`~`, or HOME/XDG_* (also as the
       fallback of an env lookup), by open-for-write, write_text/write_bytes, mkdir/makedirs/touch, or a
       --user-data-dir=/--cache-dir= argument. OWNED means derived from tempfile, TMPDIR or __file__ (the run's root).

It reads what EXECUTES (python by AST; js/sh with comments stripped, sh heredoc bodies dropped), and a root it can't
classify is quiet: the census under-reports by construction, it never guesses. The ONLY allowlist is an explicit
`# shared-on-purpose: <why>` (or `// shared-on-purpose:`) on the finding's line or the line above.

  venv/bin/python devtools/gate_census.py [--root <repo>]     # 0 clean · 1 findings, each named
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys
import warnings
from pathlib import Path

ALLOW = re.compile(r"(#|//)\s*shared-on-purpose:\s*\S")
SPAWNERS = {"Popen", "run", "call", "check_call", "check_output", "create_subprocess_exec", "spawn", "execFile",
            "execv", "execvp", "spawnSync", "execFileSync"}
SERVERS = {"HTTPServer", "ThreadingHTTPServer", "TCPServer", "ThreadingTCPServer", "UDPServer", "create_server"}
PORT_ARG = re.compile(r"^--(?:remote-debugging-)?port(?:=(\d+))?$")
PORT_IN_STR = re.compile(r"--(?:remote-debugging-port|port)[= ](\d+)\b")
DOCKER_P = re.compile(r"^(?:[\d.]+:)?(\d+):\d+(?:/\w+)?$")
DIR_FLAGS = ("--user-data-dir=", "--cache-dir=")
SHARED_ENV = re.compile(r"^(HOME|XDG_[A-Z_]+)$")
WRITE_METHODS = {"write_text", "write_bytes", "mkdir", "touch"}
SOCK_SAFE_USES = {"bind", "getsockname", "close", "setsockopt", "__enter__", "__exit__"}


def _finding(rel, line, cls, what):
    return {"file": rel, "line": line, "class": cls, "what": what}


def _allowed(lines: list[str], line: int) -> bool:
    return any(0 < n <= len(lines) and ALLOW.search(lines[n - 1]) for n in (line, line - 1))


# ── python ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _const_int(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, int) and not isinstance(n.value, bool):
        return n.value
    if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.isdigit():
        return int(n.value)
    return None


def _str_text(n):
    """The literal text of a str Constant or the literal parts of an f-string ({...} as a marker)."""
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    if isinstance(n, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in n.values)
    return None


def _callee(n: ast.Call) -> str:
    f = n.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


class _Scopes:
    """name -> the expressions assigned to it, per function and at module level (enough for root classification)."""

    def __init__(self, tree, lines=()):
        self.lines = list(lines)
        self.parent = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                self.parent[id(c)] = n
        self.assigns = {}
        for n in ast.walk(tree):
            if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    for nm in ([t] if isinstance(t, ast.Name) else [e for e in getattr(t, "elts", []) if isinstance(e, ast.Name)]):
                        self.assigns.setdefault((id(self.scope(n)), nm.id), []).append(n.value)
            elif isinstance(n, (ast.With, ast.AsyncWith)):
                for it in n.items:
                    if isinstance(it.optional_vars, ast.Name):
                        self.assigns.setdefault((id(self.scope(n)), it.optional_vars.id), []).append(it.context_expr)
        self.module = tree

    def scope(self, n):
        p = self.parent.get(id(n))
        while p is not None and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            p = self.parent.get(id(p))
        return p if p is not None else None

    def values(self, name: str, at) -> list:
        s = self.scope(at)
        got = self.assigns.get((id(s), name), []) if s is not None else []
        return got or self.assigns.get((id(None), name), [])


def _env_name(n):
    """'X' for os.environ['X'], os.environ.get('X'[, d]), os.getenv('X'[, d]); else None."""
    if isinstance(n, ast.Subscript) and ast.unparse(n.value) in ("os.environ", "environ"):
        k = n.slice
        return k.value if isinstance(k, ast.Constant) and isinstance(k.value, str) else None
    if isinstance(n, ast.Call) and ast.unparse(n.func) in ("os.environ.get", "environ.get", "os.getenv", "getenv") \
            and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
        return n.args[0].value
    return None


def _root(n, sc: _Scopes, depth=0) -> str:
    """OWNED | SHARED | UNKNOWN for a path expression: its LEFTMOST component decides."""
    if depth > 12 or n is None:
        return "UNKNOWN"
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        v = n.value
        return "SHARED" if v.startswith("/") or v.startswith("~") else "UNKNOWN"
    if isinstance(n, ast.JoinedStr):
        first = n.values[0] if n.values else None
        if isinstance(first, ast.Constant):
            return _root(first, sc, depth + 1)
        return _root(first.value, sc, depth + 1) if isinstance(first, ast.FormattedValue) else "UNKNOWN"
    if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.Add)):
        return _root(n.left, sc, depth + 1)
    if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or):
        # `os.environ.get("ASTRYX_X") or <fallback>`: the fallback is what runs when no gate sets it
        kinds = [_root(v, sc, depth + 1) for v in n.values]
        return "SHARED" if "SHARED" in kinds else "OWNED" if "OWNED" in kinds else "UNKNOWN"
    if isinstance(n, ast.Name):
        if n.id in ("__file__",):
            return "OWNED"
        vals = sc.values(n.id, n)
        # a root DECLARED where it is defined (`# shared-on-purpose:` on its assignment) covers every write derived from it
        if any(_allowed(sc.lines, getattr(v, "lineno", 0)) for v in vals):
            return "DECLARED"
        kinds = [_root(v, sc, depth + 1) for v in vals]
        return ("SHARED" if "SHARED" in kinds else "DECLARED" if "DECLARED" in kinds else "OWNED" if "OWNED" in kinds
                else "UNKNOWN")
    if isinstance(n, ast.Attribute):
        if n.attr in ("parent", "parents", "name", "stem"):
            return _root(n.value, sc, depth + 1)
        return "UNKNOWN"
    if isinstance(n, ast.Subscript):
        env = _env_name(n)
        if env:
            return "OWNED" if env == "TMPDIR" else "SHARED" if SHARED_ENV.match(env) else "UNKNOWN"
        return _root(n.value, sc, depth + 1)
    if isinstance(n, ast.Call):
        name, src = _callee(n), ast.unparse(n.func)
        env = _env_name(n)
        if env:
            if env == "TMPDIR":
                return "OWNED"
            if SHARED_ENV.match(env):
                return "SHARED"
            dflt = n.args[1] if len(n.args) > 1 else None
            return _root(dflt, sc, depth + 1) if dflt is not None else "UNKNOWN"
        if src.startswith("tempfile.") or name in ("mkdtemp", "mkstemp", "gettempdir", "TemporaryDirectory",
                                                    "NamedTemporaryFile", "tmpdir"):
            return "OWNED"
        if name == "home" or (name == "expanduser" and n.args and isinstance(n.args[0], ast.Constant)
                              and str(n.args[0].value).startswith("~")):
            return "SHARED"
        if name in ("repo_root",) or "__file__" in ast.unparse(n):
            return "OWNED"
        if name in ("Path", "PurePath", "join", "resolve", "expanduser", "absolute", "joinpath", "realpath", "abspath",
                    "str", "fspath", "with_suffix", "with_name") or src.endswith("path.join"):
            base = n.args[0] if n.args else (n.func.value if isinstance(n.func, ast.Attribute) else None)
            return _root(base, sc, depth + 1)
        if isinstance(n.func, ast.Attribute) and name in ("joinpath", "resolve", "expanduser", "absolute", "with_suffix"):
            return _root(n.func.value, sc, depth + 1)
        return "UNKNOWN"
    return "UNKNOWN"


def _mode_writes(n: ast.Call, pos: int) -> bool:
    m = n.args[pos] if len(n.args) > pos else next((k.value for k in n.keywords if k.arg == "mode"), None)
    return isinstance(m, ast.Constant) and isinstance(m.value, str) and any(c in m.value for c in "wax+")


def _py(rel: str, text: str) -> list:
    out, lines = [], text.splitlines()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return out
    sc = _Scopes(tree, lines)

    def add(n, cls, what):
        ln = getattr(n, "lineno", 0)
        if not _allowed(lines, ln):
            out.append(_finding(rel, ln, cls, what))

    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = _callee(n)
        # (a) a literal port in a spawn argv
        if name in SPAWNERS:
            argv = n.args[0] if n.args and isinstance(n.args[0], (ast.List, ast.Tuple)) else None
            elts = list(argv.elts) if argv is not None else list(n.args)
            for i, e in enumerate(elts):
                t = _str_text(e)
                if t is None:
                    continue
                m = PORT_ARG.match(t)
                if m and m.group(1) and int(m.group(1)) != 0:
                    add(e, "a", f"a literal port in a spawn argv: {t}")
                elif m and not m.group(1) and i + 1 < len(elts) and (_const_int(elts[i + 1]) or 0) > 0:
                    add(e, "a", f"a literal port in a spawn argv: {t} {_const_int(elts[i + 1])}")
                elif PORT_IN_STR.search(t) and int(PORT_IN_STR.search(t).group(1)) != 0:
                    add(e, "a", f"a literal port in a spawn argv: {t[:60]}")
                if t == "-p" and i + 1 < len(elts) and (_str_text(elts[i + 1]) or "") \
                        and DOCKER_P.match(_str_text(elts[i + 1]) or "") and "{}" not in (_str_text(elts[i + 1]) or ""):
                    add(e, "a", f"a literal published port: -p {_str_text(elts[i + 1])}")
                for flag in DIR_FLAGS:
                    if t.startswith(flag):
                        v = e.values[1].value if isinstance(e, ast.JoinedStr) and len(e.values) > 1 and \
                            isinstance(e.values[1], ast.FormattedValue) and t == flag + "{}" else None
                        kind = _root(v, sc) if v is not None else ("SHARED" if t[len(flag):].startswith(("/", "~")) else "UNKNOWN")
                        if kind == "SHARED":
                            add(e, "d", f"a spawn writes under a shared root: {t[:70]}")
        # (a) a fixed listener in-process
        if name == "bind" and n.args and isinstance(n.args[0], ast.Tuple) and len(n.args[0].elts) == 2:
            p = _const_int(n.args[0].elts[1])
            if p:
                add(n, "a", f"bind() on the literal port {p}")
        if name in SERVERS and n.args and isinstance(n.args[0], ast.Tuple) and len(n.args[0].elts) == 2:
            p = _const_int(n.args[0].elts[1])
            if p:
                add(n, "a", f"{name} on the literal port {p}")
        if name == "run" and ast.unparse(n.func).endswith("uvicorn.run"):
            p = next((_const_int(k.value) for k in n.keywords if k.arg == "port"), None)
            if p:
                add(n, "a", f"uvicorn.run on the literal port {p}")
        # (d') a write to a shared root
        target = None
        if name == "open" and isinstance(n.func, ast.Name) and n.args and _mode_writes(n, 1):
            target = n.args[0]
        elif name in WRITE_METHODS and isinstance(n.func, ast.Attribute):
            target = n.func.value
        elif name == "open" and isinstance(n.func, ast.Attribute) and _mode_writes(n, 0) \
                and ast.unparse(n.func.value) not in ("os", "io", "codecs"):
            target = n.func.value
        elif ast.unparse(n.func) in ("os.makedirs", "os.mkdir", "makedirs") and n.args:
            target = n.args[0]
        if target is not None and _root(target, sc) == "SHARED":
            add(n, "d", f"a write under a shared root: {ast.unparse(target)[:80]}")

    # (b) probe-then-release: getsockname()[1] of a socket used for nothing else, then closed
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Call) and _callee(n.value) == "getsockname"
                and _const_int(n.slice) == 1 and isinstance(n.value.func, ast.Attribute)
                and isinstance(n.value.func.value, ast.Name)):
            continue
        sock = n.value.func.value.id
        scope = sc.scope(n) or tree
        uses, closed = set(), False
        for m in ast.walk(scope):
            if isinstance(m, ast.Attribute) and isinstance(m.value, ast.Name) and m.value.id == sock:
                uses.add(m.attr)
            if isinstance(m, (ast.With, ast.AsyncWith)) and any(
                    isinstance(it.optional_vars, ast.Name) and it.optional_vars.id == sock for it in m.items):
                closed = True
        closed = closed or "close" in uses
        if closed and uses <= SOCK_SAFE_USES:
            add(n, "b", f"probe-then-release: {sock}.getsockname()[1] of a socket closed before anything listens on it")
    return out


# ── js / sh (comment-stripped text) ──────────────────────────────────────────────────────────────────────────────────
JS_COMMENT = re.compile(r"/\*.*?\*/|(?<![:\\'\"`])//[^\n]*", re.S)
JS_PORT = re.compile(r"""['"`]--port['"`]\s*,\s*['"`]?([1-9]\d{1,4})\b|--(?:remote-debugging-)?port=([1-9]\d{1,4})\b|\.listen\(\s*([1-9]\d{1,4})\b""")
JS_CONST_PORT = re.compile(r"\bconst\s+(\w*port\w*)\s*=\s*([1-9]\d{1,4})\b", re.I)
JS_WRITE = re.compile(r"""\b(?:writeFileSync|appendFileSync|mkdirSync|createWriteStream|writeFile|mkdir)\(\s*(?:['"`](/[^'"`]*)['"`]|(homedir\(\)|process\.env\.(?:HOME|XDG_\w+)))""")
JS_DIRFLAG = re.compile(r"""--(?:user-data-dir|cache-dir)=(?:/[^'"`\s$]+|\$\{(?:homedir\(\)|process\.env\.(?:HOME|XDG_\w+)))""")


def _keep_lines(text: str, stripped: str) -> list:
    return stripped.split("\n") if stripped.count("\n") == text.count("\n") else text.split("\n")


def _js(rel: str, text: str) -> list:
    out, lines = [], text.splitlines()
    stripped = JS_COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    consts = {m.group(1): m.group(2) for m in JS_CONST_PORT.finditer(stripped)}
    for i, ln in enumerate(stripped.split("\n"), 1):
        if _allowed(lines, i):
            continue
        for m in JS_PORT.finditer(ln):
            out.append(_finding(rel, i, "a", f"a literal port: {m.group(0)[:60]}"))
        for name, val in consts.items():
            if re.search(r"--(?:remote-debugging-)?port=\$\{" + re.escape(name) + r"\}", ln) or \
                    re.search(r"['\"`]--port['\"`]\s*,\s*(?:String\()?" + re.escape(name) + r"\b", ln):
                out.append(_finding(rel, i, "a", f"a literal port via `const {name} = {val}`"))
        for m in JS_WRITE.finditer(ln):
            out.append(_finding(rel, i, "d", f"a write under a shared root: {m.group(0)[:70]}"))
        for m in JS_DIRFLAG.finditer(ln):
            out.append(_finding(rel, i, "d", f"a spawn writes under a shared root: {m.group(0)[:70]}"))
    return out


SH_HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\s*\1\s*(?=\n|$)", re.S)
SH_PROBE = re.compile(r"\$\(.*getsockname\(\)\[1\]")          # a port read inside a command substitution, on one line
SH_SQUOTED = re.compile(r"'[^'\n]*'")
SH_PORT = re.compile(r"(?:^|\s)--(?:remote-debugging-)?port[= ]([1-9]\d{1,4})\b|-p\s+['\"]?(?:[\d.]+:)?([1-9]\d{1,4}):\d+")


def _sh(rel: str, text: str) -> list:
    out, lines = [], text.splitlines()
    body = SH_HEREDOC.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    body = "\n".join(re.sub(r"(^|\s)#.*$", r"\1", ln) for ln in body.split("\n"))
    for m in SH_PROBE.finditer(body):
        i = body.count("\n", 0, m.start()) + 1
        if not _allowed(lines, i):
            out.append(_finding(rel, i, "b", "probe-then-release: a port read from a socket in a $(...) that exits"))
    for i, ln in enumerate(body.split("\n"), 1):
        if re.search(r"^\s*(?:ExecStart|Environment)=", ln) or _allowed(lines, i):
            continue
        # a single-quoted word is DATA in shell (a grep pattern, a unit's text), never an argv a listener is spawned with
        for m in SH_PORT.finditer(SH_SQUOTED.sub("''", ln)):
            out.append(_finding(rel, i, "a", f"a literal port: {m.group(0).strip()[:60]}"))
    return out


# ── domain ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def tracked(repo: Path):
    """The repo's TRACKED files, or None when git can't say (then nothing is filtered)."""
    import subprocess
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
    return set(r.stdout.decode(errors="replace").split("\0")) - {""} if r.returncode == 0 else None


def domain(repo: Path, bc=None) -> set:
    """Every TRACKED file a gate reaches: branch_check's dark-list domain (oracles, files they name, transitive imports).
    A gitignored estate file a gate merely NAMES (merge_check links the estate in; 10-15: an owner's service a unit test
    mentions by name) is the owner's, not the branch's: no branch can fix or mark it, and the census never reads it.
    Residual, named: gitignored code a gate EXECUTES (triggers/) is outside this census."""
    if bc is None:
        sys.path.insert(0, str(repo))
        from devtools import branch_check as bc
    mine = tracked(repo)
    idx, reach, todo = bc._file_index(repo), set(), []
    for files in bc.gate_files(repo).values():
        for o in files:
            todo.append(o)
            t = (repo / o).read_text(errors="replace")
            for nm in bc._NAMED_RX.findall(t):
                todo.extend(idx.get(nm, ()))
    while todo:
        f = todo.pop()
        if f in reach or not (repo / f).is_file() or (mine is not None and f not in mine):
            continue
        reach.add(f)
        todo.extend(bc._imports(repo, f, (repo / f).read_text(errors="replace")))
    return reach


def scan(repo: Path, files) -> list:
    out = []
    for rel in sorted(files):
        try:
            text = (repo / rel).read_text(errors="replace")
        except OSError:
            continue
        if rel.endswith(".py"):
            out += _py(rel, text)
        elif rel.endswith((".mjs", ".js", ".ts", ".cjs")):
            out += _js(rel, text)
        elif rel.endswith(".sh"):
            out += _sh(rel, text)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("files", nargs="*", help="scan these (repo-relative) instead of the gate domain")
    a = ap.parse_args(argv)
    repo = Path(a.root).resolve()
    files = a.files or domain(repo)
    found = scan(repo, files)
    for f in found:
        print(f"  ✗ ({f['class']}) {f['file']}:{f['line']}: {f['what']}")
    print(f"gate census: {len(files)} file(s), {len(found)} finding(s)"
          + ("" if not found else " — each is a host-global resource a concurrent gate can collide on; fix it, or "
             "declare it with `# shared-on-purpose: <why>`"))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
