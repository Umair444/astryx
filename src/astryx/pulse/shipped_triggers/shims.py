"""The live SHIMS of the shipped triggers, ONE source (plan-10224 add-org-parity): the text init.sh writes into a
one-org checkout's triggers/seed/ and devtools/cog_add_org.py writes into a cog org's HOME/triggers/seed/. Each shim
only imports its tracked module (one writer of the logic); the text is the installer's, byte for byte as init.sh's
heredocs were (init.sh at 788825e).

    python -m astryx.pulse.shipped_triggers.shims write <shim> <dir>    # writes <dir>/<shim>.py; exit 0, or 2 unknown
    python -m astryx.pulse.shipped_triggers.shims names <shim>          # the trigger names it registers, one per line

NAMES: the trigger names each shim's import registers (trigger_names' model: `from M import a` registers ALL of M's
triggers), the names an installer's deferential check asks about: if ANY is installed, the shim stands down.
"""
from __future__ import annotations
# shipped-optional: not a trigger, the shims' TEXT (one source for init.sh and cog_add_org)

import sys
from pathlib import Path

SHIMS: dict[str, str] = {
    'context_compact': '''"""Live install of the shipped context-compact trigger. The logic lives TRACKED in
src/astryx/pulse/shipped_triggers/context_compact.py (one writer; this shim only deploys it).
Installed by init.sh at founding; the org may replace it with an agent-authored one.
To retire it: `trigger_rm context_compact` (a tombstone the pulse honours). Deleting this file
does NOT retire it: init.sh would install it again."""
from astryx.pulse.shipped_triggers.context_compact import context_compact  # noqa: F401
''',
    'pr_review': '''"""Live install of the shipped pr-review trigger (one writer:
src/astryx/pulse/shipped_triggers/pr_review.py). Reviewer seat at founding is the seed; move this
file to the immune-system agent (steward) once one exists — proposer and reviewer must
never be the same mind. To retire it: `trigger_rm pr_review` (a tombstone the pulse honours).
Deleting this file does NOT retire it: init.sh would install it again."""
from astryx.pulse.shipped_triggers.pr_review import pr_review  # noqa: F401
''',
    'phone_resume_sweep': '''"""Live install of the shipped phone resume sweep (one writer: src/astryx/pulse/shipped_triggers/phone_resume_sweep.py).
Installed by init.sh where ANDROID_ENABLED=1; move it to another agent if one should own the alarm."""
from astryx.pulse.shipped_triggers.phone_resume_sweep import phone_resume_sweep  # noqa: F401
''',
    'windows_idle_stop': '''"""Live install of the shipped Windows idle stop (one writer: src/astryx/pulse/shipped_triggers/windows_idle_stop.py).
Installed by init.sh where a Windows container exists; move it to another agent if one should own it."""
from astryx.pulse.shipped_triggers.windows_idle_stop import windows_idle_stop  # noqa: F401
''',
    'agent_heal': '''"""Live install of the shipped agent heal (one writer: src/astryx/pulse/shipped_triggers/agent_heal.py). To retire it:
`trigger_rm agent_heal` (a tombstone the pulse honours). Deleting this file does NOT retire it: init.sh would reinstall."""
from astryx.pulse.shipped_triggers.agent_heal import agent_heal  # noqa: F401
''',
    'upstream_prs': '''"""Live install of the shipped upstream PR watch (one writer: src/astryx/pulse/shipped_triggers/upstream_prs.py). To retire it:
`trigger_rm upstream_prs` (a tombstone the pulse honours). Deleting this file does NOT retire it: init.sh would reinstall."""
from astryx.pulse.shipped_triggers.upstream_prs import upstream_prs  # noqa: F401
''',
    'org_backup': '''"""Live install of the shipped org backup (one writer: src/astryx/pulse/shipped_triggers/org_backup.py): the daily
dump and the weekly restore-verify of THIS org (its database, its HOME's backups/). Installed by
init.sh (one org) and devtools/cog_add_org.py (a cog org) into the seed. To retire it: `trigger_rm run_backup` and `trigger_rm
run_restore_verify` (tombstones the pulse honours). Deleting this file does NOT retire it: the reconcile would
reinstall."""
from astryx.pulse.shipped_triggers.org_backup import run_backup, run_restore_verify  # noqa: F401
''',
}

NAMES: dict[str, tuple[str, ...]] = {
    'context_compact': ('context_compact',),
    'pr_review': ('pr_review',),
    'phone_resume_sweep': ('phone_resume_sweep',),
    'windows_idle_stop': ('windows_idle_stop',),
    'agent_heal': ('agent_heal',),
    'upstream_prs': ('upstream_prs',),
    'org_backup': ('run_backup', 'run_restore_verify'),
}


def write(shim: str, d: Path) -> Path:
    p = Path(d) / f"{shim}.py"
    p.write_text(SHIMS[shim])
    return p


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] in ("write", "names") and argv[1] in SHIMS:
        if argv[0] == "names":
            print("\n".join(NAMES[argv[1]]))
            return 0
        if len(argv) == 3:
            write(argv[1], Path(argv[2]))
            return 0
    print(f"usage: shims write <shim> <dir> | shims names <shim>  (shims: {', '.join(SHIMS)})", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
