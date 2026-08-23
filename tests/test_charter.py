"""Hermetic test of the ONE charter resolver (nucleus/charter.py) — proves the
load-bearing invariants against a REAL temp agents/ tree, every path not just the
happy one (plan-17, item d):

 - a duplicated stem RAISES Collision (the two-seed class). This is THE guard the
   observatory lacked before unification — it silently returned the first match on
   a dup stem while spawn.sh refused. One implementation now, so it can't drift; this
   test is what keeps the merged behaviour honest.
 - examples (*.example.md, any *.example/ dir) and .git are never charters.
 - a member resolves at ANY depth; the name is sanitised so it can never escape the
   tree (path-traversal in the name yields no match, not a file outside agents/).

Run: venv/bin/python tests/test_charter.py   (also collected by pytest).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleus.charter import resolve, Collision  # noqa: E402


def _mk(root: Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# charter\n")


def _tree() -> Path:
    d = Path(tempfile.mkdtemp()) / "agents"
    d.mkdir()
    _mk(d, "seed/seed.md")                 # self-form
    _mk(d, "org/canopus/canopus.md")       # member nested at depth
    _mk(d, "vega.example.md")              # shipped example — never a charter
    _mk(d, "team.example/ghost.md")        # inside an .example dir — never a charter
    _mk(d, ".git/refs/heads/fake.md")      # inside .git — never a charter
    return d


def test_self_form_resolves():
    d = _tree()
    assert resolve("seed", d) == d / "seed/seed.md"


def test_member_resolves_at_depth():
    d = _tree()
    assert resolve("canopus", d) == d / "org/canopus/canopus.md"


def test_example_file_never_charter():
    d = _tree()
    assert resolve("vega", d) is None


def test_example_dir_never_charter():
    d = _tree()
    assert resolve("ghost", d) is None


def test_git_never_charter():
    d = _tree()
    assert resolve("fake", d) is None


def test_absent_is_none():
    d = _tree()
    assert resolve("nobody", d) is None


def test_duplicated_stem_raises():
    d = _tree()
    _mk(d, "dup/dup.md")
    _mk(d, "other/dup.md")                 # same stem at two depths = corrupted registry
    try:
        resolve("dup", d)
    except Collision as e:
        assert "dup" in str(e) and "2 charters" in str(e)
    else:
        raise AssertionError("a duplicated stem must RAISE Collision, not pick one")


def test_name_cannot_escape_tree():
    d = _tree()
    # a traversal in the name sanitises to inert chars → no match, never a path escape
    assert resolve("../../../etc/passwd", d) is None
    assert resolve("", d) is None


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
