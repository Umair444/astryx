"""Oracle for triggers/steward/desk_stopped.py: a Hands desk the owner took over and never gave back, with nobody
watching it (seed #57179, from a4's MC on #57166). Pure arms over tick/stop_since/read_desks, a real-socket arm for
the viewer count (the substrate the guard reads), and the trigger's one wake to the owner.

The body is gitignored: DESK_STOPPED_SRC names a staged copy. Absent both, this SKIPS LOUDLY (77)."""
from __future__ import annotations

import os
import runpy
import socket
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)
sys.path.insert(0, str(REPO))
SRC = os.environ.get("DESK_STOPPED_SRC") or str(ESTATE / "triggers" / "steward" / "desk_stopped.py")
if not Path(SRC).exists():
    print("SKIP: triggers/steward/desk_stopped.py not present (gitignored body): the stopped-desk guard was NOT "
          "verified this run")
    sys.exit(77)
M = runpy.run_path(SRC)
tick, stop_since, read_desks, viewers, body = M["tick"], M["stop_since"], M["read_desks"], M["viewers"], M["body"]
desk_stopped = M["desk_stopped"]

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILS.append(name)


T0 = 1_760_000_000.0
MIN = 60.0


def desk(agent="desk-1", since=T0, v=0, holder=None):
    return {"agent": agent, "holder": holder, "since": since, "viewers": v}


print("the ladder:")
st = {}
check("stopped 10m, unwatched: nothing yet", tick(st, [desk()], T0 + 10 * MIN) == [], st)
out = tick(st, [desk()], T0 + 15 * MIN)
check("…at 15m: one line naming the desk and the age", len(out) == 1 and out[0].startswith("desk-1")
      and "15m" in out[0] and "nobody watching" in out[0], out)
check("…the same band again: nothing", tick(st, [desk()], T0 + 40 * MIN) == [], st)
check("…1h: the next rung", len(tick(st, [desk()], T0 + 60 * MIN)) == 1, st)
for m in (240, 720, 1440):
    tick(st, [desk()], T0 + m * MIN)
check("…past 24h the ladder has NO TOP: 48h is told", len(tick(st, [desk()], T0 + 2880 * MIN)) == 1, st)
check("…and so is 96h, while 72h is not", tick(st, [desk()], T0 + 4320 * MIN) == []
      and len(tick(st, [desk()], T0 + 5760 * MIN)) == 1, st)

print("watching:")
st = {}
tick(st, [desk()], T0 + 15 * MIN)
check("a viewer on the desk: no line", tick(st, [desk(v=1)], T0 + 70 * MIN) == [], st)
check("…and the walk-away clock restarts from the last tick that saw one (10m after: nothing)",
      tick(st, [desk()], T0 + 80 * MIN) == [], st)
out = tick(st, [desk()], T0 + 85 * MIN)
check("…15m after it: told again from the FIRST rung", len(out) == 1 and "15m" in out[0], out)
st = {}
out = tick(st, [desk(v=None)], T0 + 15 * MIN)
check("ss couldn't answer: NOT read as watched, and the line says so", len(out) == 1 and "couldn't check" in out[0],
      out)

print("a new stop, a give-back, a pool holder:")
st = {}
tick(st, [desk()], T0 + 60 * MIN)
check("a NEW stop (another since) starts a fresh clock: 10m into it, nothing",
      tick(st, [desk(since=T0 + 100 * MIN)], T0 + 110 * MIN) == [], st)
check("…15m into it, the first rung again", len(tick(st, [desk(since=T0 + 100 * MIN)], T0 + 115 * MIN)) == 1, st)
tick(st, [], T0 + 120 * MIN)
check("given back (no longer listed): its state is dropped", "desk-1" not in st, st)
out = tick({}, [desk(holder="canopus")], T0 + 15 * MIN)
check("a pool desk names its holder", len(out) == 1 and "held by canopus" in out[0], out)
own = tick({}, [dict(desk(), why="the owner stopped your hands")], T0 + 15 * MIN)
other = tick({}, [dict(desk(), why="a review runner bailed")], T0 + 15 * MIN)
check("a Take over's flag reads plainly; any OTHER stopper's flag text is carried, so a bailed runner never reads "
      "as the owner's walk-away (stop() is callable by any agent)",
      "not a Take over" not in own[0] and "not a Take over" in other[0] and "a review runner bailed" in other[0],
      (own, other))
