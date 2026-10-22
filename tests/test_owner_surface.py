#!/usr/bin/env python3
"""Oracle: the owner-surface census (plan-11884 G2 + G3, a4 #62268; domain per a4 #62291 and a2 #62292).

AN OWNER SURFACE MAY ADD ROUTES AND READERS, NEVER A NEW WRITER, AND NEVER A NEW INTERPRETER OF STRANGER BYTES.

THE DOMAIN, derived once and never hand-listed: the modules whose bytes reach the owner's origin. That is every .py
under observatory/ (a1 BC-1 (a)), plus the service behind EACH proxy route. A proxy is read off main.py's ROUTES (a2
#62292 (1)): a handler whose path is a catch-all (`{path...}`). Each must resolve to ONE declared upstream: a global
assigned from `_upstream("<unit>", ...)`, or a function whose body names `orgs.port('<unit>')`. A proxy that resolves
to none is a FAILURE, never a silent drop. The unit maps to its module through init.sh's own ExecStart line.

  G2 WRITES (a1 #62307): the class is "a CALL that reaches an insert", not where SQL text sits. WRITERS are derived
     repo-wide (every tracked non-test .py: the functions whose own body holds an INSERT INTO messages string, closed
     ONE level over the functions calling them). The domain's SITES are its own SQL plus its calls that resolve
     (`from M import f [as a]`, `import M [as R]` -> R.f) to a writer in another module: EXACTLY the expected 13
     (unique (file, function); main.py's growbot_event holds two inserts and is one site), including canvas_error ->
     common.wire_insert and ear.route_room -> hearing.room.route. The domain is ONE IMPORT LEVEL; a dynamic getattr
     is outside it. A domain call through a repo-internal import that doesn't resolve is UNKNOWN, never a pass.
     RED control: a planted sibling's lowercase insert is caught.
     Instruments that fail DIFFERENTLY: (2) the tokenizer, comments and docstrings stripped, a wider pattern, must
     name exactly the AST's writer files, repo-wide (a control shows it sees a bytes-literal writer the AST misses);
     (3) every sqlguard ledger row writing messages, repo-wide, is a derived WRITER (a control shows a phantom row
     makes it disagree).
  G3 SERVING: every FileResponse / StreamingResponse / StaticFiles call site in the domain is CLASSIFIED below with
     its reason; anything else (a second hand-written file server) is a failure. The untrusted-byte routes answer
     through serve_untrusted: /api/chat/file, canvas's /api/file and /api/file/preview (a2 BC-2 (ii)).
  CLIENT (a1 BC-2): no URL observatory/web/src builds for /api/chat/file carries `key=`.
"""
import ast
import json
import os
import re
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=SyntaxWarning)   # some repo modules' own escape warnings

REPO = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("SURFACE_ROOT") or REPO)
MAIN = Path(os.environ.get("SURFACE_MAIN_SRC") or ROOT / "observatory" / "api" / "main.py")
CHAT = Path(os.environ.get("SURFACE_CHAT_SRC") or ROOT / "observatory" / "api" / "chat.py")   # mutants_owner_surface_chat
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  — {detail}"))
    if not ok:
        fails.append(name)


# ── the domain ───────────────────────────────────────────────────────────────────────────────────────────────────
def proxies(main_src: str) -> tuple[dict, list]:
    """{route path: unit stem} for every catch-all route in main.py, and the ones that resolve to no upstream."""
    t = ast.parse(main_src)
    upstream_globals = {}                                 # CANVAS_UP = _upstream("astryx-canvas", ...)
    port_funcs = {}                                       # def growbot_body(): ... orgs.port('astryx-growbot') ...
    for n in t.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "_upstream" \
                and n.value.args and isinstance(n.value.args[0], ast.Constant):
            for tg in n.targets:
                if isinstance(tg, ast.Name):
                    upstream_globals[tg.id] = n.value.args[0].value
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            m = re.search(r"orgs\.port\(\s*['\"]([\w-]+)['\"]", ast.unparse(n))
            if m:
                port_funcs[n.name] = m.group(1)
    out, orphans = {}, []
    for n in t.body:
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str) \
                    and re.search(r"\{path(?::path)?\}", d.args[0].value):
                names = {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}
                stems = {upstream_globals[x] for x in names if x in upstream_globals} | \
                        {port_funcs[x] for x in names if x in port_funcs}
                if len(stems) == 1:
                    out[d.args[0].value] = stems.pop()
                else:
                    orphans.append(f"{d.args[0].value} -> {sorted(stems) or 'no declared upstream'}")
    return out, orphans


