"""Hermetic test of the dependency-coverage assert (nucleus/deps.py) — the plan-19
drift-catcher. Proves against a REAL temp repo that coverage:
 - catches a third-party import that is NOT in the manifest (the next faster_whisper);
 - catches it even when the import is FUNCTION-LOCAL (the AST-not-grep mandate —
   transcribe.py:33 is exactly this, and a `^import` grep misses it);
 - does NOT flag stdlib modules, nor first-party repo modules (relative or sibling),
   nor a declared third-party — all three exclusions must hold or the catcher is noise.

Run: venv/bin/python tests/test_deps.py   (also collected by pytest).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleus import deps  # noqa: E402


def _repo(files: dict) -> Path:
    d = Path(tempfile.mkdtemp()) / "repo"
    d.mkdir()
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return d


def test_undeclared_third_party_is_a_gap():
    d = _repo({"app.py": "import requests\nimport os\n"})
    gaps = deps.coverage_gaps(d, declared=set())
    assert "requests" in gaps
    assert "os" not in gaps                 # stdlib excluded


def test_function_local_import_is_caught():
    # the AST-not-grep proof: the import is indented inside a function, invisible to a
    # top-level `^import` grep — coverage must still catch it.
    body = "def load():\n    from faster_whisper import WhisperModel\n    return WhisperModel\n"
    d = _repo({"transcribe.py": body})
    assert "faster_whisper" in deps.coverage_gaps(d, declared=set())


def test_declared_third_party_is_not_a_gap():
    d = _repo({"app.py": "import requests\n"})
    assert deps.coverage_gaps(d, declared={"requests"}) == []


def test_first_party_sibling_not_a_gap():
    # bridges/whatsapp.py does `import transcribe` → resolves to bridges/transcribe.py,
    # first-party, never a dependency.
    d = _repo({"bridges/whatsapp.py": "import transcribe\nfrom common import x\n",
               "bridges/transcribe.py": "x = 1\n",
               "bridges/common.py": "x = 1\n"})
    assert deps.coverage_gaps(d, declared=set()) == []


def test_relative_import_not_a_gap():
    d = _repo({"pkg/__init__.py": "", "pkg/a.py": "from . import b\nfrom .b import y\n",
               "pkg/b.py": "y = 1\n"})
    assert deps.coverage_gaps(d, declared=set()) == []


def test_mixed_realistic():
    d = _repo({
        "nucleus/charter.py": "import sys\nfrom pathlib import Path\n",   # stdlib only
        "bridges/whatsapp.py": "import httpx\nfrom common import x\n",     # httpx third-party
        "bridges/common.py": "x = 1\n",
        "obs/main.py": "def f():\n    import numpy\n",                    # undeclared, fn-local
    })
    gaps = deps.coverage_gaps(d, declared={"httpx"})
    assert gaps == ["numpy"]               # only the undeclared third-party, fn-local caught


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  ✗ {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
