"""Authored mutants for src/astryx/core/trigger_names.py (plan-9853 D1/D3), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_trigger_names.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src/astryx/core/trigger_names.py"
ORACLE = REPO / "tests" / "test_trigger_names.py"
ENV = "TRIGGER_NAMES_SRC"
TIMEOUT = 900

MUTANTS = {
    # the closure (a4 #49108 D1)
    "no closure: an import is not followed":
        ("    for f in files:\n        _read(f, w, out)\n    return root\n",
         "    return root\n"),
    "one hop: an imported module's own defs only, its imports not followed":
        ("    for f in files:\n        _read(f, w, out)\n    return root\n",
         "    for f in files:\n        out.names |= {n.name for n in ast.parse(f.read_text()).body\n"
         "                      if isinstance(n, ast.FunctionDef) and n.decorator_list}\n    return root\n"),
    "`from M import a` registers only a, not all of M":
        ("            root = _read_module(mod, w, out, blind, s)\n",
         "            _m = Read()\n            root = _read_module(mod, w, _m, blind, s)\n"
         "            out.names |= _m.names & {a.name for a in s.names}\n            out.blind += _m.blind\n"),
    "an alias registers the alias, not the def's name":
        ("            root = _read_module(mod, w, out, blind, s)\n",
         "            _m = Read()\n            root = _read_module(mod, w, _m, blind, s)\n"
         "            _al = {a.name: a.asname for a in s.names if a.asname}\n"
         "            out.names |= {_al.get(n, n) for n in _m.names}\n            out.blind += _m.blind\n"),
    "`from pkg import submodule` is ignored (a2 R2)":
        ("                    if a.name != \"*\" and _is_submodule(mod, a.name, root):\n",
         "                    if False:\n"),
    "the sys.path idiom isn't modelled (its dir is never searched)":
        ("                w.front.insert(0, d.resolve())\n",
         "                pass\n"),
    "an `if __name__` block is walked like any other (the main guard isn't recognised)":
        ("        if _main_guard(s):                               # never runs under discover: imported, or run as <run_path>\n"
         "            continue\n",
         ""),
    # a1 BC-1: tree.body only, unknowns → no names (each rule's own mutant)
    "an import/decorated def inside a top-level compound statement isn't blind":
        ("                blind(f\"an import or decorated def inside a top-level {type(s).__name__.lower()}\", s)\n",
         "                pass\n"),
    "a decorator other than the trigger as imported isn't blind (it's just skipped)":
        ("                    blind(f\"`@{ast.unparse(d)}` on {s.name} isn't the trigger decorator as imported\", s)\n",
         "                    pass\n"),
    "`from astryx import trigger as …` isn't blind":
        ("                            blind(\"`from astryx import trigger as …` (an alias of the decorator)\", s)\n",
         "                            pass\n"),
    "exec/importlib/__import__/runpy at top level aren't blind":
        ("            blind(\"exec/eval/compile/runpy/importlib/__import__ at top level\", s)\n",
         "            pass\n"),
    "the trigger used other than as a decorator isn't blind":
        ("            blind(\"the trigger decorator used other than as a decorator\", s)\n",
         "            pass\n"),
    "a sys.path use other than the idiom isn't blind":
        ("            blind(\"a top-level sys.path use other than `sys.path.insert(i, <a path from __file__>)`\", s)\n",
         "            pass\n"),
    "an unresolvable local import isn't blind (read as nothing)":
        ("        blind(f\"`{dotted}` doesn't resolve under {root}\", s)\n",
         "        pass\n"),
    "a relative import isn't blind":
        ("                blind(\"a relative import\", s)\n",
         "                pass\n"),
    "a file that doesn't parse isn't blind":
        ("        out.blind.append(f\"{rel}: doesn't parse ({type(e).__name__})\")\n",
         "        pass\n"),
    "a file that doesn't parse loses its own `def` names (F2)":
        ("        out.names |= set(re.findall(r\"^def\\s+([A-Za-z_]\\w*)\\s*\\(\", src, re.M))\n",
         ""),
    # the states
    "a blind file doesn't defer (a would-be-absent name reads absent)":
        ("    if blind:", "    if False:"),
    "a tombstoned copy still counts as installed":
        ("            if not retired(agent):\n",
         "            if True:\n"),
    "RETIRED under ANY agent, not the target (a3 BC-1)":
        ("    if retired(target):\n",
         "    if any((d / \".retired\" / name).exists() for d in root.iterdir()):\n"),
    "a legacy row is ignored (reads absent)":
        ("    if legacy:\n",
         "    if False:\n"),
    "any row is legacy, not only kind='python' (a2 G3)":
        ("\"SELECT agent FROM triggers WHERE kind='python' AND name=%s\"",
         "\"SELECT agent FROM triggers WHERE name=%s\""),
    "an unreadable table reads as empty (absent), not deferred":
        ("    if rows is None:\n        return \"deferred\", \"the triggers table can't be read, so a legacy row for it can't be ruled out\"\n",
         "    rows = rows or []\n"),
    "needs .env at import (a4 #49617): no DSN is a crash":
        ("    except (LookupError, OSError):\n        return None\n",
         "    except (LookupError, OSError):\n        raise\n"),
    "a blind deferral doesn't name its exit (a4 #50070)":
        ("f\"there: {'; '.join(blind[:3])}. Exit: fix or move that file (or \"",
         "f\"there: {'; '.join(blind[:3])}. (or \""),
    "a cog org's triggers are the CODE tree's, not its HOME's (S7b: lab's doctor read the primary's triggers)":
        ('        root = (paths.estate(__file__) if repo == REPO.resolve() else repo) / "triggers"',
         '        root = repo / "triggers"'),
    "a cog with no HOME carried crashes (NoHome), never defers":
        ("    except paths.NoHome as e:                  # a cog of several orgs", "    except ImportError as e:                  # a cog of several orgs"),
}
