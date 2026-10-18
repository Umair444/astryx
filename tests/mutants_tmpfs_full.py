"""Mutants for triggers/steward/tmpfs_full.py (goal 11580). The body is gitignored: TMPFS_FULL_STAGED names a staged
copy to probe before it is applied. The oracle is tests/test_tmpfs_full.py."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)
SUBJECT = Path(os.environ.get("TMPFS_FULL_STAGED") or ESTATE / "triggers" / "steward" / "tmpfs_full.py")
ORACLE = REPO / "tests" / "test_tmpfs_full.py"
ENV = "TMPFS_FULL_SRC"
MUTANTS = {
    "F1 bytes only (the 10-17 shape: inodes at 100%, bytes at 51%, silent)":
        ('        pct = max(v for v in (u["inodes"], u["bytes"], 0.0) if v is not None)',
         '        pct = u["bytes"] or 0.0'),
    "F2 the hours ladder is gone (a mount parked at 85% is told once)":
        ('        if pb > s.get("pb", -1) or hb > s.get("hb", -1):', '        if pb > s.get("pb", -1):'),
    "F3 the hours ladder has a top rung (silent forever past 24h)":
        ('        hb = _band((now - s["since"]) / 3600, HOUR_BANDS)',
         '        hb = min(_band((now - s["since"]) / 3600, HOUR_BANDS), len(HOUR_BANDS) - 1)'),
    "F4 no hysteresis (79<->81 restarts the ladder)":
        ('            if pct < LINE - HYSTERESIS:\n                s.clear()', '            s.clear()'),
    "F5 an unreadable /tmp is skipped (unknown silences)":
        ('            if mp == MUST and not s.get("unknown"):', '            if False:'),
    "F6 /tmp is read only when /proc/mounts lists it":
        ('    if MUST not in out:\n        out.append(MUST)\n', ''),
    "F7 ro mounts are read (the 1,024-inode credentials mounts trip a remedy nobody can act on)":
        ('        if len(f) < 4 or f[2] != "tmpfs" or "ro" in f[3].split(","):',
         '        if len(f) < 4 or f[2] != "tmpfs":'),
    "F8 PRIVACY: any scratchpad child is named (another project's path slug goes on the line)":
        ('                who = m.group(1) if m else k.name if HARNESS.match(k.name) else "other"',
         '                who = m.group(1) if m else k.name'),
    "F9 PRIVACY: small prefixes are named (a lone file's name goes on the line)":
        ('        big = [r for r in rows if r[1] >= MIN_SHOWN]', '        big = list(rows)'),
    "F10 a truncated walk reads as exact":
        ('                if clock() - t0 > budget:', '                if False:'),
    "F11 the mkdtemp suffix is kept (8,930 land-* dirs read as 8,930 one-dir prefixes)":
        ('    p = re.sub(r"[._-]?[A-Za-z0-9_]{8}$", "", name)       # mkdtemp\'s 8-char suffix', '    p = name'),
    "F12 no age on the line (a live run can't be told from a dead one)":
        ('            parts.append(f"    {label}: {\'>=\' if cut else \'\'}{n} inodes, oldest {h}h")',
         '            parts.append(f"    {label}: {\'>=\' if cut else \'\'}{n} inodes")'),
    "F13 the line goes to steward, not to medic (host vitals)":
        ('TO = "medic"', 'TO = "steward"'),
    "F14 a dropped mount's state is never forgotten":
        ("        del state[mp]", "        pass"),
}
