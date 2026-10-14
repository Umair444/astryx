"""What the org's runtime tree is: the ONE allowlist both the wheel build (hatch_build.py) and
`astryx init` (astryx.tree) read. Only git-TRACKED files under these paths ship, so nothing gitignored
(.env, local.md, homes/, agents/<private>, triggers/, memory/) can reach a wheel or a sdist. tests/,
harness/ and docs/ are left out on purpose: they are the repo's, not an org's. Constants only; the build
hook loads this file with runpy, without importing the package.
"""

TREE_FILES = (
    "init.sh", "astryx.py", "local.template.md", "runtime.json.example",
    "README.md", "LICENSE", "CLAUDE.md", ".gitignore",
)
TREE_DIRS = (
    "agents/", "assets/", "bridges/", "canvas/", "channel/", "hooks/", "infra/",
    "mcp/", "nucleus/", "observatory/", "skills/", "src/astryx/",
)
NEVER = ("tests/", "harness/", "docs/", "homes/", "triggers/", "memory/", "var/", "venv/")


def wanted(rel: str) -> bool:
    if any(rel.startswith(n) for n in NEVER):
        return False
    if "/__pycache__/" in f"/{rel}" or rel.endswith((".pyc", ".pyo")):
        return False
    return rel in TREE_FILES or rel.startswith(TREE_DIRS)
