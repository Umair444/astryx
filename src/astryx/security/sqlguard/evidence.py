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

THE STAMP (D1) is the one header, for report.json and the ledger seed alike: commit, estate_hash, the sha256 of the
stored covering, the env and the seal. The env is every name sqlguard reads (STAMP_ENV, equal to env_census() or the
seal test is RED), stamped as {name: sha256(value)[:16] | null}, never a value (a2 BC-1 #62651: the admin DSN is one of
them). A consumer compares its own tuple to the stamp; a mismatch is NOT SEARCHED, "evidence from X, judged at Y",
never a grade. VOLATILE names are per-process identity (which dir, which gate, which run, the registry pin, a child's
libpq options): stamped, so the census still equals, but never compared.
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

STAMP_ENV = ("ASTRYX_COG_REGISTRY", "ASTRYX_FIXTURE_ADMIN_DSN", "ASTRYX_FIXTURE_TEMPLATE", "ASTRYX_SQLGUARD_DIR",
             "ASTRYX_SQLGUARD_ESTATE_SRC", "ASTRYX_SQLGUARD_GATE", "ASTRYX_SQLGUARD_ROOT", "ASTRYX_SQLGUARD_RUN",
             "PGOPTIONS")
VOLATILE = frozenset({"ASTRYX_SQLGUARD_DIR", "ASTRYX_SQLGUARD_GATE", "ASTRYX_SQLGUARD_RUN", "ASTRYX_COG_REGISTRY",
                      "PGOPTIONS"})


def env_census(pkg: Path = PKG) -> set:
    """Every env name a sqlguard module (shim included) READS by name: os.environ.get/setdefault(N), os.getenv(N),
    os.environ[N] as a load, `N in os.environ`. N is a literal, or a module-level str constant of that file. A
    whole-env copy (`os.environ.items()`, propagate's carry, rekey's GIT_ scrub) names nothing and reads no input of
    a grade, so it isn't counted."""
    names = set()
    for f in sorted(pkg.rglob("*.py")):
        tree = ast.parse(f.read_text(), str(f))
        consts = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
                  and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
                  for t in n.targets if isinstance(t, ast.Name)}

        def name(x):
            if isinstance(x, ast.Constant) and isinstance(x.value, str):
                return x.value
            return consts.get(x.id) if isinstance(x, ast.Name) else None

        is_env = lambda x: (isinstance(x, ast.Attribute) and x.attr == "environ"
                            and isinstance(x.value, ast.Name) and x.value.id == "os")
        for n in ast.walk(tree):
            got = None
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.args:
                if n.func.attr in ("get", "setdefault") and is_env(n.func.value):
                    got = name(n.args[0])
                elif n.func.attr == "getenv" and isinstance(n.func.value, ast.Name) and n.func.value.id == "os":
                    got = name(n.args[0])
            elif isinstance(n, ast.Subscript) and is_env(n.value) and isinstance(n.ctx, ast.Load):
                got = name(n.slice)
            elif isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], (ast.In, ast.NotIn)) \
                    and is_env(n.comparators[0]):
                got = name(n.left)
            if got:
                names.add(got)
    return names


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


def compare(theirs, mine, fields=("commit", "estate_hash", "env")) -> list:
    """The mismatches between a stamp a grade was judged at and the consumer's own tuple, as
    "evidence from X, judged at Y" lines. Empty = the same tuple. VOLATILE env names are never compared."""
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
