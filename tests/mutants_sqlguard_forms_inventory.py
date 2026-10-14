"""Authored mutants for src/astryx/security/sqlguard/inventory.py (plan-10107 D1/D2/D5), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_sqlguard_forms_inventory.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src/astryx/security/sqlguard/inventory.py"
ORACLE = REPO / "tests" / "test_sqlguard_forms.py"
ENV = "SQLGUARD_INVENTORY_SRC"
TIMEOUT = 600

MUTANTS = {
    "the composed-string head caller asks the statement question":
        ('                    if is_site(_head(n), form="head"):\n',
         '                    if is_site(_head(n), form="statement"):\n'),
    "the top-level assignment head caller asks the statement question":
        ('tg.id not in consts and is_site(_head(st.value), form="head"):',
         'tg.id not in consts and is_site(_head(st.value), form="statement"):'),
    "D5 back to an execute-name list (an unlisted wrapper, an AugAssign, a join read as safe; a3 BC-1)":
        ('        p = parent.get(id(n))\n        if isinstance(p, ast.Compare) or isinstance(p, ast.Dict):\n',
         '        p = parent.get(id(n))\n'
         '        return not (isinstance(p, ast.Call) and getattr(p.func, "attr", "") in ("execute", "fetch"))\n'
         '        if isinstance(p, ast.Compare) or isinstance(p, ast.Dict):\n'),
    "D5 calls every use safe":
        ('            if isinstance(pp, (ast.For, ast.AsyncFor, ast.comprehension)) and pp.iter is p:\n'
         '                return True\n        return False\n',
         '            if isinstance(pp, (ast.For, ast.AsyncFor, ast.comprehension)) and pp.iter is p:\n'
         '                return True\n        return True\n'),
    "D5 forgets a dict key/value is safe (the hands keymap goes RED)":
        ('        if isinstance(p, ast.Compare) or isinstance(p, ast.Dict):\n',
         '        if isinstance(p, ast.Compare):\n'),
    "D5's flag is never recorded":
        ('                bare_unsafe.append(getattr(n, "lineno", 0))   # maybe a composed query\'s only trace: needs a `*` row\n',
         '                pass\n'),
    "an ALIASED is_site call without form= appears (a3 BC-2: the census must see the alias)":
        ('from astryx.security.sqlguard.normalize import is_bare_verb, is_site, is_write, norm\n',
         'from astryx.security.sqlguard.normalize import is_bare_verb, is_site, is_write, norm\n'
         'from astryx.security.sqlguard.normalize import is_site as _looks\n\n\ndef _probe(t):\n    return _looks(t)\n'),
    "a raw `_SITE.match` appears outside normalize.py (a3 BC-2: it bypasses the form)":
        ('from astryx.security.sqlguard.normalize import is_bare_verb, is_site, is_write, norm\n',
         'from astryx.security.sqlguard.normalize import is_bare_verb, is_site, is_write, norm\n'
         'from astryx.security.sqlguard.normalize import _SITE\n\n\ndef _probe(t):\n    return _SITE.match(t)\n'),
    "another checkout of this repo is walked again (the estate's .claude/worktrees/ read as subjects, 10-14)":
        ("        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and d not in twins\n",
         "        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS\n"),
    "EVERY nested repo is pruned, not only this one's checkouts (agents/ would vanish silently)":
        ("twins = {d for d in dirnames if mine is not None and _common_dir(Path(dirpath) / d) == mine}",
         "twins = {d for d in dirnames if _common_dir(Path(dirpath) / d) is not None}"),
    "a pruned checkout is not declared":
        ("        OTHER_CHECKOUTS.update(", "        set().update("),
}
