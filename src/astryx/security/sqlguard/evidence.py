"""What a sqlguard GRADE was judged FROM: the stamp and the seal (plan-11908 D1 + D2 + D3, a4 #62645).

A grade is a pure function of a tuple: the code tree, the estate, the stored covering, the env and the EVIDENCE (the
trace dir). A decision taken from a grade whose tuple wasn't sealed is not a pass. On 10-23 the evidence changed 80 ms
after the verdict: enforce's own SQL was appended to the trace dir it had just judged, and a later re-judge of the
same dir by glob disagreed with the report (a3 H1 #62644).

THE SEAL (D2) is a BYTE PREFIX per file, never a file list. The shim opens one file per process lazily, in append
mode, so a process alive at judge time (enforce itself, a gate still running) keeps appending to a file a file-list
seal already names. seal(d) = sorted [name, nbytes, sha256 of exactly those bytes] over trace-*.jsonl AND gates.tsv
(a1 BC-1 #62653: both are judge's own reads), each cut at its last "\\n": a partial final line is outside the seal,
never a shim error.
  read_sealed(d, seal) reads EXACTLY each sealed prefix. A prefix whose sha no longer matches (or a sealed file that
  is gone or shorter) is "sealed evidence changed", NOT SEARCHED. Bytes past a prefix, and files the seal doesn't
  name, are counted and named as "N post-seal records ignored: <names>".

TWO READER CLASSES (D3). GRADERS read only through a seal: judge.load_traces(d, seal). A WITNESS counts what touched
prod, and a guard's own post-verdict SQL against the live DB is still a prod statement, so a witness reads the WHOLE
dir: witness_traces(d). Every trace-dir read in src/ and devtools/ calls one of the two (the census arm in
tests/test_sqlguard_seal.py); a new reader is accused until it's classed.

THE STAMP (D1) is the one header, for report.json and the ledger seed alike: commit, estate_hash (informational) and
estate_code_hash (the estate files the inventory reads), the sha256 of the stored covering, the env and the seal. The
env census runs over the package's whole static astryx import closure, alias-aware, and every name it finds is classed:
STAMP_ENV, or NOT_INPUT with its reason, or the seal test is RED (a3 R-3). Stamped as {name: sha256(value)[:16] |
null}, never a value (a2 BC-1 #62651: the admin DSN is one of them). A consumer compares COMPARED (commit,
estate_code_hash, env) to its own; a mismatch is NOT SEARCHED, "evidence from X, judged at Y", never a grade.
VOLATILE names are per-process identity (which dir, gate or run, the HOME selectors, a child's libpq options): stamped,
never compared.
Graded DETECTION against a same-uid writer (anyone can rewrite a trace AND report.json); PREVENTION against the guard's
own post-verdict acts and concurrent appenders, which is the measured failure.
"""
import ast
import glob
import hashlib
import json
import os
import subprocess
from pathlib import Path

PKG = Path(__file__).resolve().parent
SEALED = ("trace-*.jsonl", "gates.tsv")

STAMP_ENV = ("ASTRYX_COG_REGISTRY", "ASTRYX_FIXTURE_ADMIN_DSN", "ASTRYX_FIXTURE_TEMPLATE", "ASTRYX_HOME",
             "ASTRYX_REPO_COMMON", "ASTRYX_SQLGUARD_DIR", "ASTRYX_SQLGUARD_ESTATE_SRC", "ASTRYX_SQLGUARD_GATE",
             "ASTRYX_SQLGUARD_ROOT", "ASTRYX_SQLGUARD_RUN", "ASTRYX_SQLGUARD_WRITE_SEEN", "PGOPTIONS")
# Stamped, never compared: per-process identity. ASTRYX_HOME and ASTRYX_COG_REGISTRY select the HOME (a resident's
# shell carries its own); they stay safe only because the estate CODE they select is compared (estate_code_hash, a3
# #62830 call 1). ASTRYX_SQLGUARD_WRITE_SEEN (D5) is the timer's role, not an input of a grade: it decides whether
# enforce advances the seen-set clocks, never what judge grades, and a hand admit after a timer run must not mismatch.
VOLATILE = frozenset({"ASTRYX_SQLGUARD_DIR", "ASTRYX_SQLGUARD_GATE", "ASTRYX_SQLGUARD_RUN", "ASTRYX_COG_REGISTRY",
                      "ASTRYX_HOME", "ASTRYX_SQLGUARD_WRITE_SEEN", "PGOPTIONS"})
