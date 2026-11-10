"""The shipped ORG BACKUP (plan-10224 add-org-parity): the daily dump and the weekly restore-verify of the org whose
pulse runs it, as two pulse triggers (the owner's 08-21 ruling: the pulse is the org's one timer, never a unit).

  run_backup          04:00 daily     scripts/backup.sh          artifact: <estate>/backups/ newest dump, alarm at 48h
  run_restore_verify  03:00 Sunday    scripts/restore_verify.sh  artifact: <estate>/backups/.last-restore-ok, alarm 9d

The SAME names, schedules and state keys as the primary's own triggers/steward/org_runners.py, so an org that already
owns them is never given a second copy (an installer's deferential check asks trigger_names for both names). The CODE
is this checkout (the scripts, the cwd they need: ROOT=$PWD); the ESTATE is the pulse's org (its HOME in a cog of
several orgs, the checkout on one), handed to each script as ASTRYX_HOME explicitly, never inherited: backup.sh and
restore_verify.sh resolve their org's .env, database and backups/ from it. A launch is detached (it outlives the
pulse's 30 s check cap); its log is <estate>/var/runners/<name>.log. A stale artifact alarms naming the ORG (its .env's
ASTRYX_ORG), so two orgs' alarms are told apart.

Install (init.sh's orgbackup node and devtools/cog_add_org.py do, from astryx.pulse.shipped_triggers.shims):
  from astryx.pulse.shipped_triggers.org_backup import run_backup, run_restore_verify  # noqa: F401
"""
from __future__ import annotations
# imported as a module only (a trigger shim imports it), never run by path: no sys.path preamble, and no import inside
# a top-level conditional (either makes trigger_names' static reader defer every lookup). Not astryx.config either: its
# run-by-path preamble is such a conditional, so a shim importing this would read BLIND, and a blind file in an org's
# triggers/ turns every later "absent" there into "deferred" (an installer would stand down for good)
from astryx.paths import repo_root
from astryx import orgs, paths

import os
import subprocess
import time
from pathlib import Path

from astryx import trigger

REPO = repo_root(__file__)
RENAG_H = 24


def _estate() -> Path:
    """The org's estate, read at CALL time: the checkout on one org, its HOME in a cog of several orgs."""
    return paths.home() if orgs.multi() else REPO


def _org(estate: Path) -> str:
    """The org's federation name, from its .env FILE (never the process env: a pane may carry another org's). The first
    `ASTRYX_ORG=` line, read BY config.read_env (plan-10224 ENVREAD); the HOME's name if there is none."""
    from astryx import config      # at call time: trigger_names follows a shim's top-level imports, and config.py's
    try:                           # run-by-path `if` block would read as an import inside a top-level if (blind)
        return config.read_env(estate / ".env").get("ASTRYX_ORG") or estate.name
    except OSError:
        return estate.name


def _launch(estate: Path, name: str, script: str) -> None:
    logd = estate / "var" / "runners"
    logd.mkdir(parents=True, exist_ok=True)
    log = open(logd / f"{name}.log", "ab")
    log.write(f"\n--- launch {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ---\n".encode())
    subprocess.Popen(["bash", str(REPO / "scripts" / script)], cwd=REPO, stdout=log, stderr=log,
                     env={**os.environ, "ASTRYX_HOME": str(estate)},
                     start_new_session=True)      # detached: outlives the 30s check cap


def _age_h(p: Path) -> float | None:
    try:
        return (time.time() - p.stat().st_mtime) / 3600
    except OSError:
        return None


def _newest_dump_age_h(estate: Path) -> float | None:
    d = estate / "backups"
    ages = [_age_h(p) for p in d.glob("*.dump")] if d.is_dir() else []
    ages = [a for a in ages if a is not None]
    return min(ages) if ages else None


def _stale(ctx, key: str, artifact_age_h: float | None, max_age_h: float, what: str) -> str | None:
    """Standing-condition alarm: re-nags every RENAG_H while stale, re-arms on recovery."""
    if artifact_age_h is not None and artifact_age_h <= max_age_h:
        ctx.state.pop(key, None)                  # recovered: re-arm
        return None
    last = ctx.state.get(key, 0)
    if time.time() - last < RENAG_H * 3600:
        return None
    ctx.state[key] = time.time()
    seen = "never produced" if artifact_age_h is None else f"last produced {artifact_age_h:.0f}h ago"
    return (f"{what}: artifact {seen} (ceiling {max_age_h:.0f}h). The launcher fires but the job is not landing: "
            f"read var/runners/ logs and the script itself.")


@trigger("0 4 * * *", note="daily pg dump of THIS org's database into its HOME's backups/ (scripts/backup.sh, "
                           "detached); artifact-staleness alarm at 48h, naming the org")
def run_backup(ctx):
    est = _estate()
    _launch(est, "backup", "backup.sh")
    return _stale(ctx, "backup_nag", _newest_dump_age_h(est), 48, f"[{_org(est)}] org backup is STALE")


@trigger("0 3 * * 0", note="weekly restore-verify of THIS org's newest dump into a scratch database named for its "
                           "own (scripts/restore_verify.sh, detached); staleness alarm at 9d, naming the org")
def run_restore_verify(ctx):
    est = _estate()
    _launch(est, "restore-verify", "restore_verify.sh")
    return _stale(ctx, "restore_nag", _age_h(est / "backups" / ".last-restore-ok"), 9 * 24,
                  f"[{_org(est)}] restore-verify is STALE (backups may not be restorable)")
