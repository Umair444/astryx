"""Hermetic test of the dependency-coverage assert (src/astryx/core/deps.py) — the plan-19
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
from astryx.core import deps  # noqa: E402


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
        "src/astryx/core/charter.py": "import sys\nfrom pathlib import Path\n",   # stdlib only
        "bridges/whatsapp.py": "import httpx\nfrom common import x\n",     # httpx third-party
        "bridges/common.py": "x = 1\n",
        "obs/main.py": "def f():\n    import numpy\n",                    # undeclared, fn-local
    })
    gaps = deps.coverage_gaps(d, declared={"httpx"})
    assert gaps == ["numpy"]               # only the undeclared third-party, fn-local caught



# ---- spec judging (0.1.2, a2 #54114/#54126): presence can't see a wrong major; unknown syntax fails closed ----
def _v(ver):
    return lambda dist: ver


def test_spec_wrong_major_is_a_problem():
    assert "does not satisfy <2" in deps.spec_problem("mcp>=1.28,<2", _v("2.3.0"))


def test_spec_in_range_is_fine():
    assert deps.spec_problem("mcp>=1.28,<2", _v("1.28.1")) is None
    assert deps.spec_problem("mcp>=1.28,<2", _v("1.30.0")) is None
    assert deps.spec_problem("sherpa-onnx==1.13.8", _v("1.13.8")) is None


def test_spec_boundary_of_the_cap():
    """the first broken release is exactly 2.0.0: `<2` must refuse it (a2 #54128 K3: `<` as `<=` let it pass)."""
    assert "does not satisfy <2" in deps.spec_problem("mcp<2", _v("2.0.0"))
    assert "does not satisfy <2" in deps.spec_problem("mcp>=1.28,<2", _v("2"))
    assert deps.spec_problem("mcp<2", _v("1.99.99")) is None


def test_spec_not_equal_judged_both_ways():
    """`!=` is a claimed operator (a2 #54128 K8: inverted, it survived 15/15)."""
    assert "does not satisfy !=1.5" in deps.spec_problem("x!=1.5", _v("1.5.0"))
    assert deps.spec_problem("x!=1.5", _v("1.6")) is None


def test_spec_below_floor_is_a_problem():
    assert "does not satisfy >=1.28" in deps.spec_problem("mcp>=1.28,<2", _v("1.27.9"))


def test_unconstrained_spec_is_judged_by_presence_only():
    assert deps.spec_problem("psycopg[binary]", _v("anything")) is None
    assert deps.spec_problem("discord.py", _v("x")) is None


def test_extras_with_a_constraint_are_judged():
    assert deps.spec_problem("uvicorn[standard]>=99", _v("0.30.1")) is not None


def test_unknown_syntax_fails_closed():
    for spec in ("x~=1.0", "x===1.0", "x>=1; python_version<'3'", "x @ https://e.x/x.whl", "x>=1.0rc1"):
        why = deps.spec_problem(spec, _v("1.0"))
        assert why and "unjudgeable" in why, (spec, why)


def test_uncomparable_installed_version_fails_closed():
    assert "can't compare" in deps.spec_problem("x>=1", _v("2.0rc1"))


def test_missing_metadata_fails_closed():
    def gone(dist):
        raise LookupError(dist)
    assert "no installed distribution metadata" in deps.spec_problem("x>=1", gone)


def test_check_cli_rejects_an_importable_mcp_2():
    """a2's shadow, end to end: an importable `mcp` whose dist-info says 2.3.0 -> `deps.py check core` rc 1, named."""
    import os
    import subprocess
    site = Path(tempfile.mkdtemp()) / "site"
    (site / "mcp").mkdir(parents=True)
    (site / "mcp" / "__init__.py").write_text("")
    (site / "mcp-2.3.0.dist-info").mkdir()
    (site / "mcp-2.3.0.dist-info" / "METADATA").write_text("Metadata-Version: 2.1\nName: mcp\nVersion: 2.3.0\n")
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, str(root / "src/astryx/core/deps.py"), "check", "core"],
                       env={**os.environ, "PYTHONPATH": str(site)}, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "mcp 2.3.0 does not satisfy <2" in r.stderr, (r.returncode, r.stderr)

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
