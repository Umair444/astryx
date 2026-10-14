"""Mutants for devtools/identity_gate.py (oracle: tests/test_identity_gate.py). Hermetic.

    venv/bin/python devtools/mutation_probe.py tests/mutants_identity_gate.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "devtools" / "identity_gate.py"
ORACLE = REPO / "tests" / "test_identity_gate.py"
ENV = "IDENTITY_GATE_SRC"
MUTANTS = {
    "K1 any installed astryx passes (the shadow check is gone)":
        ('    elif outside[0] == "path" and Path(outside[1]).resolve() != own:',
         '    elif outside[0] == "path" and False:'),
    "K2 the 'outside' reading runs from the tree root, where the shim always wins":
        ("        outside = resolve(py, Path(scratch), isolated=True, sites=sites, nosite=nosite)",
         "        outside = resolve(py, tree, isolated=False, sites=sites, nosite=nosite)"),
    "K3 a broken install reads as 'nothing installed'":
        ('    if err.endswith(ABSENT) and "ModuleNotFoundError" in err:', '    if True:'),
    "K4 the inside reading is never checked":
        ('    if inside[0] != "path":\n        probs.append(f"from the tree root, astryx.paths does not import ({inside[0]}: {inside[1]})")\n'
         '    elif Path(inside[1]).resolve() != own:\n        probs.append(f"from the tree root, astryx.paths is {inside[1]}, not this tree\'s {own}")\n',
         ''),
}
