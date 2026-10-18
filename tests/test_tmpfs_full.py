"""Oracle for triggers/steward/tmpfs_full.py: a tmpfs filling on inodes as well as bytes (goal 11580; /tmp hit 100%
inodes at 51% bytes on 10-17, seed #59286). Pure arms over mounts/usage/tick on a fake statvfs, an attribution arm
over a fixture tree (the privacy pin: names below the top level are counted, never printed), one live arm that
asserts only shape, and the trigger's one wake to medic.

The body is gitignored: TMPFS_FULL_SRC names a staged copy. Absent both, this SKIPS LOUDLY (77)."""
from __future__ import annotations

import atexit
import os
import runpy
import shutil
import signal
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

REPO = Path(__file__).resolve().parent.parent


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)
sys.path.insert(0, str(REPO))
SRC = os.environ.get("TMPFS_FULL_SRC") or str(ESTATE / "triggers" / "steward" / "tmpfs_full.py")
if not Path(SRC).exists():
    print("SKIP: triggers/steward/tmpfs_full.py not present (gitignored body): the tmpfs guard was NOT verified this run")
    sys.exit(77)
M = runpy.run_path(SRC)
mounts, usage, tick, attribute, body, prefix = (M[k] for k in ("mounts", "usage", "tick", "attribute", "body", "prefix"))
tmpfs_full = M["tmpfs_full"]

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILS.append(name)


T0 = 1_760_000_000.0
H = 3600.0


def U(ino, byt=10.0):
    return {"inodes": ino, "bytes": byt}


def sv(files=1000, ffree=1000, blocks=1000, bfree=1000):
    return lambda mp: NS(f_files=files, f_ffree=ffree, f_blocks=blocks, f_bfree=bfree)


print("the mounts:")
PM = ("tmpfs /tmp tmpfs rw,nosuid,nodev,size=8126340k,nr_inodes=1048576 0 0\n"
      "none /run/credentials/x.service tmpfs ro,nosuid,nodev,nr_inodes=1024 0 0\n"
      "/dev/sda1 / ext4 rw,relatime 0 0\n"
      "tmpfs /dev/shm tmpfs rw,nosuid,nodev 0 0\n")
ms = mounts(PM)
check("rw tmpfs only: /tmp in, the ro credentials mount and ext4 / out", "/tmp" in ms
      and "/run/credentials/x.service" not in ms and "/" not in ms, ms)
ro = mounts(f"none {REPO} tmpfs ro,nosuid,nodev 0 0\n")         # a path this uid CAN write, mounted ro
check("an ro tmpfs is out even where this uid can write the path (ro is the rule, not W_OK)", str(REPO) not in ro, ro)
check("/tmp is read even when /proc/mounts doesn't list it (it's the mount every mkdtemp uses)",
      "/tmp" in mounts("/dev/sda1 / ext4 rw 0 0\n"), mounts("/dev/sda1 / ext4 rw 0 0\n"))

print("usage:")
check("inodes and bytes as percents", usage("/x", sv(1000, 100, 1000, 490)) == {"inodes": 90.0, "bytes": 51.0},
      usage("/x", sv(1000, 100, 1000, 490)))
check("no inode limit (f_files 0): inodes None, not 0% and not a crash", usage("/x", sv(0, 0))["inodes"] is None)


def boom(mp):
    raise OSError("gone")


check("statvfs fails: None (unknown, not empty)", usage("/x", boom) is None)

print("the percent ladder:")
st = {}
check("79%: nothing", tick(st, {"/tmp": U(79.0)}, T0) == [], st)
out = tick(st, {"/tmp": U(81.0)}, T0)
check("81% inodes: one line, naming the mount, INODES and both numbers",
      len(out) == 1 and out[0][1].startswith("/tmp: INODES at 81%") and "bytes 10.0%" in out[0][1], out)