# Read in the import closure but never an input of a grade, each with its reason. A census name in neither STAMP_ENV nor
# here turns tests/test_sqlguard_seal.py RED (a3 R-3).
NOT_INPUT = {
    "ASTRYX_DSN": "read only by config.dsn(env_first=True); every sqlguard DSN read is fixture.live_dsn, which passes "
                  "env_first=False (the .env FILE), and an oracle binds ASTRYX_DSN to its fixture, never the judge",
}
COMPARED = ("commit", "estate_code_hash", "env")


def _closure(pkg: Path, src: Path) -> list:
    """pkg's .py files plus every astryx module they import, transitively (function-level imports too)."""
    def modfile(name):
        p = src / name.replace(".", "/")
        return p / "__init__.py" if (p / "__init__.py").exists() else p.with_suffix(".py") if p.with_suffix(".py").exists() else None
    todo, seen = [f.resolve() for f in pkg.rglob("*.py")], set()
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        for n in ast.walk(ast.parse(f.read_text(), str(f))):
            names = []
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                names = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
            todo += [m.resolve() for m in map(modfile, (x for x in names if x.startswith("astryx"))) if m]
    return sorted(seen)


def env_census(pkg: Path = PKG, src: Path = None) -> dict:
    """{name: [files]}: every env name READ BY NAME anywhere in pkg's static astryx import closure (a3 R-3 #62830: the
    package alone missed paths.py's ASTRYX_REPO_COMMON, read through an alias). A read is os.environ.get/setdefault/pop(N),
    os.getenv(N), os.environ[N] as a load, `N in os.environ`, on os.environ OR an alias of it: a name assigned from an
    expression mentioning os.environ, or a parameter called env/environ. N is a literal or a str constant of that file.
    A whole-env copy (`os.environ.items()`) names nothing, so it isn't counted. Every name found must be classed:
    STAMP_ENV or NOT_INPUT."""
    src = src or pkg.parents[2]
    reads = {}
    for f in _closure(pkg, src):
        tree = ast.parse(f.read_text(), str(f))
        consts = {t.id: n.value.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                  and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
                  for t in n.targets if isinstance(t, ast.Name)}
        alias = {"environ", "env"}
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and "os.environ" in ast.unparse(n.value):
                alias |= {t.id for t in n.targets if isinstance(t, ast.Name)}

        def name(x):
            if isinstance(x, ast.Constant) and isinstance(x.value, str):
                return x.value
            return consts.get(x.id) if isinstance(x, ast.Name) else None

        is_env = lambda x: ast.unparse(x) == "os.environ" or (isinstance(x, ast.Name) and x.id in alias)
        for n in ast.walk(tree):
            got = None
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.args:
                if n.func.attr in ("get", "setdefault", "pop") and is_env(n.func.value):
                    got = name(n.args[0])
                elif ast.unparse(n.func) == "os.getenv":
                    got = name(n.args[0])
            elif isinstance(n, ast.Subscript) and is_env(n.value) and isinstance(n.ctx, ast.Load):
                got = name(n.slice)
            elif isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], (ast.In, ast.NotIn)) \
                    and is_env(n.comparators[0]):
                got = name(n.left)
            if got:
                rel = f.relative_to(src.parent) if f.is_relative_to(src.parent) else f
                reads.setdefault(got, set()).add(str(rel))
    return {k: sorted(v) for k, v in reads.items()}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _files(d) -> list:
    return sorted({os.path.basename(p) for pat in SEALED for p in glob.glob(os.path.join(d, pat))})


