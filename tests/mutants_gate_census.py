"""Authored mutants for devtools/gate_census.py (plan-10108 D4), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_gate_census.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools/gate_census.py"
ORACLE = REPO / "tests" / "test_gate_census.py"
ENV = "GATE_CENSUS_SRC"
TIMEOUT = 300

MUTANTS = {
    "(b) probe-then-release is never reported":
        ("        if closed and uses <= SOCK_SAFE_USES:\n", "        if False:\n"),
    "(b) a socket that is bound AND served reads as a probe":
        ("        if closed and uses <= SOCK_SAFE_USES:\n", "        if closed:\n"),
    "(b) a `with` exit is not a close":
        ("                    isinstance(it.optional_vars, ast.Name) and it.optional_vars.id == sock for it in m.items):\n"
         "                closed = True\n",
         "                    isinstance(it.optional_vars, ast.Name) and it.optional_vars.id == sock for it in m.items):\n"
         "                pass\n"),
    "(d') an env lookup's fixed FALLBACK is ignored (ASTRYX_X or /tmp/... reads clean)":
        ('            return _root(dflt, sc, depth + 1) if dflt is not None else "UNKNOWN"\n', '            return "UNKNOWN"\n'),
    "(d') XDG_* reads as an owned root (a3 BC-1 ii)":
        ('SHARED_ENV = re.compile(r"^(HOME|XDG_[A-Z_]+)$")', 'SHARED_ENV = re.compile(r"^(HOME)$")'),
    "(d') a `x or <shared>` fallback reads clean":
        ('        return "SHARED" if "SHARED" in kinds else "OWNED" if "OWNED" in kinds else "UNKNOWN"\n'
         '    if isinstance(n, ast.Name):',
         '        return "OWNED" if "OWNED" in kinds else "UNKNOWN"\n    if isinstance(n, ast.Name):'),
    "(a) port 0 counts as a literal port":
        ("                if m and m.group(1) and int(m.group(1)) != 0:\n", "                if m and m.group(1):\n"),
    "(a) docker's published port is not checked":
        ('                if t == "-p" and i + 1 < len(elts)', '                if False and t == "-p" and i + 1 < len(elts)'),
    "(a) a js port held in a const is not followed":
        ("        for name, val in consts.items():\n", "        for name, val in {}.items():\n"),
    "js comments are scanned (a commented-out spawn reads as a finding)":
        ('    stripped = JS_COMMENT.sub(lambda m: re.sub(r"[^\\n]", " ", m.group(0)), text)\n', "    stripped = text\n"),
    "sh heredoc bodies are scanned (a unit's text reads as a spawn)":
        ('    body = SH_HEREDOC.sub(lambda m: re.sub(r"[^\\n]", " ", m.group(0)), text)\n', "    body = text\n"),
    "a single-quoted sh word (a grep pattern) is read as argv":
        ('''        for m in SH_PORT.finditer(SH_SQUOTED.sub("''", ln)):\n''', "        for m in SH_PORT.finditer(ln):\n"),
    "a marker with no reason silences":
        (r'ALLOW = re.compile(r"(#|//)\s*shared-on-purpose:\s*\S")', r'ALLOW = re.compile(r"(#|//)\s*shared-on-purpose:")'),
    "a marker anywhere a few lines up silences":
        ("for n in (line, line - 1))", "for n in range(line - 5, line + 1))"),
    "a marker on the ROOT's definition doesn't cover its derived writes":
        ('        if any(_allowed(sc.lines, getattr(v, "lineno", 0)) for v in vals):\n',
         '        if False:\n'),
    "the domain loses transitive imports":
        ('        todo.extend(bc._imports(repo, f, (repo / f).read_text(errors="replace")))\n', "        pass\n"),
    "a gitignored estate file a gate names is read (merge_check links the estate in)":
        ("        if f in reach or not (repo / f).is_file() or (mine is not None and f not in mine):\n",
         "        if f in reach or not (repo / f).is_file():\n"),
    "branch_check is imported plainly (under a bare python3 without psycopg the census crashes: pre-push 10-15)":
        ("    names = (\"psycopg\", \"psycopg.conninfo\", \"psycopg.sql\", \"psycopg.errors\", \"psycopg.rows\", \"psycopg.types\")\n",
         "    names = ()\n"),
    "(r) an unpinned service start is never reported":
        ("            if _pins((repo / o).read_text(errors=\"replace\")):\n", "            if True:\n"),
    "(r) any file in the reach pins the oracle (a filename in a comment, a helper it never imports; a2 #61467 P2)":
        ("            if _pins((repo / o).read_text(errors=\"replace\")):\n",
         "            if any(_pins(t) for t in side.values()):\n"),
    "(r) a call to gate() is not a pin (every hand-run gate since seed's estate pin reads as unpinned)":
        ("            if (isinstance(f, ast.Name) and f.id in gates) or", "            if (isinstance(f, ast.Name) and f.id in ()) or"),
    "(r) estate.gate() through the module is not a pin":
        ("and isinstance(f.value, ast.Name) and f.value.id in mods):", "and isinstance(f.value, ast.Name) and f.value.id in ()):"),
    "(r) ANY function named gate pins (a local stub, not estate's)":
        ("            if (isinstance(f, ast.Name) and f.id in gates) or", "            if (isinstance(f, ast.Name) and f.id == \"gate\") or"),
    "(r) a MENTION of the key pins (an unpin, a print; a2 #61467 P1/P3)":
        ("    for n in ast.walk(tree):\n        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):\n",
         "    for n in ast.walk(tree):\n        if isinstance(n, ast.Constant) and n.value == REGISTRY:\n            return True\n"
         "        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):\n"),
    "(r) the host's live registry under /etc is a pin":
        ('    live = lambda v: isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value.startswith("/etc/")\n',
         "    live = lambda v: False\n"),
    "(r) setdefault is not a pin":
        ('f.attr == "setdefault" and n.args and key(n.args[0])', 'f.attr == "setdefault" and False'),
    "(r) a keyword write is not a pin":
        ("            if any(k.arg == REGISTRY and not live(k.value) for k in n.keywords):\n",
         "            if False:\n"),
    "(r) a dict literal's key is not a pin":
        ("            if any(key(k) and not live(v) for k, v in zip(n.keys, n.values)):\n", "            if False:\n"),
    "(r) uvicorn run in process is no service":
        ('                and f.attr in ("run", "Server"):\n', '                and f.attr in ():\n'),
    "(r) a -c body importing uvicorn is no service":
        (' or "import uvicorn" in t)', ")"),
    "(r) an ASGI target is no service (only a literal `uvicorn` argv)":
        ('(t == "uvicorn" or APP_TARGET.match(t) or', '(t == "uvicorn" or'),
    "(r) a file the oracle NAMES is outside its reach (a helper's spawn is never seen)":
        ("        for nm in bc._NAMED_RX.findall(t):\n", "        for nm in ():\n"),
    "(r) `# shared-on-purpose:` does not silence it":
        ("                    if (f, ln) not in seen and not _allowed(lines, ln):\n", "                    if (f, ln) not in seen:\n"),
}