check("…85% in the same band: nothing", tick(st, {"/tmp": U(85.0)}, T0 + 60) == [], st)
check("…91%: the next rung", len(tick(st, {"/tmp": U(91.0)}, T0 + 120)) == 1, st)
check("…bytes past the line with inodes low: told, and it says bytes",
      tick({}, {"/tmp": U(5.0, 83.0)}, T0)[0][1].startswith("/tmp: bytes at 83%"))

print("the hours ladder (a mount PARKED above the line is still told):")
st = {}
tick(st, {"/tmp": U(85.0)}, T0)
check("85% for 30m: nothing more", tick(st, {"/tmp": U(85.0)}, T0 + 0.5 * H) == [], st)
out = tick(st, {"/tmp": U(85.0)}, T0 + 1 * H)
check("…1h: told again, and the line says how long", len(out) == 1 and "for 1h" in out[0][1], out)
for h in (4, 12, 24):
    tick(st, {"/tmp": U(85.0)}, T0 + h * H)
check("…past 24h the ladder has NO TOP: 48h is told", len(tick(st, {"/tmp": U(85.0)}, T0 + 48 * H)) == 1, st)
check("…and 96h, while 72h is not", tick(st, {"/tmp": U(85.0)}, T0 + 72 * H) == []
      and len(tick(st, {"/tmp": U(85.0)}, T0 + 96 * H)) == 1, st)

print("hysteresis:")
st = {}
tick(st, {"/tmp": U(81.0)}, T0)
check("dip to 78% (inside the margin): state kept, and back at 81% is NOT a fresh line",
      tick(st, {"/tmp": U(78.0)}, T0 + 60) == [] and tick(st, {"/tmp": U(81.0)}, T0 + 120) == [], st)
tick(st, {"/tmp": U(70.0)}, T0 + 180)
check("below 75%: cleared, so the next climb is told from the first rung",
      len(tick(st, {"/tmp": U(81.0)}, T0 + 240)) == 1, st)

print("unknown never silences:")
st = {}
out = tick(st, {"/tmp": None}, T0)
check("statvfs failed on /tmp: a line that says it couldn't read", len(out) == 1 and "couldn't read" in out[0][1], out)
check("…once, not every tick", tick(st, {"/tmp": None}, T0 + 300) == [], st)
check("another mount unreadable: no line (a per-session mount may just be gone)",
      tick({}, {"/run/user/9": None}, T0) == [])
st = {"/gone": {"since": T0, "pb": 0}}
tick(st, {"/tmp": U(10.0)}, T0)
check("a mount no longer listed: its state dropped", "/gone" not in st, st)

print("attribution:")
tmp = Path(tempfile.mkdtemp(prefix="tmpfs_full."))
atexit.register(shutil.rmtree, tmp, True)           # every exit path through sys.exit; /tmp is tmpfs (goal 11580)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # a timeout's TERM exits through atexit too
for i in range(3):
    d = tmp / f"land-{i}abcdefg"
    d.mkdir()
    for j in range(5):
        (d / f"f{j}").write_text("x")
os.utime(tmp / "land-0abcdefg", (T0 - 50 * H, T0 - 50 * H))
sp = tmp / "claude-1000"
(sp / "-home-umair-astryx-homes-canopus" / "SECRETCV").mkdir(parents=True)
(sp / "-home-umair-astryx-homes-canopus" / "SECRETCV" / "offer-letter.pdf").write_text("x")
(sp / "-weird-dir").mkdir()
(sp / "bash-edit-diff" / "x").mkdir(parents=True)
(tmp / "loose.txt").write_text("x")
rows, cut = attribute(str(tmp), now=T0)
lab = {r[0]: r for r in rows}
check("mkdtemp suffixes grouped: land-* is ONE prefix with all its inodes (3 dirs + 15 files)",
      lab.get("land", (0, 0))[1] == 18, rows)
check("…biggest first", rows[0][0] == "land", rows)
check("…oldest entry's age in hours (50h: a dead run, not a live one)", lab["land"][2] == 50.0, rows)
check("the scratchpad root is split by AGENT name, and nothing deeper", "claude-1000/canopus" in lab
      and "claude-1000/other" in lab, rows)