def unit_module(stem: str) -> Path | None:
    """init.sh's ExecStart for a unit: `uvicorn pkg.mod:app` or `python -m pkg.mod` -> the module's file."""
    init = (ROOT / "init.sh").read_text()
    at = init.find(f"_uw {stem} service")
    m = re.search(r"ExecStart=\S*?(?:uvicorn\s+([\w.]+):\w+|python\s+-m\s+([\w.]+))", init[at:at + 2000]) if at >= 0 else None
    if not m:
        return None
    mod = (m.group(1) or m.group(2)).replace(".", "/") + ".py"
    for base in (ROOT, ROOT / "src"):
        if (base / mod).is_file():
            return base / mod
    return None


def domain() -> tuple[list[Path], dict, list]:
    px, orphans = proxies(MAIN.read_text())
    real_main = ROOT / "observatory" / "api" / "main.py"
    files = sorted(p for p in (ROOT / "observatory").rglob("*.py") if "node_modules" not in p.parts)
    real_chat = ROOT / "observatory" / "api" / "chat.py"
    if MAIN != real_main or CHAT != real_chat:          # the probes' channels: the judged file stands in for the real one
        files = [MAIN if p == real_main else CHAT if p == real_chat else p for p in files]
    mods = {}
    for route, stem in px.items():
        f = unit_module(stem)
        if f is None:
            orphans.append(f"{route} -> unit {stem} has no ExecStart module in init.sh")
        else:
            mods[route] = f
            if f not in files:
                files.append(f)
    return files, mods, orphans


def _rel(f: Path) -> str:
    if f == MAIN:
        return "observatory/api/main.py"
    if f == CHAT:
        return "observatory/api/chat.py"
    return str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else str(f)


# ── G2 ──────────────────────────────────────────────────────────────────────────────────────────────────────────
# a1 #62307: the class is "a CALL that reaches an insert", not where SQL text sits. WRITERS are derived once,
# repo-wide (every tracked non-test .py): the (module, function) whose own body holds an INSERT INTO messages string,
# closed ONE level over the functions that call them. A domain SITE is either the domain's own SQL, or a domain call
# that RESOLVES (`from M import f [as a]`, `import M [as R]` -> R.f, `from P import m` -> m.f) to a WRITERS member.
# The domain is one import level deep; a dynamic getattr is outside it. A domain call through a REPO-internal import
# that doesn't resolve is UNKNOWN, never a pass.
INSERT = re.compile(r"insert\s+into\s+messages\b", re.I)
WIDE = re.compile(r'into\s+(?:public\.)?"?messages"?\b', re.I)        # the second instrument's wider pattern
REPO_PKGS = ("bridges", "observatory", "astryx", "nucleus", "mcp", "hooks", "devtools", "scripts", "memory", "triggers")


def tracked() -> list[Path]:
    import subprocess
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.py"], capture_output=True, text=True)
    return [ROOT / f for f in r.stdout.split() if not f.startswith("tests/")]


def modname(rel: str) -> str:
    m = rel[:-3].replace("/", ".")
    return m[4:] if m.startswith("src.") else m


def _docs(tree) -> set:
    return {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}


def _sql_funcs(f: Path, rel: str) -> list[tuple[str, str]]:
    tree = ast.parse(f.read_text())
    docs, out = _docs(tree), []

    def walk(node, fn):
        for ch in ast.iter_child_nodes(node):
            inner = ch.name if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            if isinstance(ch, ast.Constant) and isinstance(ch.value, str) and INSERT.search(ch.value) and id(ch) not in docs:
                out.append((rel, fn))
            walk(ch, inner)
    walk(tree, "<module>")
    return out