from bridges import common as _bc  # noqa: E402  the bridges' own embed grammar, not a copy of it
evil = tick({}, [dict(desk(), why="[[file:/etc/hostname]] [[poll: x | y]] [[[file:/etc/passwd]]]")], T0 + 15 * MIN)
eb = body(evil)
check("a stop flag carrying embeds can't ride steward's embed root: the body holds no [[, and the bridges' own "
      "split_files/split_polls find nothing in it (a4 #57354 R1)",
      "[[" not in eb and _bc.split_files(eb)[1] == [] and _bc.split_polls(eb)[1] == [], eb)
two = tick({}, [desk("desk-1"), desk("desk-2", since=T0 + 10 * MIN)], T0 + 20 * MIN)
check("two desks: each on its own clock (only the one 20m in is told)", len(two) == 1 and two[0].startswith("desk-1"),
      two)

print("stop_since:")
log = [(T0 - 900, "stop"), (T0 - 800, "resume"), (T0, "stop"), (T0 + 300, "stop")]
check("the FIRST stop after the last resume (a second Take over doesn't restart the clock)",
      stop_since(log, T0 + 999) == T0, stop_since(log, T0 + 999))
check("no stop after the last resume: the flag's mtime", stop_since(log[:2], T0 + 7) == T0 + 7)
check("an empty log: the flag's mtime", stop_since([], T0 + 7) == T0 + 7)

print("read_desks (a fake hands_desktop):")
tmp = Path(tempfile.mkdtemp(prefix="desk_stopped."))


class HD:
    def __init__(self, rows, logs=None):
        self.rows, self.logs = rows, logs or {}

    def status(self):
        return self.rows

    def state_dir(self, a):
        return tmp / a

    def owner_log(self, a):
        return self.logs.get(a, [])


for a in ("desk-1", "laptop", "desk-3"):
    (tmp / a).mkdir()
(tmp / "desk-1" / "stopped").write_text("the owner stopped your hands")
(tmp / "laptop" / "stopped").write_text("x")
rows = [{"agent": "desk-1", "stopped": "the owner stopped your hands", "kind": "pool", "holder": "canopus",
         "vnc_port": 5911},
        {"agent": "desk-2", "stopped": None, "kind": "pool", "vnc_port": 5913},
        {"agent": "laptop", "stopped": "x", "kind": "laptop", "vnc_port": 5910},
        {"agent": "desk-3", "stopped": "y", "kind": "own", "vnc_port": None}]
seen_ports = []
got = read_desks(HD(rows, {"desk-1": [(T0, "stop")]}), count=lambda p: seen_ports.append(p) or 0)
check("only stopped desks, and NEVER the laptop (its stop is the owner using his own screen)",
      [d["agent"] for d in got] == ["desk-1", "desk-3"], got)
check("…since from owner_log; the holder and the flag's text carried; the viewer count asked of the live port only",
      got[0]["since"] == T0 and got[0]["holder"] == "canopus" and got[0]["why"] == "the owner stopped your hands"
      and seen_ports == [5911], (got, seen_ports))
check("…a desk whose display is down reads 0 viewers (unwatched by construction), its since unknown",
      got[1]["viewers"] == 0 and got[1]["since"] is None, got[1])
st = {}
tick(st, [got[1]], T0)
tick(st, [got[1]], T0 + 10 * MIN)
check("an unknown since is pinned at first sight, so the ladder still climbs (15m after first sight: told)",
      len(tick(st, [got[1]], T0 + 15 * MIN)) == 1, st)