check("…the harness's own dir is named (bash-edit-diff), a path slug is not ('-weird-dir' reads other)",
      "claude-1000/bash-edit-diff" in lab and not any("weird" in k for k in lab), rows)
text = body([("/tmp", "/tmp: INODES at 99%")], {"/tmp": (rows, cut)})
check("PRIVACY: no name below the agent level is printed (counted, never named)",
      "SECRETCV" not in text and "offer-letter" not in text and "-weird-dir" not in text, text)
check("…and the scratchpad's inodes are still counted", lab["claude-1000/canopus"][1] == 3, rows)
small = body([("/tmp", "x")], {"/tmp": ([("land", 900, 50.0), ("loose", 1, 0.0)], False)})
check("a prefix under MIN_SHOWN inodes is folded into 'everything else', never named (a lone file's name)",
      "land: 900" in small and "loose" not in small and "everything else: 1 inodes" in small, small)
tick_n = iter(range(10 ** 6))
rows2, cut2 = attribute(str(tmp), budget=2, clock=lambda: next(tick_n), now=T0)
check("a walk past its budget says so (>= on the line)", cut2 and ">=" in body([("/tmp", "x")], {"/tmp": (rows2, cut2)}),
      (rows2, cut2))
rows3, cut3 = attribute(str(tmp), clock=lambda: 100.0, now=T0, deadline=99.0)
check("a deadline already spent (an earlier mount used the tick's budget): no walk, and it says >=", cut3, (rows3, cut3))
check("prefix: a mkdtemp name loses its suffix; a plain name keeps its stem",
      prefix("sqlguard.ab_c1234") == "sqlguard" and prefix("wa-retry-x") == "wa-retry", (prefix("sqlguard.ab_c1234"),
                                                                                         prefix("wa-retry-x")))

print("live (shape only; never a threshold off the live host):")
lu = usage("/tmp")
check("statvfs on the real /tmp returns both percents in [0, 100]", lu is not None
      and all(v is None or 0 <= v <= 100 for v in lu.values()), lu)

print("the trigger:")


class Ctx:
    def __init__(self):
        self.state, self.said = {}, []

    def say(self, to, body, **kw):
        self.said.append((to, body, kw))


c = Ctx()
full = sv(1000, 10, 1000, 900)
r1 = tmpfs_full(c, proc_mounts=PM, statvfs=sv(), now=T0, attr=lambda mp, **k: ([], False))
r2 = tmpfs_full(c, proc_mounts=PM, statvfs=full, now=T0 + 300, attr=lambda mp, **k: ([("land", 900, 50.0)], False))
check("healthy: nothing; then ONE wake to medic, from steward, naming the mount, the prefix and the remedy",
      r1 is None and r2 is None and len(c.said) == 1 and c.said[0][0] == "medic"
      and c.said[0][2].get("from_agent") == "steward" and "/tmp: INODES at 99%" in c.said[0][1]
      and "land: 900 inodes, oldest 50.0h" in c.said[0][1] and "DEAD runs" in c.said[0][1], c.said)
seen = []
c3 = Ctx()
tmpfs_full(c3, proc_mounts=PM + f"tmpfs {REPO} tmpfs rw 0 0\n", statvfs=full, now=T0, attr=lambda mp, **k: (seen.append(k.get("deadline")), ([], False))[1])
check("two mounts alarmed in one tick share ONE walk deadline (N mounts walk the budget once, not N times)",
      len(seen) >= 2 and seen[0] is not None and len(set(seen)) == 1, seen)
c2 = Ctx()
tmpfs_full(c2, proc_mounts=PM, statvfs=boom, now=T0, attr=lambda mp, **k: ([], False))
check("statvfs failing everywhere: the /tmp line still goes out", len(c2.said) == 1
      and "couldn't read" in c2.said[0][1], c2.said)

print()
print(f"{'PASS' if not FAILS else 'FAIL'}: {len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
