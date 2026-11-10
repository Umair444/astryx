"""Authored mutants for devtools/org_census.py (plan-11324 S3a; a2 #58917 R-1/R-2), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_census.py

Each restores a census that UNDER-reads: the walk a hand-kept list of roots again (R-1), the org's gitignored estate
read as the core's code, and the two shell forms vitals.sh carried (a quoted command substitution, a `:-` default).
The oracle loads the census from ORG_CENSUS_SRC.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "devtools/org_census.py"
ORACLE = REPO / "tests" / "test_org_home_census.py"
TIMEOUT = 900   # the census walks the whole tree (~95 s on this host), and the oracle runs it once plus per-file arms
ENV = "ORG_CENSUS_SRC"

MUTANTS = {
    "W1 the walk is a hand-kept list of roots again (a2 R-1: skills/, harness/ unread)":
        ('    files = keep if keep is not None else {p for p in root.rglob("*")}\n',
         '    files = {p for p in (keep if keep is not None else root.rglob("*")) if p.relative_to(root).parts[0] in\n'
         '             ("src", "mcp", "devtools", "scripts", "channel", "bridges", "hooks", "observatory", "canvas",\n'
         '              "tests", "init.sh")}\n'),
    "W2 the org's gitignored estate is read as the core's code (merge_check's linked tree)":
        ("    keep = _not_ignored(root)\n", "    keep = None\n"),
    "G1 a quoted command substitution is stripped as a label (vitals.sh:147)":
        (' and not re.search(r"\\$\\(|`", m.group())', ""),
    "G2 a `:-` default is not a lead (vitals.sh:87)":
        ('|:-)(?:\\./)?"""', ')(?:\\./)?"""'),
    "N1 python's argv kind is not read":
        ('        for n in _py_tmux(src):\n',
         '        for n in []:\n'),
    'N2 org_tmux.sh routes calls made BEFORE it is sourced':
        ('sourced_at is not None and sourced_at < n:',
         'sourced_at is not None:'),
    'N3 `exec tmux` is routed by the function it bypasses':
        ('            if not m.group("pre") and sourced_at',
         '            if sourced_at'),
    'N4 .ts is not read again (a2 #59037)':
        (', ".cjs", ".ts")   # .cjs/.ts',
         ', ".cjs")   # .cjs/.ts'),
    "N5 python's unit-name kind is not read":
        ('        for n in ([] if rel.startswith("tests/") else _py_unit(src)):',
         '        for n in []:'),
    "N6 shell's unit-name kind is not read":
        ('        if UNIT_NAME.search(bare) and not rel.startswith("tests/"):',
         '        if False:'),
    "N7 a guard that SERVES a cog is exempt like one that refuses (its checkout reads run for another org: a2 #60858)":
        ('        sv = g and serves(lines)\n', '        sv = False\n'),
    "N8 every site of a serving file is exempt (not only those relative to the org's HOME)":
        ('                    (res["guarded"] if ORGH_REL.search(sh_code(raw)) else res[kind]).append(row)',
         '                    res["guarded"].append(row)'),
    "N9 the $ORGH exemption reads the RAW line, so `$ORGH` in a trailing comment exempts a checkout read (a2 #60989 A-1)":
        ('ORGH_REL.search(sh_code(raw))', 'ORGH_REL.search(raw)'),
    "G1a a serving region is ignored (init.sh's doctor body judged by no gate again: a2 #61513)":
        ("                elif sv or any(a <= n <= b for a, b in regions):", "                elif sv:"),
    "G1b a region serves the WHOLE file (init.sh's refusing setup verbs read as serving)":
        ("                elif sv or any(a <= n <= b for a, b in regions):", "                elif sv or bool(regions):"),
    "G1c an unclosed region is dropped (it judges less, never more)":
        ("    if start is not None:\n        out.append((start, 10 ** 9))\n", ""),
    "G1d a unit file's Description= line is read as a path":
        ('|^\\s*Description=""", code)), None)', '""", code)), None)'),
    "G2a no alias is a base (a python read through `repo = repo or REPO` unseen again: trigger_names' miss)":
        ('estate_sites(rel, lines, toks, cd_base, base_aliases(src))', 'estate_sites(rel, lines, toks, cd_base)'),
    "G2b a parameter's BASE default makes no alias (`def f(repo=REPO)`)":
        ("            for arg, d in zip(pos[len(pos) - len(a.defaults):], a.defaults):\n                if base.search(seg(d)):\n"
         "                    out.add(arg.arg)\n", ""),
    "G2c an assignment from a BASE makes no alias (`base = REPO`, `root = root or REPO`)":
        ("                if isinstance(tg, ast.Name):\n                    out.add(tg.id)\n", "                pass\n"),
}
