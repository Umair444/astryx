"""Authored mutants for src/astryx/core/charter.py's GROUPS (plan-11324 S3d), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_groups_charter.py

Each is a plausible wrong group rule: a self-folder read as a group, a nested group's members not rolled up, every
member read as direct, the parent lost, an example tree counted, an unsorted (order-dependent) answer.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src" / "astryx" / "core" / "charter.py"
ORACLE = REPO / "tests" / "test_groups.py"
ENV = "CHARTER_SRC"
TIMEOUT = 60

MUTANTS = {
    "G1 a self-folder is a group (the agent's home read as a composite)":
        ("    if len(parts) >= 2 and parts[-2] == charter_path.stem:     # self-folder: the agent's home drops out\n"
         "        parts = parts[:-1]\n", ""),
    "G2 a nested group's members don't roll up to its parent (members = direct)":
        ("            g[\"members\"].append(p.stem)\n            if i == len(chain) - 1:\n                g[\"direct\"].append(p.stem)\n",
         "            if i == len(chain) - 1:\n                g[\"members\"].append(p.stem)\n                g[\"direct\"].append(p.stem)\n"),
    "G3 every member is direct":
        ("            if i == len(chain) - 1:\n                g[\"direct\"].append(p.stem)\n",
         "            g[\"direct\"].append(p.stem)\n"),
    "G4 a nested group's parent is lost (every group hangs off the org)":
        ("\"parent\": \"/\".join(chain[:i]) or None", "\"parent\": None"),
    "G5 a group is keyed by its own name, not its path (team/sub collides with any other sub)":
        ("            gid = \"/\".join(chain[:i + 1])\n", "            gid = chain[i]\n"),
    "G6 the examples are counted (charter_files skipped for a raw rglob)":
        ("    for p in charter_files(agents_dir):\n        chain = group_path(p, agents_dir)\n",
         "    for p in sorted(agents_dir.rglob(\"*.md\")):\n        chain = group_path(p, agents_dir)\n"),
    "G7 the CLI ignores the agents/ dir it is given":
        ("groups(Path(sys.argv[2]) if len(sys.argv) == 3 else AGENTS)", "groups(AGENTS)"),
}
