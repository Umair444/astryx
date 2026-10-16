"""Authored mutants for src/astryx/security/sqlguard/normalize.py (plan-10107), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_sqlguard_forms_normalize.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src/astryx/security/sqlguard/normalize.py"
ORACLE = REPO / "tests" / "test_sqlguard_forms.py"
ENV = "SQLGUARD_NORMALIZE_SRC"
TIMEOUT = 600

MUTANTS = {
    "the statement form keeps the bare verb (the goal's defect)":
        ('    return form == "head" or not _BARE.match(t)\n',
         '    return True\n'),
    "a1's second-keyword rule instead of one token (drops `select 1` and the AGE calls)":
        ('    return form == "head" or not _BARE.match(t)\n',
         '    return form == "head" or bool(re.search(r"\\b(into|from|set|where|values|returning|as|join|using)\\b", t, re.I))\n'),
    "the head form drops the bare verb too":
        ('    return form == "head" or not _BARE.match(t)\n',
         '    return not _BARE.match(t)\n'),
    "form gets a default (a new caller inherits one)":
        ('def is_site(text: str, *, form: str) -> bool:\n',
         'def is_site(text: str, *, form: str = "statement") -> bool:\n'),
    "an unknown form is accepted":
        ('        raise ValueError(f"is_site: form must be one of {FORMS}, not {form!r}")\n',
         '        pass\n'),
    "the CLI-argv guard (?!-) is lost":
        ('_SITE = re.compile(r"^\\s*(select|insert|update|delete|with|merge)\\b(?!-)", re.I)\n',
         '_SITE = re.compile(r"^\\s*(select|insert|update|delete|with|merge)\\b", re.I)\n'),
}
