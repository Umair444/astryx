"""Authored mutants for src/astryx/paths.py (seed #53453, a4 #53469), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_checkouts.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src/astryx/paths.py"
ORACLE = REPO / "tests" / "test_checkouts.py"
ENV = "CHECKOUTS_SRC"

MUTANTS = {
    "EVERY nested repo is another checkout (agents/ would vanish from every scanner)":
        ("        return common_dir(d) in self.mine\n", "        return common_dir(d) is not None\n"),
    "an UNKNOWN source prunes every nested repo instead of saying so":
        ("        if self.unknown or d.resolve() == self.root:\n            return False\n",
         "        if self.unknown:\n            return common_dir(d) is not None\n        if d.resolve() == self.root:\n"
         "            return False\n"),
    "the declared source (ASTRYX_REPO_COMMON) is ignored: an archive tree stays UNKNOWN":
        ("        declared = env.get(CHECKOUT_SOURCE_ENV)\n", "        declared = None\n"),
    "the pointer's text is not read when the admin dir is unreadable (the sandbox case)":
        ('            if admin.parent.name == "worktrees":\n', '            if False:\n'),
    "the tree itself counts as another checkout":
        ("        if self.unknown or d.resolve() == self.root:\n", "        if self.unknown:\n"),
    "an empty dir holds only other checkouts":
        ("        return bool(entries) and all(", "        return all("),
    "a pruned checkout is not recorded for the report":
        ("                self.found.add(os.path.relpath(full, self.root))\n", "                pass\n"),
    "the UNKNOWN report doesn't say so":
        ('            return (f"other checkouts: UNKNOWN', '            return (f"other checkouts: none'),
    "a nested checkout met while UNKNOWN is walked silently (not named)":
        ("                if self.unknown and (full / \".git\").exists():\n", "                if False:\n"),
    "holds_only_others looks one level down only (.claude/ -> worktrees/ -> checkout reads as authored)":
        ("e.is_dir() and not e.is_symlink() and self.holds_only_others(e, depth - 1)", "e.is_dir() and self.is_other(e)"),
}
