"""What the org's runtime tree is: the ONE allowlist both the wheel build (hatch_build.py) and
`astryx init` (astryx.tree) read. Only git-TRACKED files under these paths ship, so nothing gitignored
(.env, local.md, homes/, agents/<private>, triggers/, memory/) can reach a wheel or a sdist. tests/,
harness/ and docs/ are left out on purpose: they are the repo's, not an org's. Constants only; the build
hook loads this file with runpy, without importing the package.

TODO(plan-10224 S4): before the FIRST PUBLISHED build, move this from directory prefixes to a FILE-LEVEL allowlist.
A prefix ships every file a future commit adds under nucleus/, bridges/, mcp/ ... unreviewed; S4's scrub (the
personal lines, the #NNNN ids, the canopus/gemini/vega special cases) has to land first.
"""

TREE_FILES = (
    "init.sh", "astryx.py", "local.template.md", "runtime.json.example",
    "README.md", "LICENSE", "CLAUDE.md", ".gitignore",
)
TREE_DIRS = (
    "agents/", "assets/", "bridges/", "canvas/", "channel/", "hooks/", "infra/",
    "mcp/", "nucleus/", "observatory/", "scripts/", "skills/", "src/astryx/",
)
NEVER = ("tests/", "harness/", "docs/", "homes/", "triggers/", "memory/", "var/", "venv/")


def wanted(rel: str) -> bool:
    if any(rel.startswith(n) for n in NEVER):
        return False
    if "/__pycache__/" in f"/{rel}" or rel.endswith((".pyc", ".pyo")):
        return False
    return rel in TREE_FILES or rel.startswith(TREE_DIRS)