def seal(d) -> dict:
    """{"files": [[name, nbytes, sha256]], "lines": n}: each sealed file cut at its last newline."""
    out, lines = [], 0
    for name in _files(d):
        with open(os.path.join(d, name), "rb") as f:
            b = f.read()
        b = b[:b.rfind(b"\n") + 1]
        out.append([name, len(b), _sha(b)])
        lines += b.count(b"\n")
    return {"files": out, "lines": lines}


def read_sealed(d, sl) -> tuple:
    """({name: text of exactly its sealed prefix}, changed: [names], ignored: [post-seal notes])."""
    texts, changed, ignored_n, ignored_names = {}, [], 0, []
    sealed = {n: (nb, h) for n, nb, h in sl["files"]}
    for name, (nb, h) in sorted(sealed.items()):
        p = os.path.join(d, name)
        try:
            with open(p, "rb") as f:
                b = f.read()
        except OSError:
            changed.append(name)
            continue
        head = b[:nb]
        if len(head) < nb or _sha(head) != h:
            changed.append(name)
            continue
        texts[name] = head.decode("utf-8", errors="replace")
        tail = b[nb:]
        if tail.strip():
            ignored_n += tail.count(b"\n") + (0 if tail.endswith(b"\n") else 1)
            ignored_names.append(name)
    for name in _files(d):
        if name not in sealed:
            with open(os.path.join(d, name), "rb") as f:
                b = f.read()
            if b.strip():
                ignored_n += b.count(b"\n") + (0 if b.endswith(b"\n") else 1)
                ignored_names.append(name)
    notes = [f"{ignored_n} post-seal records ignored: {', '.join(ignored_names)}"] if ignored_names else []
    return texts, changed, notes


def witness_traces(d):
    """WITNESS reader (D3): every record in every trace file of the dir, post-seal included. For counting what
    touched prod, never for a grade."""
    for f in sorted(glob.glob(os.path.join(d, "trace-*.jsonl"))):
        with open(f, errors="replace") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def env_stamp(environ=None) -> dict:
    environ = os.environ if environ is None else environ
    return {n: (_sha(environ[n].encode())[:16] if n in environ else None) for n in STAMP_ENV}


def covering_sha(covering) -> str | None:
    if not covering:
        return None
    return _sha(json.dumps(covering, sort_keys=True, default=sorted).encode())


def stamp(root: Path, estate_src: Path = None, covering=None, sl=None) -> dict:
    from astryx.security.sqlguard.ledger import estate_hash
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    src = estate_src or Path(os.environ.get("ASTRYX_SQLGUARD_ESTATE_SRC") or root)
    out = {"commit": commit, **estate_hash(root, src), "covering_sha": covering_sha(covering), "env": env_stamp()}
    if sl is not None:
        out["seal"] = sl
    return out


def compare(theirs, mine, fields=COMPARED) -> list:
    """The mismatches between a stamp a grade was judged at and the consumer's own tuple, as
    "evidence from X, judged at Y" lines. Empty = the same tuple. VOLATILE env names are never compared; estate_hash
    (the whole estate, logs and store rows included) is stamped but informational, estate_code_hash is compared.
    KNOWN LIMIT (a3 N-2 #62830): commit is HEAD's sha, so a tree with no HEAD (no .git, a fresh init) stamps "" and two
    such trees compare EQUAL on commit; there only the estate-code and env components bind. And it is HEAD, not the
    worktree's content, so a dirty checkout compares equal too (N-4: detection grade)."""
    if not theirs:
        return ["evidence from an UNSTAMPED report (written before plan-11908 D1), judged at "
                f"{(mine.get('commit') or '?')[:12]}: re-run enforce"]
    out = []
    for f in fields:
        a, b = theirs.get(f), mine.get(f)
        if f == "env":
            a = {k: v for k, v in (a or {}).items() if k not in VOLATILE}
            b = {k: v for k, v in (b or {}).items() if k not in VOLATILE}
            diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
            if diff:
                out.append(f"evidence from env {diff} as stamped, judged under different values of them")
        elif a != b:
            show = lambda v: (str(v)[:12] if v else "none")
            out.append(f"evidence from {f} {show(a)}, judged at {f} {show(b)}")
    return out
