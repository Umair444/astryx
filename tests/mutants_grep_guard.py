"""Authored mutants for src/astryx/security/grep_guard.py, run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_grep_guard.py

Both directions are pinned: mutants that make the guard DENY what runs the real binary or what isn't blind (noise
trains agents to route around a guard), and mutants that make it ALLOW a blind sweep (the defect it exists for).
The guard only decides; it creates and destroys nothing, so no mutant can touch shared state.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src" / "astryx" / "security" / "grep_guard.py"
ORACLE = REPO / "tests" / "test_grep_guard.py"
ENV = "GREP_GUARD_SRC"

MUTANTS = {
    "G1 `command grep` is treated as the function (the real binary denied: noise)":
        ('        if argv[0] != "grep" or not _recursive(argv[1:]):',
         '        if "grep" not in argv[:2] or not _recursive(argv[1:]):'),
    "G2 any grep counts as recursive (a non-recursive grep denied: noise)":
        ("def _recursive(args) -> bool:\n", "def _recursive(args) -> bool:\n    return True\n"),
    "G3 `cd ROOT && grep -r .` is judged from the wrong directory (a blind sweep allowed)":
        ('        if argv[0] == "cd":\n', '        if argv[0] == "cd-never":\n'),
    "G4 every directory reads blind (a subdirectory search denied: noise)":
        ("        if (p / \".gitignore\").is_file():\n            return True\n",
         "        return True\n"),
    "G5 only the TOP is checked (a parent of the repo allowed)":
        ("                if e.is_dir(follow_symlinks=False) and (Path(e.path) / \".gitignore\").is_file():",
         "                if False:"),
    "G6 unparseable fails CLOSED (a fleet-wide actuator blocks on a quoting slip)":
        ("        return None                                   # unparseable: allow (the declared polarity)",
         "        return 'unparseable'"),
    "G7 an env assignment hides the grep (`LC_ALL=C grep -r` allowed)":
        ("        while argv and _ENV.match(argv[0]):\n            argv = argv[1:]\n", ""),
    "G8 the pattern is taken for a root (no-path `grep -r kg` allowed)":
        ("    paths = operands if pattern_given else operands[1:]", "    paths = operands"),
    "G9 a combined flag cluster isn't seen as recursive (`grep -nrI` allowed)":
        ('        if re.fullmatch(r"-[A-Za-z]+", a) and ("r" in a[1:] or "R" in a[1:]):',
         '        if a in ("-r", "-R"):'),
    "G10 $HOME isn't expanded (`grep -r x $HOME/astryx` from a home allowed: a2 #41004)":
        ('    return os.path.expanduser(path.replace("${HOME}", home).replace("$HOME", home))',
         '    return os.path.expanduser(path)'),
    "G11 `-d recurse` isn't recursive (a2 #41004: function 7 vs real 47, allowed)":
        ('        if a == "-d" and i + 1 < len(args) and args[i + 1] == "recurse":', '        if False:'),
}
