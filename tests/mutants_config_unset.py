"""Authored mutants for src/astryx/config.py's unset_env (plan-11859 U4). Every one must be CAUGHT by
tests/test_org_login.py (L9, and L6 through the API).

    venv/bin/python devtools/mutation_probe.py tests/mutants_config_unset.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "config.py"
ORACLE = REPO / "tests" / "test_org_login.py"
ENV = "CONFIG_SRC"

MUTANTS = {
    "V1 an unset removes only the first occurrence (a last-wins reader still sees the key)":
        ("        for i in reversed(hits):\n            del lines[i]\n", "        del lines[hits[0]]\n"),
    "V2 an unset of an absent key rewrites the file and says it removed something":
        ("        if not hits:\n            return False\n", ""),
    "V3 an unset writes the key empty instead of removing it (a unit's EnvironmentFile exports KEY=)":
        ("    return _write_env(key, None, path)", '    return _write_env(key, f"{key}=\\n", path)'),
}
