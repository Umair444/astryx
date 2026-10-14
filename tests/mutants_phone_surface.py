"""Authored mutants for mcp/phone/surface.py (plan-8675 S1), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_phone_surface.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "mcp/phone/surface.py"
ORACLE = REPO / "tests" / "test_phone_facade.py"
ENV = "PHONE_SURFACE_SRC"
TIMEOUT = 120

MUTANTS = {
    "an unlisted visible window doesn't taint":
        ('"personal" if unlisted or not visible else "org"',
         '"personal" if not visible else "org"'),
    'nothing visible reads as public':
        ('"personal" if unlisted or not visible else "org"',
         '"personal" if unlisted else "org"'),
    'a block with no isVisible line counts as hidden':
        ('            w["visible"] = True\n',
         '            w["visible"] = False\n'),
    'titles match as substrings':
        ('r["title"].fullmatch(w["title"])',
         'r["title"].search(w["title"])'),
    "the owning package isn't checked":
        ('w["package"] == r["package"] and r["title"]',
         'r["title"]'),
    'combine trusts the LAST reading only':
        ('    org = bool(stamps) and all(s.get("tier") == "org" for s in stamps) and not foreign\n',
         '    org = bool(stamps) and stamps[-1].get("tier") == "org" and not foreign\n'),
    'element ids are ignored':
        ('    foreign = sorted(element_packages(content) - public_pkgs)\n', '    foreign = []\n'),
    'no readings reads as org':
        ('    org = bool(stamps) and all(', '    org = all('),
}
