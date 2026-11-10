"""Authored mutants for the shipped org backup (plan-10224 add-org-parity), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_backup.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src" / "astryx" / "pulse" / "shipped_triggers" / "org_backup.py"
ORACLE = REPO / "tests" / "test_org_backup.py"
ENV = "ORG_BACKUP_SRC"
TIMEOUT = 300

MUTANTS = {
    "O1 the HOME is inherited, not named (a pulse whose env carries no ASTRYX_HOME backs up no org's estate)":
        ('                     env={**os.environ, "ASTRYX_HOME": str(estate)},\n', ''),
    "O2 the script runs from the ESTATE, not the code tree (a cog HOME has no scripts/)":
        ('    subprocess.Popen(["bash", str(REPO / "scripts" / script)], cwd=REPO,',
         '    subprocess.Popen(["bash", str(estate / "scripts" / script)], cwd=estate,'),
    "O3 the estate is always the checkout (a cog org backs up the primary's tree)":
        ('    return paths.home() if orgs.multi() else REPO\n', '    return REPO\n'),
    "O4 the alarm names the org from the PROCESS env (a pane carrying another org's name mislabels it)":
        ('        return config.read_env(estate / ".env").get("ASTRYX_ORG") or estate.name',
         '        return os.environ.get("ASTRYX_ORG") or estate.name'),   # org-home: mutant pattern (the env-first read O4 plants, matched as data)
    "O5 the alarm names no org":
        ('f"[{_org(est)}] org backup is STALE"', '"org backup is STALE"'),
    "O6 the dump age is read from the checkout's backups/ (another org's fresh dump silences this one's alarm)":
        ('    d = estate / "backups"\n', '    d = REPO / "backups"\n'),   # org-home: a mutant's wrong root, on purpose
    "O7 the launch logs into the checkout's var/ (one log for every org)":
        ('    logd = estate / "var" / "runners"\n', '    logd = REPO / "var" / "runners"\n'),   # org-home: a mutant's wrong root
    "O8 restore-verify launches the backup script":
        ('    _launch(est, "restore-verify", "restore_verify.sh")', '    _launch(est, "restore-verify", "backup.sh")'),
}
