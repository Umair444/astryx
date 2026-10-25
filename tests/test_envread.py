#!/usr/bin/env python3
"""Oracle: every Python .env reader reads through config.read_env, which decodes PER LINE (plan-10224 ENVREAD, seed
#61855): a line that is not UTF-8 is skipped and said on stderr as file:line (never its bytes or value), every other
key reads, and a key whose first line is the bad one reads as absent.

The package is copied into a temp tree T (T/src/astryx/…), so paths.estate() of each seated module is T and its .env
is the fixture's. Each arm runs in a child under a pinned absent registry, with no ASTRYX_*/HANDS_*/ANDROID_* inherited,
no variable the fixture .env names inherited (every key an arm reads is planted in the fixture, so a value can only come
from T/.env, a1 #62369 A1), and HOME=T/home (no reader reaches a file under the real HOME).
  E0 read_env itself: an unrelated bad line → the other keys read; the asked key's bad line → absent (its later line
     not taken); stderr names file:line, never the planted value
  E1 contrib/canopus_inbound.py   GMAIL_ADDRESS at login          E2 federation/card_assert.py   _env("ASTRYX_ORG")
  E3 hands/android.py             sdk() from ANDROID_SDK_ROOT       E4 hands/hands_desktop.py      _env_int("HANDS_STEP_CAP")
  E5 pulse/shipped_triggers/org_backup.py   _org(estate)
  E8 core/upstream_pr.py          setting("ASTRYX_UPSTREAM")        E9 hearing/ear_store.py        _env("EAR_TTL_DAYS")
  E10 hearing/voice_mint.py       cap_minutes(), env("OPENAI_API_KEY"), its estate T (every key it reads is planted)
  E11 people/people.py            _salt() (whichever of PEOPLE_SALT / ASTRYX_ORG the file names first), _org()
  E12 security/release.py         mac_key()                         E13 security/dsn_census.py     _node(), dsns()
  E14 federation/introduce.py     load_env(): the pairs, and an absent .env still raises
     each: the asked key reads past a non-UTF-8 line, and the skip is said on stderr without the value
  E6 NAMES' clash check (`orgs.py dupnames`) over a non-UTF-8 .env: never rc 2; two orgs under one name still rc 1
  E7 the CENSUS, DERIVED: every tracked non-test .py (git ls-files; a walk when the tree has no .git, as the mutation
     probe's copy) is parsed, and every .env path literal (".env", "…/.env", f"{x}/.env") and every config.env_path()
     call is followed to its use: through `/`, Path()/str(), names (per scope, until rebound), a helper's parameter in
     this file or in a censused module it imports, a return to its callers, a collection, an argparse default. A use is
     CONFIG (config's API), PROBE (read_bytes() discarded: absent raises, nothing decoded), BENIGN (is_file/exists/stat/
     chmod, a pattern, a comparison, a message), READ (open/read_text/read_bytes: a hand-rolled reader), WRITE, or
     UNCLASSIFIED. READ, WRITE and UNCLASSIFIED are RED (fail closed) unless DECLARED in EXEMPT with a reason. A second,
     text-level instrument (a KEY= parse: `startswith(KEY=`, `.split("=")`, `.partition("=")`, in a def that holds a
     .env path literal or a module name bound to one) must AGREE with the walk, def by def: a site either finds and the
     other misses is RED, named file:line. A file that doesn't parse is RED; an exemption no site needs is RED (stale).
     E7a pins the census on a planted git tree (a reader in mcp/, hooks/, bridges/, devtools/, scripts/, src/, the top
     level, through a module name, a helper, another module; a regex-only and an AST-only site; negative controls), E7b
     runs it on THIS tree.
  The mcp/, hooks/, bridges/, observatory/ and devtools/ readers migrated with E8–E14 (mcp/{gmail,growbot,imagegen,
  jobs,memory,contacts}/server.py, hooks/nudge.py, bridges/gateway.py, observatory/api/main.py _env_key_names,
  devtools/branch_check_prep.py read_env) can't be imported hermetically (FastMCP, a live bridge, the observatory app,
  psycopg at import): E7 is their gate.
Seams: ENVREAD_SEAT="<path under src/astryx>=<file>[;…]" seats that file in place of the checkout's (the RED: an old
site), ENVREAD_CONFIG_SRC=<file> seats a config.py (tests/mutants_envread.py). Residuals, not migrated: shell `grep '^KEY=' .env`, home.mjs.
Exit 0 · 1.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "src" / "astryx"
PLANTED = "fx-PLANTED-77a1"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def seat(t: Path) -> None:
    shutil.copytree(PKG, t / "src" / "astryx", ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
    (t / "mcp").symlink_to(REPO / "mcp")      # hands/android.py imports mcp/phone/surface.py from its tree (code, no estate)
    for pair in filter(None, (os.environ.get("ENVREAD_SEAT") or "").split(";")):
        rel, src = pair.split("=", 1)
        shutil.copyfile(src, t / "src" / "astryx" / rel)
    if os.environ.get("ENVREAD_CONFIG_SRC"):                       # the probe's seam: a mutant config.py
        shutil.copyfile(os.environ["ENVREAD_CONFIG_SRC"], t / "src" / "astryx" / "config.py")


BAD = b"NOTE=\xff\xfe " + PLANTED.encode() + b"\n"       # line 2 of every fixture .env
ENV = (b"ASTRYX_DSN=postgresql://nobody@127.0.0.1:1/astryx_fx_envread\n" + BAD
       + b"ASTRYX_ORG=envread.fixture.test\nGMAIL_ADDRESS=fixture@example.invalid\n"
       b"GMAIL_APP_PASSWORD=fx-not-a-password\nANDROID_SDK_ROOT=/fx/sdk\nHANDS_STEP_CAP=7\n"
       b"ASTRYX_UPSTREAM=https://example.invalid/fx-PLANTED-up/astryx\nEAR_TTL_DAYS=5\n"
       b"CANVAS_VOICE_DAILY_MINUTES=12.5\nOPENAI_API_KEY=fx-PLANTED-not-a-key\nPEOPLE_SALT=fx-PLANTED-salt\n"
       b"ASTRYX_RELEASE_KEY=fx-PLANTED-release-key-0123456789abcdef\nASTRYX_NODE=/fx/bin/node\n")
FIXTURE_KEYS = {ln.split(b"=", 1)[0].decode() for ln in ENV.splitlines() if b"=" in ln}


def child(t: Path, code: str, *args, reg=None):
    # own-env: the child's registry, HOME and package path are named here; ASTRYX_*, HANDS_*, ANDROID_* and every key
    # the fixture .env names are dropped, so a value an arm reads can only come from T/.env
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("ASTRYX_", "HANDS_", "ANDROID_")) and k not in FIXTURE_KEYS}
    (t / "home").mkdir(exist_ok=True)
    env.update(ASTRYX_COG_REGISTRY=str(reg or t / "no-registry" / "cog.json"), PYTHONPATH=str(t / "src"),
               HOME=str(t / "home"))
    r = subprocess.run([sys.executable, "-c", code, *args] if code else list(args), cwd=t, env=env,
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout.strip(), r.stderr


# psycopg is only a DB path's: a stub where the interpreter has none (the arms never connect)
NO_PG = ("import importlib.util, sys, types\nif importlib.util.find_spec('psycopg') is None:\n"
         "    m = sys.modules['psycopg'] = types.ModuleType('psycopg'); m.sql = sys.modules['psycopg.sql'] = "
         "types.ModuleType('psycopg.sql')\n")
# federation/introduce imports httpx, psycopg and nacl at module level; the arm only reads its .env. Stubbed where the
# interpreter has none, so E14 grades under the push gate's PY=python3 too (land 563a81f0: "No module named 'httpx'")
NO_FED = NO_PG + ("_absent = [p for p in ('httpx', 'nacl') if importlib.util.find_spec(p) is None]\n"
                  "if 'httpx' in _absent:\n    sys.modules['httpx'] = types.ModuleType('httpx')\n"
                  "if 'nacl' in _absent:\n"
                  "    for _n in ('nacl', 'nacl.encoding', 'nacl.signing'):\n"
                  "        sys.modules[_n] = types.ModuleType(_n)\n"
                  "    sys.modules['nacl.encoding'].HexEncoder = object\n"
                  "    sys.modules['nacl.signing'].SigningKey = sys.modules['nacl.signing'].VerifyKey = object\n")
SITES = [
    ("E1", "contrib/canopus_inbound.py", "import sys, types; sys.modules.setdefault('psycopg', types.ModuleType('psycopg'));"
     " import astryx.contrib.canopus_inbound as m; print(m._login_creds()[0])",   # psycopg is only main()'s: a stub where it's absent
     "fixture@example.invalid"),
    ("E2", "federation/card_assert.py", "import astryx.federation.card_assert as m; print(m._env('ASTRYX_ORG'))",
     "envread.fixture.test"),
    ("E3", "hands/android.py", "import astryx.hands.android as m; print(m.sdk())", "/fx/sdk"),
    ("E4", "hands/hands_desktop.py", "import astryx.hands.hands_desktop as m; print(m._env_int('HANDS_STEP_CAP', 300))",
     "7"),
    ("E5", "pulse/shipped_triggers/org_backup.py",
     "import pathlib, astryx.pulse.shipped_triggers.org_backup as m; print(m._org(pathlib.Path.cwd()))",
     "envread.fixture.test"),
    ("E8", "core/upstream_pr.py", "import astryx.core.upstream_pr as m; print(m.setting('ASTRYX_UPSTREAM', 'fx-default'))",
     "https://example.invalid/fx-PLANTED-up/astryx"),
    ("E9", "hearing/ear_store.py", NO_PG + "import astryx.hearing.ear_store as m; print(m._env('EAR_TTL_DAYS'))", "5"),
    # A1 (#62369): every key voice_mint reads is planted and dropped from the child's environment, and its estate is
    # shown to be T, so the arm can only have read T/.env, never the live one
    ("E10", "hearing/voice_mint.py",
     "import pathlib, astryx.hearing.voice_mint as m; from astryx import paths\n"
     "print(m.cap_minutes(), m.env('OPENAI_API_KEY') == 'fx-PLANTED-not-a-key',"
     " paths.estate(m.__file__) == pathlib.Path.cwd())", "12.5 True True"),
    ("E11", "people/people.py", NO_PG + "import astryx.people.people as m; print(m._salt(), m._org())",
     "envread.fixture.test envread.fixture.test"),          # ASTRYX_ORG is named before PEOPLE_SALT: _salt takes it
    ("E12", "security/release.py", "import astryx.security.release as m; print(m.mac_key().decode())",
     "fx-PLANTED-release-key-0123456789abcdef"),
    ("E13", "security/dsn_census.py",
     "import astryx.security.dsn_census as m; print(m._node(), sorted(m.dsns().values()))",
     "/fx/bin/node ['postgresql://nobody@127.0.0.1:1/astryx_fx_envread']"),
    ("E14", "federation/introduce.py",
     NO_FED + "import astryx.federation.introduce as m, pathlib\ne = m.load_env()\n"
     "try:\n    m.load_env(pathlib.Path.cwd() / 'absent.env'); gone = 'read'\nexcept FileNotFoundError:\n    gone = 'raised'\n"
     "print(e['ASTRYX_ORG'], e['HANDS_STEP_CAP'], 'NOTE' in e, gone)", "envread.fixture.test 7 False raised"),
]


def said(err: str, f: Path, n: int) -> bool:
    return f"{f}:{n}: not UTF-8, line skipped" in err and PLANTED not in err and "�" not in err


# ── E7: the census of .env readers, DERIVED (a1 #62368, accepted #62369) ──────────────────────────────────────────────
ENV_LIT = re.compile(r"^(?:.*/)?\.env$")                 # a .env PATH: ".env", "x/.env" (never ".env.example", a message)
CONFIG_API = {"read_env", "get", "dsn", "env_path", "is_set", "set_env", "unset_env", "org_env", "duplicate_keys"}
WRAP = {"Path", "PurePath", "PosixPath", "str", "fspath", "join", "expanduser", "resolve", "absolute"}
READS, WRITES = {"read_text", "read_bytes", "open"}, {"write_text", "write_bytes"}
BENIGN = {"is_file", "exists", "is_dir", "is_symlink", "stat", "lstat", "chmod"}     # a question about the file, no bytes
COLLECT = {"frozenset", "set", "tuple", "list", "sorted"}                    # a collection carrying the path
GROW = {"add", "update", "append", "extend", "insert"}
NAMEISH = {"name", "parent", "suffix", "stem", "parts"}
SKIP_DIRS = {".git", "venv", ".venv", "node_modules", "__pycache__"}
# the text instrument: a KEY= parse (a1's `startswith(KEY=`, and the split/partition on "=" every parser here used)
PARSE = re.compile(r"""startswith\((\w+|f?["'][A-Z_]+)\s*\+?\s*["']?=|\.split\(\s*["']=["']|\.partition\(\s*["']=["']""")
ENV_TXT = re.compile(r"""["'](?:[^"'\n]*/)?\.env["']""")
DEF_TXT = re.compile(r"^(\s*)(?:async\s+)?def\s+\w+")
MOD_ENV_NAME = re.compile(r"""^([A-Za-z_]\w*)\s*(?::[^=]*)?=[^=].*["'](?:[^"'\n]*/)?\.env["']""")
# DECLARED, never a silent skip: (file, def) -> why that site is not a config reader. A stale entry is RED.
EXEMPT = {
    ("src/astryx/config.py", "*"):
        "the ONE reader and writer: read_env, duplicate_keys (a strict read, key NAMES only), _write_env (set_env/"
        "unset_env read strictly: a writer that skipped a bad line would drop it on the rewrite)",
    ("src/astryx/security/secretset.py", "_env_pairs"):
        "the secret HARVESTER, not a config reader: it takes EVERY pair (duplicates, `export `, quoted) so a value no "
        "reader takes is still guarded, and a non-UTF-8 .env raises there, which fails the guard closed",
    ("devtools/cog_add_org.py", "make_home"): "a WRITER: creates a new org's .env (O_EXCL, 0600); it reads nothing",
    ("devtools/branch_check_prep.py", "write_env"):
        "a WRITER: generates the sandbox's .env from read_env()'s values (ENV_ALLOW) and returns its path",
    ("devtools/branch_check.py", "run"):
        "the live .env's PATH handed to the sandbox boundary probe, which proves the sandbox can NOT open it "
        "(branch_check_sandbox: read_bytes, the bytes discarded); never parsed",
}


def git_env():
    """The parent's environment without GIT_*: a hook's GIT_DIR would point `git -C <tree>` at another repo."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def py_files(root: Path):
    """(listing, [rel] or None) for every non-test .py under root: git's index when root is a git tree (a planted
    reader is listed once it is tracked, as on a push), else every file on disk but SKIP_DIRS (the mutation probe's
    tree copy holds the git-listed files and nothing else)."""
    if (root / ".git").exists():
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", "*.py"], capture_output=True, text=True,
                           timeout=60, env=git_env())
        if r.returncode != 0:
            return f"git ls-files rc {r.returncode}", None
        rels, how = [f for f in r.stdout.split("\0") if f], "git ls-files"
    else:
        rels, how = [], "a walk (no .git)"
        for d, ds, fs in os.walk(root):
            ds[:] = sorted(x for x in ds if x not in SKIP_DIRS)
            rels += [(Path(d) / f).relative_to(root).as_posix() for f in fs if f.endswith(".py")]
    return how, sorted(f for f in rels if not f.startswith("tests/"))


class FileCensus:
    """One file's .env paths, each followed to its USE (the kinds in the docstring's E7)."""

    def __init__(self, rel: str, src: str, module=None, others=None):
        self.rel, self.src = rel, src
        self.module, self.others = module or (lambda name: None), others or (lambda: [])
        self.tree = ast.parse(src)
        self.par = {c: n for n in ast.walk(self.tree) for c in ast.iter_child_nodes(n)}
        self.cfg_mods, self.cfg_funcs, self.mods = set(), set(), {}
        for n in ast.walk(self.tree):
            if isinstance(n, ast.ImportFrom) and n.module and not n.level:
                self.mods.update({a.asname or a.name: f"{n.module}.{a.name}" for a in n.names})
                if n.module == "astryx":
                    self.cfg_mods |= {a.asname or a.name for a in n.names if a.name == "config"}
                elif n.module == "astryx.config":
                    self.cfg_funcs |= {a.asname or a.name for a in n.names if a.name in CONFIG_API}
            elif isinstance(n, ast.Import):
                self.mods.update({a.asname: a.name for a in n.names if a.asname})
                self.cfg_mods |= {a.asname for a in n.names if a.name == "astryx.config" and a.asname}
        self.defs = {}
        for n in ast.walk(self.tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.defs.setdefault(n.name, []).append(n)
        self.sites, self.seen = [], set()

    def scope(self, n):
        p = self.par.get(n)
        while p is not None and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            p = self.par.get(p)
        return p

    def where(self, n):
        s, names = self.scope(n), []
        line = s.lineno if s is not None else 0
        while s is not None:
            names.append(getattr(s, "name", "<lambda>"))
            s = self.scope(s)
        return ".".join(reversed(names)) or "<module>", line

    def add(self, kind, n, why):
        fn, defline = self.where(n)
        self.sites.append({"kind": kind, "file": self.rel, "line": n.lineno, "func": fn, "def": defline, "why": why})

    def run(self):
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and ENV_LIT.match(n.value):
                p = self.par.get(n)
                self.use(p if isinstance(p, ast.JoinedStr) else n)     # f"{home}/.env": the f-string is the path
            elif isinstance(n, ast.Call) and self.is_config(n.func) and self.callee(n.func) == "env_path":
                self.use(n)                                             # config's own path, read by hand
        return self.sites

    def is_config(self, f):
        return (isinstance(f, ast.Attribute) and f.attr in CONFIG_API and isinstance(f.value, ast.Name)
                and f.value.id in self.cfg_mods) or (isinstance(f, ast.Name) and f.id in self.cfg_funcs)

    @staticmethod
    def callee(f):
        return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None

    def use(self, n, depth=0):
        if id(n) in self.seen:
            return
        self.seen.add(id(n))
        if depth > 24:
            return self.add("unclassified", n, "a use chain deeper than the census follows")
        p, d = self.par.get(n), depth + 1
        if isinstance(p, ast.BinOp) and isinstance(p.op, (ast.Div, ast.Add)):
            return self.use(p, d)
        if isinstance(p, (ast.If, ast.While, ast.IfExp, ast.Assert)) and n is p.test \
                or isinstance(p, ast.UnaryOp) and isinstance(p.op, ast.Not):
            return self.add("benign", n, "truth-tested (no bytes)")
        if isinstance(p, (ast.IfExp, ast.BoolOp, ast.JoinedStr)) \
                or isinstance(p, (ast.ListComp, ast.SetComp, ast.GeneratorExp)) and n is p.elt:
            return self.use(p, d)
        if isinstance(p, ast.FormattedValue):
            return self.add("benign", n, "said in a message")
        if isinstance(p, (ast.Tuple, ast.List, ast.Set)):
            gp = self.par.get(p)
            if isinstance(gp, ast.Assign) and gp.value is p and len(gp.targets) == 1 \
                    and isinstance(gp.targets[0], ast.Tuple) and len(gp.targets[0].elts) == len(p.elts):
                return self.bind(gp.targets[0].elts[p.elts.index(n)], gp, d)
            return self.use(p, d)
        if isinstance(p, ast.Compare):
            return self.add("benign", n, "compared (a pattern, no bytes)")
        if isinstance(p, ast.keyword):
            return self.arg(self.par.get(p), n, d, kw=p.arg)
        if isinstance(p, ast.Call):
            return self.add("unclassified", n, "called") if n is p.func else self.arg(p, n, d)
        if isinstance(p, ast.Attribute) and p.value is n:
            gp = self.par.get(p)
            if isinstance(gp, ast.Call) and gp.func is p:
                if p.attr in READS:
                    if p.attr == "read_bytes" and isinstance(self.par.get(gp), ast.Expr):
                        return self.add("probe", gp, "read_bytes() discarded: an absent file raises, nothing decoded")
                    return self.add("read", gp, f".{p.attr}() on a .env path")
                if p.attr in WRITES:
                    return self.add("write", gp, f".{p.attr}()")
                if p.attr in BENIGN:
                    return self.add("benign", gp, f".{p.attr}()")
                if p.attr in WRAP:
                    return self.use(gp, d)
                if p.attr in ("startswith", "endswith") or p.attr in GROW:
                    return self.add("benign", gp, f".{p.attr}() (a pattern, or a collection of paths)")
                return self.add("unclassified", gp, f".{p.attr}() on a .env path")
            if p.attr in NAMEISH:
                return self.add("benign", p, f".{p.attr} (no bytes)")
            return self.add("unclassified", p, f".{p.attr} on a .env path")
        if isinstance(p, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and p.value is n:
            for t in (p.targets if isinstance(p, ast.Assign) else [p.target]):
                self.bind(t, p, d)
            return
        if isinstance(p, (ast.For, ast.comprehension)) and p.iter is n:
            return self.bind(p.target, p, d)
        if isinstance(p, ast.Return):
            return self.returned(n, d)
        if isinstance(p, ast.arguments):
            return self.default(p, n, d)
        return self.add("unclassified", n, f"under {type(p).__name__}")

    def arg(self, call, n, d, kw=None):
        f = call.func
        name = self.callee(f)
        if self.is_config(f):
            return self.add("config", call, f"config.{name}()")
        if name in WRAP or name in COLLECT:
            return self.use(call, d)
        if name in GROW and isinstance(f, ast.Attribute):
            return self.add("benign", call, f"collected by .{name}()")
        if name == "chmod":
            return self.add("benign", call, "chmod() (no bytes)")
        if name and name.endswith(("Error", "Exception")):
            return self.add("benign", call, f"said in a {name}")
        if name == "add_argument" and kw == "default":         # argparse: follow the option to its attribute
            opt = next((a.value for a in call.args if isinstance(a, ast.Constant) and str(a.value).startswith("--")),
                       None)
            dest = next((k.value.value for k in call.keywords if k.arg == "dest" and isinstance(k.value, ast.Constant)),
                        opt and opt[2:].replace("-", "_"))
            hits = [x for x in ast.walk(self.tree) if isinstance(x, ast.Attribute) and x.attr == dest
                    and isinstance(x.ctx, ast.Load)] if dest else []
            for h in hits:
                self.use(h, d)
            if hits:
                return
        if name == "open" and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "os":
            flags = ast.get_source_segment(self.src, call) or ""
            return self.add("write" if re.search(r"O_(WRONLY|RDWR|CREAT|APPEND)", flags) else "read", call, "os.open()")
        if name == "open":
            mode = call.args[1] if len(call.args) > 1 else next((k.value for k in call.keywords if k.arg == "mode"), None)
            m = "r" if mode is None else mode.value if isinstance(mode, ast.Constant) and isinstance(mode.value, str) \
                else None
            if m is None:
                return self.add("unclassified", call, "open() with a mode the census can't read")
            return self.add("write" if set(m) & set("wax+") else "read", call, f"open(…, {m!r})")
        if name in ("startswith", "endswith"):
            return self.add("benign", call, f"a .{name}() pattern")
        # a helper of this file, or a function of a censused module this file imports: follow it to its parameter
        if isinstance(f, ast.Name) and f.id in self.defs:
            fc, fname = self, f.id
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in self.mods:
            fc, fname = self.module(self.mods[f.value.id]), f.attr
        elif isinstance(f, ast.Name) and f.id in self.mods:                       # from mod import helper
            dotted = self.mods[f.id]
            fc, fname = self.module(dotted.rsplit(".", 1)[0]), dotted.rsplit(".", 1)[1]
        else:
            fc, fname = None, None
        if fc is not None and fname in fc.defs:
            pos = call.args.index(n) if n in call.args else None
            hit = False
            for fd in fc.defs[fname]:
                params = [a.arg for a in fd.args.posonlyargs + fd.args.args + fd.args.kwonlyargs]
                pname = kw if kw in params else params[pos] if kw is None and pos is not None and pos < len(params) \
                    else None
                if pname:
                    hit = True
                    fc.param(fd, pname, d)
            if hit:
                return
        return self.add("unclassified", call, f"handed to {name or '?'}()")

    def bind(self, t, at, d):
        if isinstance(t, ast.Name):
            if isinstance(at, ast.comprehension):     # [f(x) for x in X]: the loads are the comprehension's own
                inner = {id(x) for x in ast.walk(at.iter)}
                found = [x for x in ast.walk(self.par.get(at)) if isinstance(x, ast.Name) and x.id == t.id
                         and isinstance(x.ctx, ast.Load) and id(x) not in inner]
                for x in found:
                    self.use(x, d)
                return None if found else self.add("benign", t, f"{t.id} bound, never read")
            return self.loads(t.id, self.scope(at), self.bound_at(t), d, t)
        if isinstance(t, ast.Attribute):            # self.env = …: every load of .env on the same base
            hits = [x for x in ast.walk(self.tree) if isinstance(x, ast.Attribute) and x.attr == t.attr
                    and isinstance(x.ctx, ast.Load) and ast.dump(x.value) == ast.dump(t.value)]
            for h in hits:
                self.use(h, d)
            return None if hits else self.add("unclassified", t, f"stored in .{t.attr}, never read here")
        return self.add("unclassified", t, f"bound to a {type(t).__name__}")

    def bound_at(self, store):
        """Where a binding takes effect: after the value it is bound from (`env = f(env)` reads the OLD env)."""
        p = store
        while p is not None:
            if isinstance(p, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)) and p.value is not None:
                return (p.value.end_lineno, p.value.end_col_offset)
            if isinstance(p, (ast.For, ast.AsyncFor, ast.comprehension)):
                return (p.iter.end_lineno, p.iter.end_col_offset)
            if isinstance(p, ast.withitem):
                return (p.context_expr.end_lineno, p.context_expr.end_col_offset)
            if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return (p.lineno, 0)
            if isinstance(p, ast.stmt):
                return (p.lineno, p.col_offset)
            p = self.par.get(p)
        return (store.lineno, store.col_offset)

    def binds(self, s, name):
        """[(node, position)] where `name` is (re)bound in scope s (None: the module's own statements)."""
        out = []
        for x in ast.walk(s if s is not None else self.tree):
            if isinstance(x, ast.arg) and x.arg == name and self.par.get(self.par.get(x)) is s and s is not None:
                out.append((x, (s.lineno, 0)))
            elif self.scope(x) is s and isinstance(x, ast.Name) and x.id == name \
                    and isinstance(x.ctx, (ast.Store, ast.Del)):
                out.append((x, self.bound_at(x)))
        return out

    def loads(self, name, s, after, d, own=None):
        """Every load of `name` the binding at position `after` in scope s reaches: in s after it and before its
        next rebinding, or in a nested function that never binds the name itself."""
        later = sorted(at for x, at in self.binds(s, name) if x is not own and at > after)
        stop = later[0] if later else (10 ** 9, 0)
        found = False
        for x in ast.walk(s if s is not None else self.tree):
            if not (isinstance(x, ast.Name) and x.id == name and isinstance(x.ctx, ast.Load)):
                continue
            xs = self.scope(x)
            if xs is s and after < (x.lineno, x.col_offset) < stop or xs is not s and not self.binds(xs, name):
                found = True
                self.use(x, d)
        if not found:
            anchor = own if own is not None else ast.Pass(lineno=after[0])
            self.par.setdefault(anchor, s if s is not None else self.tree)
            self.add("benign", anchor, f"{name} bound, never read")

    def param(self, fd, pname, d):
        own = next((a for a in ast.walk(fd.args) if isinstance(a, ast.arg) and a.arg == pname), None)
        self.loads(pname, fd, (fd.lineno, 0), d, own)

    def default(self, args, n, d):
        fd = self.par.get(args)
        pos = [a.arg for a in args.posonlyargs + args.args]
        for a, v in list(zip(pos[len(pos) - len(args.defaults):], args.defaults)) + \
                [(k.arg, v) for k, v in zip(args.kwonlyargs, args.kw_defaults)]:
            if v is n:
                return self.param(fd, a, d)
        return self.add("unclassified", n, "a default the census can't place")

    def returned(self, n, d):
        """A returned path: followed to every call of the function, in this file and in every censused file that
        imports this one. None found is UNCLASSIFIED."""
        fd = self.scope(n)
        name = getattr(fd, "name", None)
        calls = [] if not name else \
            [(self, c) for c in ast.walk(self.tree) if isinstance(c, ast.Call) and self.callee(c.func) == name
             and (isinstance(c.func, ast.Name) or isinstance(c.func.value, ast.Name)
                  and c.func.value.id in ("self", "cls"))]
        for fc in self.others() if name else []:
            if fc is self:
                continue
            for c in ast.walk(fc.tree):
                if not isinstance(c, ast.Call):
                    continue
                f = c.func
                if isinstance(f, ast.Attribute) and f.attr == name and isinstance(f.value, ast.Name) \
                        and f.value.id in fc.mods and fc.module(fc.mods[f.value.id]) is self \
                        or isinstance(f, ast.Name) and f.id in fc.mods and fc.mods[f.id].endswith("." + name) \
                        and fc.module(fc.mods[f.id].rsplit(".", 1)[0]) is self:
                    calls.append((fc, c))
        if not calls:
            return self.add("unclassified", n, f"returned out of this file by {name or 'a lambda'}()")
        for fc, c in calls:
            fc.use(c, d)


def regex_sites(rel: str, src: str):
    """The text instrument, independent of the AST walk: a line holding a KEY= parse, in a block (the def it sits in,
    by indentation; else the module) that holds a .env path literal or a name the module binds to one."""
    lines = src.splitlines()
    mod_names = {m.group(1) for ln in lines for m in [MOD_ENV_NAME.match(ln)] if m}
    name_re = re.compile(r"\b(" + "|".join(map(re.escape, sorted(mod_names))) + r")\b") if mod_names else None
    out = []
    for i, ln in enumerate(lines):
        if not PARSE.search(ln):
            continue
        ind, start, dind = len(ln) - len(ln.lstrip()), None, -1
        for j in range(i, -1, -1):                 # the innermost def above it, less indented than the line
            m = DEF_TXT.match(lines[j])
            if m and len(m.group(1)) < ind:
                start, dind = j, len(m.group(1))
                break
        block = lines
        if start is not None:
            end = next((k for k in range(start + 1, len(lines)) if lines[k].strip()
                        and len(lines[k]) - len(lines[k].lstrip()) <= dind
                        and not lines[k].lstrip().startswith((")", "]", "}"))), len(lines))
            block = lines[start:end]
        text = "\n".join(block)
        if ENV_TXT.search(text) or (name_re and name_re.search(text)):
            out.append({"file": rel, "line": i + 1, "def": start + 1 if start is not None else 0})
    return out


def census(root: Path, exempt: dict):
    """-> (listing, [(file, line, finding)], {kind: count}, n files)."""
    how, rels = py_files(root)
    findings, counts, used, by_rel = [], {}, set(), {}
    if rels is None:
        return how, [("", 0, f"the file listing failed ({how}): nothing was searched")], counts, 0

    def module(dotted):                         # a censused file by its import name (astryx.* lives under src/)
        base = dotted.replace(".", "/")
        return next((by_rel[c] for c in (f"{base}.py", f"{base}/__init__.py", f"src/{base}.py",
                                          f"src/{base}/__init__.py") if c in by_rel), None)
    for rel in rels:
        try:
            with warnings.catch_warnings():         # a file's own SyntaxWarning (an escape in a docstring) is not ours
                warnings.simplefilter("ignore", SyntaxWarning)
                by_rel[rel] = FileCensus(rel, (root / rel).read_text(), module, lambda: list(by_rel.values()))
        except (SyntaxError, UnicodeDecodeError, ValueError, OSError) as e:
            findings.append((rel, 0, f"unparseable or unreadable ({type(e).__name__}): its .env uses can't be "
                                     f"classified"))
    for fc in list(by_rel.values()):
        fc.run()
    for rel, fc in by_rel.items():
        ast_reads, exempt_defs = {}, set()
        for s in fc.sites:
            counts[s["kind"]] = counts.get(s["kind"], 0) + 1
            key = next((k for k in ((rel, s["func"]), (rel, "*")) if k in exempt), None)
            if key:
                exempt_defs.add(s["def"])
            if s["kind"] not in ("read", "write", "unclassified"):
                continue
            if key:
                used.add(key)
                continue
            findings.append((rel, s["line"], f"{s['func']}(): {s['kind'].upper()}, {s['why']}"))
            if s["kind"] == "read":
                ast_reads.setdefault(s["def"], s)
        rx = {} if (rel, "*") in exempt else \
            {r["def"]: r for r in reversed(regex_sites(rel, fc.src)) if r["def"] not in exempt_defs}
        for dl in sorted(set(ast_reads) - set(rx)):
            findings.append((rel, ast_reads[dl]["line"], "the AST walk finds a read here that the text instrument "
                                                         "misses (no KEY= parse beside a .env path in its def)"))
        for dl in sorted(set(rx) - set(ast_reads)):
            findings.append((rel, rx[dl]["line"], "the text instrument finds a KEY= parse beside a .env path that the "
                                                  "AST walk reads nowhere in this def"))
    for k in sorted(set(exempt) - used):
        findings.append((k[0], 0, f"{k[1]}: a declared exemption no site needs any more (stale)"))
    return how, findings, counts, len(rels)


# E7a's planted tree: (path, source). `# P:<tag>` marks the line a finding must name; `# P:-` lines must name none.
PLANT = {
    "mcp/fx/server.py":
        "from pathlib import Path\nROOT = Path(__file__).parent\n\n\ndef key():\n"
        "    for line in (ROOT / '.env').read_text().splitlines():  # P:mcp-read\n"   # org-home: E7a's planted source text, never run
        "        if line.startswith('FX_KEY='):  # P:mcp-rx\n            return line.split('=', 1)[1]\n",
    "hooks/fx_hook.py":
        "def env():\n    out = {}\n    with open('/fx/home/.env') as f:  # P:hooks-read\n        for line in f:\n"
        "            k, v = line.split('=', 1)  # P:hooks-rx\n            out[k] = v\n    return out\n",
    "bridges/fx_bridge.py":
        "from pathlib import Path\nENV = Path('/fx') / '.env'\n\n\ndef tok():\n"
        "    for ln in ENV.read_text().splitlines():  # P:bridges-read\n"
        "        if ln.startswith(KEY + '='):  # P:bridges-rx\n            return ln\n\n\nKEY = 'FX_TOKEN'\n",
    "devtools/fx_tool.py":        # an AST-only site: the helper's own def holds no .env path, so the text misses it
        "from pathlib import Path\n\n\ndef _parse(p):\n"
        "    return dict(l.split('=', 1) for l in Path(p).read_text().splitlines())  # P:helper-read P:helper-astonly\n"
        "\n\ndef main():\n    return _parse(Path('/fx') / '.env')\n",
    "scripts/fx_script.py":       # a TEXT-only site: the bytes come through a subprocess the walk can't classify
        "import subprocess\n\n\ndef val():\n"
        "    out = subprocess.run(['cat', '/fx/.env'], capture_output=True, text=True).stdout  # P:script-unclass\n"
        "    return [l for l in out.splitlines() if l.startswith('FX_K=')]  # P:script-rxonly\n",
    "src/astryx/fx_ok.py":        # negative controls: config, a probe, questions, a message, a pattern
        "from pathlib import Path\nfrom astryx import config\nHOME = Path('/fx')\n\n\ndef ok():\n"
        "    e = config.read_env(HOME / '.env')  # P:-\n    (HOME / '.env').read_bytes()  # P:-\n"
        "    if not (HOME / '.env').is_file():  # P:-\n        print(f\"no {HOME / '.env'}\")  # P:-\n"
        "    return e.get('FX'), Path('x').name.startswith('.env')  # P:-\n",
    "src/astryx/fx_lib.py":
        "from pathlib import Path\n\n\ndef load(p):\n"
        "    return [l.partition('=') for l in Path(p).read_text().splitlines()]  # P:cross-read P:cross-astonly\n",
    "src/astryx/fx_cross.py":
        "from pathlib import Path\nfrom astryx import fx_lib\n\n\ndef go():\n    return fx_lib.load(Path('/fx') / '.env')\n",
    "src/astryx/fx_probe.py":     # a DECODING probe: read_text() discarded still decodes, so it is a read
        "from pathlib import Path\n(Path('/fx') / '.env').read_text()  # P:probe-text\n",
    "fx_top.py":
        "VALS = [l.split('=', 1) for l in open('.env').read().splitlines()]  # P:top-read P:top-rx\n",
    "src/astryx/fx_broken.py": "def broken(:\n    return open('.env')  # P:broken\n",
    "tests/test_fx.py": "print(open('.env').read().split('='))  # P:-  (tests/ is out of scope)\n",
}
UNTRACKED = ("src/astryx/fx_untracked.py", "print(open('.env').read().split('='))  # P:-  (never git-added)\n")


def control(td: Path):
    root = td / "plant"
    for rel, src in PLANT.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(src)
    ok = [subprocess.run(["git", "-C", str(root), *a], capture_output=True, timeout=60, env=git_env()).returncode == 0
          for a in (["init", "-q"], ["add", "-A"])]
    (root / UNTRACKED[0]).write_text(UNTRACKED[1])
    marks, negatives = {}, set()
    for rel, src in PLANT.items():
        for n, ln in enumerate(src.splitlines(), 1):
            for tag in re.findall(r"P:(\S+)", ln):
                if tag == "-":
                    negatives.add((rel, n))
                else:
                    marks[tag] = (rel, n)
    how, found, counts, nfiles = census(root, {})
    at = {}
    for rel, line, what in found:
        at.setdefault((rel, line), []).append(what)

    def hit(tag, needle):
        rel, n = marks[tag]
        return any(needle in w for w in at.get((rel, n), []) + (at.get((rel, 0), []) if tag == "broken" else []))
    check("E7a the planted tree is listed through git ls-files (a .git tree), the untracked plant not among them",
          all(ok) and how == "git ls-files" and nfiles == len(PLANT) - 1, f"git {ok} {how} {nfiles} files")
    for tag in ("mcp-read", "hooks-read", "bridges-read", "helper-read", "cross-read", "top-read"):
        check(f"E7a a hand-rolled reader is found by the AST walk, named file:line ({marks[tag][0]}:{marks[tag][1]})",
              hit(tag, ": READ,"), at)
    for tag in ("mcp-read", "hooks-read", "bridges-read", "top-read"):
        rel = marks[tag][0]
        check(f"E7a ... and the text instrument agrees on it ({rel}: no disagreement named)",
              not any("instrument" in w for (r, _), ws in at.items() if r == rel for w in ws), at)
    check("E7a a discarded read_text() is a READ (it decodes; only a discarded read_bytes() is a probe)",
          hit("probe-text", ": READ,"), at)
    check("E7a a use the walk can't classify (a subprocess handed the path) is UNCLASSIFIED, RED",
          hit("script-unclass", "UNCLASSIFIED"), at)
    check("E7a a TEXT-only site (a KEY= parse beside a .env path, no read the walk sees) is a named disagreement",
          hit("script-rxonly", "the text instrument finds"), at)
    check("E7a an AST-only site (a helper's read, no .env path in its def) is a named disagreement, both ways pinned",
          hit("helper-astonly", "the AST walk finds") and hit("cross-astonly", "the AST walk finds"), at)
    check("E7a an unparseable file is RED, never skipped", hit("broken", "unparseable"), at)
    check("E7a config's API, a discarded read_bytes probe, a question, a message, a pattern, tests/ and an untracked "
          "file: no finding", not any(k in negatives for k in at) and not any(r.startswith(("tests/", UNTRACKED[0]))
                                                                              for r, _ in at), at)
    ex = {(marks["bridges-read"][0], "tok"): "fx reason", ("nowhere.py", "x"): "fx stale"}
    _, found2, _, _ = census(root, ex)
    check("E7a a DECLARED exemption holds its site (the read and the text instrument's line both), and a stale one is "
          "RED", not any(r == marks["bridges-read"][0] for r, _, _ in found2)
          and any(r == "nowhere.py" and "stale" in w for r, _, w in found2), found2)


with tempfile.TemporaryDirectory() as td:
    t = Path(td).resolve()
    seat(t)
    (t / ".env").write_bytes(ENV)

    print("E0 read_env ITSELF")
    e0 = t / "e0.env"
    e0.write_bytes(b"A=1\n" + BAD + b"K=\xfe" + PLANTED.encode() + b"\nK=later\nB=2\n")
    rc, out, err = child(t, "import json, sys; from astryx import config; print(json.dumps(config.read_env(sys.argv[1])))",
                         str(e0))
    try:
        got = json.loads(out) if rc == 0 else None        # stdout is the dict alone: a word printed there is a FAIL
    except ValueError:
        got = None
    check("an unrelated bad line: the keys before and after it read", got is not None and got.get("A") == "1"
          and got.get("B") == "2", f"rc {rc} {out!r} {err[-200:]!r}")
    check("the asked key's bad FIRST line: absent, its later line not taken in its place",
          got is not None and "K" not in got and "NOTE" not in got, f"{got}")
    check("stderr says each bad line as file:line and names the absent key, never the value",
          said(err, e0, 2) and said(err, e0, 3) and "(K reads as absent)" in err, err[-300:])

    for tag, rel, code, want in SITES:
        print(f"\n{tag} {rel}")
        rc, out, err = child(t, code)
        check(f"{tag} the asked key reads past a non-UTF-8 line ({want})", rc == 0 and out == want,
              f"rc {rc} {out!r} {err.strip().splitlines()[-1:] if err.strip() else ''}")
        check(f"{tag} the skip is said on stderr as file:line, without the value", said(err, t / ".env", 2), err[-200:])

    print("\nE6 NAMES' CLASH CHECK OVER A NON-UTF-8 .env")
    homes = {}
    for o, name, bad in (("fxa", "a.fixture.test", True), ("fxb", "b.fixture.test", False),
                         ("fxc", "A.fixture.test", True)):
        h = t / f"home-{o}"
        h.mkdir()
        (h / ".env").write_bytes(b"ASTRYX_DSN=postgresql://nobody@127.0.0.1:1/fx\n" + (BAD if bad else b"")
                                 + f"ASTRYX_ORG={name}\n".encode())
        homes[o] = h

    def reg(keys, fn):
        f = t / fn
        f.write_text(json.dumps({"orgs": {o: {"home": str(homes[o]), "db": f"fxenvread_{o}"} for o in keys}}))
        return f

    orgs_py = str(t / "src" / "astryx" / "orgs.py")
    rc, out, err = child(t, None, sys.executable, orgs_py, "dupnames", reg=reg(["fxa", "fxb"], "r2.json"))
    check("distinct names, one .env not UTF-8: rc 0 (never 2, the clash check is not blinded)", rc == 0 and out == "",
          f"rc {rc} {out!r} {err[-200:]!r}")
    rc, out, err = child(t, None, sys.executable, orgs_py, "dupnames", reg=reg(["fxa", "fxb", "fxc"], "r3.json"))
    check("two orgs under one name, both .env not UTF-8: rc 1 naming both (the clash is still seen)",
          rc == 1 and out == "a.fixture.test\tfxa fxc", f"rc {rc} {out!r} {err[-200:]!r}")

    print("\nE7a THE CENSUS, PINNED ON A PLANTED TREE")
    control(t)

print("\nE7b THE CENSUS OF THIS TREE: every .env read goes through config, or is declared")
how, found, counts, nfiles = census(REPO, EXEMPT)
print(f"  listed by {how}: {nfiles} non-test .py; uses by kind {dict(sorted(counts.items()))}")
for rel, line, what in found:
    print(f"    {rel}:{line}: {what}")
check(f"E7b no hand-rolled .env reader, writer or unclassified use outside the declared exemptions ({len(found)} named "
      f"above)", not found)
check("E7b enough is classified that the zero means something (≥ 300 files listed, ≥ 50 config uses)",
      nfiles >= 300 and counts.get("config", 0) >= 50, f"{nfiles} files, {counts}")

print()
print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else
      "ALL PASS: every Python .env reader reads through config.read_env, per line, a bad line skipped loudly")
sys.exit(1 if fails else 0)
