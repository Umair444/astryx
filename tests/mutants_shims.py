"""Authored mutants for the shipped triggers' shims, ONE source (plan-10224 add-org-parity), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_shims.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src" / "astryx" / "pulse" / "shipped_triggers" / "shims.py"
ORACLE = REPO / "tests" / "test_org_backup.py"
ENV = "SHIMS_SRC"
TIMEOUT = 300

# Not authored, EQUIVALENT by the pulse's own semantics: the org_backup shim importing only run_backup. `from M import a`
# registers ALL of M's triggers (pulse.discover; trigger_names models it), so both are still scheduled: no oracle can
# tell it apart, because nothing does.
MUTANTS = {
    "S2 NAMES omits run_restore_verify (an org that owns its own verify gets a second one)":
        ("    'org_backup': ('run_backup', 'run_restore_verify'),", "    'org_backup': ('run_backup',),"),
    "S3 the agent_heal shim imports another trigger":
        ("from astryx.pulse.shipped_triggers.agent_heal import agent_heal  # noqa: F401",
         "from astryx.pulse.shipped_triggers.context_compact import context_compact  # noqa: F401"),
    "S4 write() writes a file the pulse never reads (not <shim>.py)":
        ('    p = Path(d) / f"{shim}.py"', '    p = Path(d) / f"{shim}.txt"'),
}