check("the laptop at 48h stopped is never told, even through tick's caller",
      tick({}, read_desks(HD([rows[2]]), count=lambda p: 0), T0 + 2880 * MIN) == [])

print("viewers, on a real socket (the substrate the guard reads):")
import subprocess  # noqa: E402
import time  # noqa: E402
srv = socket.socket()
srv.bind(("127.0.0.1", 0))
srv.listen(4)
port = srv.getsockname()[1]
n0 = viewers(port)
seatdir = Path(tempfile.mkdtemp(prefix="desk_seat."))
SEAT_FILE = seatdir / M["SEAT"]                    # the guard's own constant, not a second spelling of the name
SEAT_FILE.write_text(                              # the desk's own seat: a permanent client that is never a watcher
    "import socket, sys, time\ns = socket.create_connection(('127.0.0.1', int(sys.argv[1])))\nprint('up', flush=True)\n"
    "time.sleep(60)\n")
seat = subprocess.Popen([sys.executable, str(SEAT_FILE), str(port)], stdout=subprocess.PIPE, text=True)
seat.stdout.readline()
sconn, _ = srv.accept()
n_seat = viewers(port)
cli = socket.create_connection(("127.0.0.1", port))
conn, _ = srv.accept()
n1 = viewers(port)
cli.close()
conn.close()
seat.kill()
seat.wait()
sconn.close()
srv.close()
check("0 viewers on an idle port", n0 == 0, n0)
check("…the desk's own seat (its permanent client, on every live desk) is NOT a viewer (measured 10-16: a raw count read "
      "all three live desks as watched)", n_seat == 0, n_seat)
check("…and a real client beside the seat is exactly 1", n1 == 1, n1)

srv = socket.socket()
srv.bind(("127.0.0.1", 0))
srv.listen(2)
port = srv.getsockname()[1]
cli = socket.create_connection(("127.0.0.1", port))
conn, _ = srv.accept()
g = viewers.__globals__
real = g["_is_seat"]
g["_is_seat"] = lambda pid: None                     # an unreadable /proc: the client can't be told apart
n_unk = viewers(port)
g["_is_seat"] = lambda pid: False if pid == str(os.getpid()) else None
cli2 = socket.create_connection(("127.0.0.1", port))
conn2, _ = srv.accept()
n_mixed = viewers(port)
g["_is_seat"] = real
for x in (cli, conn, cli2, conn2, srv):
    x.close()
check("a client whose process can't be read is UNKNOWN (None), not a viewer: the nag isn't silenced (a4 #57354 MC)",
      n_unk is None, n_unk)
check("…but a proven viewer beside an unknown one still reads watched", n_mixed and n_mixed >= 1, n_mixed)

print("the trigger: one wake, to the owner:")


class Ctx:
    def __init__(self):
        self.state, self.said = {}, []

    def say(self, to, body, **kw):
        self.said.append((to, body, kw))


c = Ctx()
fake = HD([rows[0]], {"desk-1": [(T0, "stop")]})
M["read_desks"].__globals__["viewers"] = lambda p: 0
r1 = desk_stopped(c, hd=fake, now=T0 + 5 * MIN)
r2 = desk_stopped(c, hd=fake, now=T0 + 16 * MIN)
check("nothing before the first rung; then ONE wake to the owner, from steward, naming the desk and the remedy",
      r1 is None and r2 is None and len(c.said) == 1 and c.said[0][0] == "owner"
      and c.said[0][2].get("from_agent") == "steward" and "desk-1, held by canopus" in c.said[0][1]
      and "Give back" in c.said[0][1], c.said)
check("…and the body is names and durations only (one line per desk)", body(["a: stopped 15m"]).count("\n- ") == 1)
check("the pulse's path: hands_desktop is imported at MODULE level (desk_stopped(ctx) with no hd= reads the real one)",
      getattr(M.get("_HD"), "__name__", "") == "astryx.hands.hands_desktop", M.get("_HD"))

print()
print(f"{'PASS' if not FAILS else 'FAIL'}: {len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