def imports_of(tree, mod: str) -> dict:
    """name -> ('func', module, func) | ('mod', module), from this module's imports (relative ones resolved)."""
    pkg = mod.rsplit(".", 1)[0] if "." in mod else ""
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                parts = pkg.split(".") if pkg else []
                parts = parts[:len(parts) - (n.level - 1)] if n.level > 1 else parts
                base = ".".join(parts + ([n.module] if n.module else []))
            for a in n.names:
                out[a.asname or a.name] = ("from", base, a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                out[a.asname or a.name.split(".")[0]] = ("mod", a.name if a.asname else a.name.split(".")[0])
    return out


def writers_repo():
    """WRITERS: {(module, function)} repo-wide, closed one level; plus the parsed tree per module."""
    mods, trees = {}, {}
    for f in tracked():
        rel = _rel(f)
        try:
            trees[modname(rel)] = (rel, ast.parse(f.read_text()))
        except (SyntaxError, UnicodeDecodeError):
            continue
        mods[modname(rel)] = f
    base = {(modname(r), fn) for f in mods.values() for r, fn in _sql_funcs(f, _rel(f))}
    closed = set(base)
    for mod, (rel, tree) in trees.items():             # one level: a function calling a base writer (same module or imported)
        imp = imports_of(tree, mod)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for c in ast.walk(fn):
                if isinstance(c, ast.Call) and _target(c, imp, mod, mods) in base:
                    closed.add((mod, fn.name))
    return closed, mods, trees


def _target(call, imp, mod, mods):
    """The (module, function) a call resolves to, None for a non-repo or non-function call, 'UNKNOWN' for a repo-internal
    import that doesn't resolve."""
    f = call.func
    if isinstance(f, ast.Name):
        if f.id in imp and imp[f.id][0] == "from":
            _, m, name = imp[f.id]
            if f"{m}.{name}" in mods:                   # `from P import m` used as m(...): not a function call target
                return None
            if m in mods:
                return (m, name)
            return "UNKNOWN" if m.split(".")[0] in REPO_PKGS else None
        return (mod, f.id)
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in imp:
        e = imp[f.value.id]
        m = e[1] if e[0] == "mod" else f"{e[1]}.{e[2]}"
        if m in mods:
            return (m, f.attr)
        if e[0] == "from" and e[1] in mods:             # `from P import obj` then obj.method(): not a module function
            return None
        return "UNKNOWN" if m.split(".")[0] in REPO_PKGS and m not in ("astryx",) else None
    return None


def g2_sites(files, writers, mods):
    """The domain's G2 sites: its own SQL, and its calls that resolve to a writer. Plus the UNKNOWN calls."""
    own, calls, unknown = [], [], []
    for f in files:
        rel = _rel(f)
        own += _sql_funcs(f, rel)
        tree = ast.parse(f.read_text())
        mod = modname(rel)
        imp = imports_of(tree, mod)

        def walk(node, fn):
            for ch in ast.iter_child_nodes(node):
                inner = ch.name if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
                if isinstance(ch, ast.Call):
                    t = _target(ch, imp, mod, mods)
                    if t == "UNKNOWN":
                        unknown.append(f"{rel}:{ch.lineno} {ast.unparse(ch.func)}")
                    elif t and t in writers and t[0] != mod:   # a writer in ANOTHER module, reached from here
                        calls.append((rel, fn))
                walk(ch, inner)
        walk(tree, "<module>")
    return sorted(set(own) | set(calls)), sorted(set(calls) - set(own)), unknown


def writers(files) -> list[tuple[str, str]]:            # the SQL-text sites alone (the RED control's instrument)
    return sorted(x for f in files for x in _sql_funcs(f, _rel(f)))


def text_census(mods) -> set:
    """The SECOND instrument, a different method (the tokenizer, comments and docstrings stripped) on a wider pattern:
    the files whose CODE mentions inserting into messages. It must equal the files the AST says hold a writer."""
    import io
    import tokenize
    out = set()
    for f in mods.values():
        src = f.read_text()
        try:
            toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        except (tokenize.TokenError, IndentationError):
            continue
        code, prev = [], tokenize.NEWLINE
        for t in toks:
            if t.type == tokenize.COMMENT:
                continue
            if t.type == tokenize.STRING and prev in (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT):
                prev = t.type                            # a statement that is only a string: a docstring
                continue
            code.append(t.string)
            if t.type not in (tokenize.NL, tokenize.COMMENT):
                prev = t.type
        if WIDE.search(" ".join(code)) and INSERT.search(" ".join(code)):
            out.add(_rel(f))
    return out


EXPECTED_SITES = sorted([
    ("observatory/api/main.py", "people_answer"), ("observatory/api/main.py", "goal_create"),
    ("observatory/api/main.py", "owner_send"), ("observatory/api/main.py", "brain_completions"),
    ("observatory/api/main.py", "growbot_event"), ("observatory/api/main.py", "memory_chat"),
    ("observatory/api/main.py", "cog_new_org"), ("observatory/api/main.py", "memory_propose"),
    ("observatory/api/room.py", "ask"), ("bridges/canvas.py", "_say"), ("bridges/ear.py", "record"),
    ("bridges/canvas.py", "canvas_error"), ("bridges/ear.py", "route_room"),     # calls: common.wire_insert, room.route
])

# ── G3 ───────────────────────────────────────────────────────────────────────────────────────────────────────────
SERVERS = ("FileResponse", "StreamingResponse", "StaticFiles")
CLASSIFIED = {   # (relpath, function, constructor): why it may serve bytes without serve_untrusted
    ("observatory/api/main.py", "agent_avatar", "FileResponse"): "an agent's own avatar from the agents/ tree (org-authored); "
        "nosniff + a CSP sandbox, pinned by test_active_content S2",
    ("bridges/canvas.py", "avatar", "FileResponse"): "the same avatar rule on canvas, pinned by test_active_content S2",
    ("observatory/api/main.py", "index", "FileResponse"): "the app's own build output (web/dist)",
    ("observatory/front.py", "index", "FileResponse"): "the front's own build output (web/dist)",
    ("observatory/api/main.py", "<module>", "StaticFiles"): "the app's own build output (web/dist)",
    ("observatory/front.py", "<module>", "StaticFiles"): "the front's own build output (web/dist)",
    ("bridges/canvas.py", "<module>", "StaticFiles"): "canvas's own build output (canvas/web/dist)",
    ("observatory/api/room.py", "audio", "FileResponse"): "speech the org synthesised from an agent's line (TTS), a fixed "
        "audio/mpeg type; no stranger's bytes",
    ("observatory/api/main.py", "events", "StreamingResponse"): "the wire's SSE: org JSON, a fixed text/event-stream type",
    ("bridges/canvas.py", "events", "StreamingResponse"): "canvas's SSE: org JSON, a fixed text/event-stream type",
    ("observatory/front.py", "cog_stream", "StreamingResponse"): "the cog's SSE: org JSON, a fixed text/event-stream type",
    ("observatory/api/main.py", "whatsapp_pair", "StreamingResponse"): "wacli's pairing lines (a QR as text), a fixed "
        "text/plain type",
    ("observatory/api/main.py", "_pipe", "StreamingResponse"): "the /canvas and /ear proxies: their upstream modules are "
        "IN this census (the derived domain)",
    ("observatory/front.py", "_relay", "StreamingResponse"): "the cog front's relay to each org's observatory, which is "
        "main.py, in this census",
}
UNTRUSTED_ROUTES = (("observatory/api/chat.py", "file"), ("bridges/canvas.py", "message_file"),
                    ("bridges/canvas.py", "message_file_preview"))


def servers(files) -> tuple[set, dict]:
    sites, calls_su = set(), {}
    for f in files:
        rel = _rel(f)
        tree = ast.parse(f.read_text())

        def walk(node, fn):
            for ch in ast.iter_child_nodes(node):
                inner = ch.name if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
                if isinstance(ch, ast.Call):
                    nm = getattr(ch.func, "id", None) or getattr(ch.func, "attr", None)
                    if nm in SERVERS:
                        sites.add((rel, fn, nm))
                    if nm == "serve_untrusted":
                        calls_su[(rel, fn)] = calls_su.get((rel, fn), 0) + 1
                walk(ch, inner)
        walk(tree, "<module>")
    return sites, calls_su


def main():
    files, mods, orphans = domain()
    rels = {_rel(f) for f in files}
    check("DOMAIN every catch-all proxy route in main.py resolves to ONE declared upstream (none silently dropped)",
          not orphans and len(mods) >= 3, f"orphans {orphans}; resolved {sorted(mods)}")
    check("DOMAIN the proxied services are in it: canvas, ear and growbot's body (anti-vacuity)",
          {"bridges/canvas.py", "bridges/ear.py", "src/astryx/contrib/growbot_body.py"} <= rels, sorted(rels))

    W, mods, _ = writers_repo()
    got, via, unknown = g2_sites(files, W, mods)
    check(f"G2 the domain's messages-writer SITES (its own SQL + its calls that reach a writer) are EXACTLY the "
          f"expected {len(EXPECTED_SITES)} (one import level)", got == EXPECTED_SITES,
          f"new: {sorted(set(got) - set(EXPECTED_SITES))}; gone: {sorted(set(EXPECTED_SITES) - set(got))}")
    check("G2 the call-reached writers are found (canvas_error -> wire_insert, route_room -> room.route)",
          {("bridges/canvas.py", "canvas_error"), ("bridges/ear.py", "route_room")} <= set(via), via)
    check("G2 no domain call through a repo-internal import is UNKNOWN (an unresolved import is never a pass)",
          not unknown, unknown[:8])
    sql_sites = writers(files)
    with tempfile.TemporaryDirectory() as td:            # RED control: a sibling module's lowercase writer is caught
        planted = Path(td) / "sibling.py"
        planted.write_text('async def sneak(pool):\n    await pool.execute("insert  into messages (body) values ($1)", "x")\n')
        red = writers(files + [planted])
    check("G2 RED control: a planted sibling module with a lowercase insert is caught",
          len(red) == len(sql_sites) + 1 and any(fn == "sneak" for _, fn in red), red[-3:])
    ast_files = {_rel(mods[m]) for m, _ in W if m in mods and _sql_funcs(mods[m], _rel(mods[m]))}
    txt = text_census(mods)
    check("G2 second instrument (tokenizer, comments + docstrings stripped, wider pattern) names exactly the files the "
          "AST says hold a writer, repo-wide", txt == ast_files,
          f"text-only: {sorted(txt - ast_files)}; ast-only: {sorted(ast_files - txt)}")
    with tempfile.TemporaryDirectory() as td:            # the instruments FAIL DIFFERENTLY (a1 #62307, lens 3): a writer
        bw = Path(td) / "bytes_writer.py"                # whose SQL is a BYTES literal is invisible to the AST's string check,
        bw.write_text('async def w(c):\n    await c.execute(b"INSERT INTO messages (body) VALUES (1)")\n')   # not to the tokenizer
        ast_sees, tok_sees = bool(_sql_funcs(bw, "planted/bytes_writer.py")), bool(text_census({"planted": bw}))
    check("G2 control: the tokenizer instrument sees a bytes-literal writer the AST string check misses (they disagree)",
          tok_sees and not ast_sees, f"ast {ast_sees}, tokenizer {tok_sees}")
    ledger = json.loads((ROOT / "src/astryx/security/sqlguard/ledger.json").read_text())
    led = set()
    for part in ("rows", "covering"):
        for k in ledger.get(part, {}):
            f, _, rest = k.partition("::")
            fn, _, sql = rest.partition("\x1f")
            if f.endswith(".py") and INSERT.search(sql):
                led.add((modname(f), fn))
    check("G2 third instrument: every sqlguard ledger row that writes messages, repo-wide, is a derived WRITER",
          led <= W and len(led) > 0, f"ledger-only: {sorted(led - W)}")
    planted = led | {("bridges.no_such", "phantom_writer")}
    check("G2 control: a ledger row naming a writer the AST never derived makes the third instrument disagree",
          not planted <= W, sorted(planted - W))

    sites, su = servers(files)
    unclassified = sorted(s for s in sites if s not in CLASSIFIED)
    check("G3 every FileResponse / StreamingResponse / StaticFiles in the domain is classified with its reason "
          "(no second hand-written server of untrusted bytes)", not unclassified, unclassified)
    stale = sorted(k for k in CLASSIFIED if k not in sites)
    check("G3 the classification names only sites that exist (no stale exemption)", not stale, stale)
    missing = [r for r in UNTRUSTED_ROUTES if not su.get(r)]
    check("G3 the untrusted-byte routes answer through serve_untrusted: /api/chat/file, canvas /api/file and its preview",
          not missing, missing)

    web = ROOT / "observatory" / "web" / "src"
    leaks = []
    for f in list(web.rglob("*.ts")) + list(web.rglob("*.tsx")):
        for i, ln in enumerate(f.read_text().splitlines(), 1):
            if "/api/chat/file" in ln and re.search(r"[?&]key=|\bkey=", ln):
                leaks.append(f"{f.relative_to(ROOT)}:{i}")
    check("CLIENT (a1 BC-2) no URL the page builds for /api/chat/file carries key=", not leaks, leaks)
    print(f"\n{'PASS' if not fails else 'FAIL'}: owner surface ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
