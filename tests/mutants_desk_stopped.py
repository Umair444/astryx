"""Mutants for triggers/steward/desk_stopped.py (seed #57179, a4's MC on #57166). The body is gitignored:
DESK_STOPPED_STAGED names a staged copy to probe before it is applied. The oracle is tests/test_desk_stopped.py."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)
SUBJECT = Path(os.environ.get("DESK_STOPPED_STAGED") or ESTATE / "triggers" / "steward" / "desk_stopped.py")
ORACLE = REPO / "tests" / "test_desk_stopped.py"
ENV = "DESK_STOPPED_SRC"
MUTANTS = {
    "S1 the laptop is not excluded (the owner using his own screen is nagged)":
        ('        if not st.get("stopped") or st.get("kind") == "laptop":',
         '        if not st.get("stopped"):'),
    "S2 a viewer doesn't restart the ladder (a fresh walk-away waits for the old band)":
        ('            s.pop("band", None)\n', ''),
    "S3 a new stop keeps the old clock and band":
        ('        if s.get("since") != since:', '        if "since" not in s:'),
    "S4 the ladder has a top rung (silent forever past 24h)":
        ("        b = _band(age, BANDS)", "        b = min(_band(age, BANDS), len(BANDS) - 1)"),
    "S5 an unknown viewer count reads as watched (an ss failure silences the guard)":
        ('        if d["viewers"]:', '        if d["viewers"] or d["viewers"] is None:'),
    "S6 a second Take over restarts the clock (the LAST stop, not the first since the resume)":
        ("    return min(after) if after else mtime", "    return max(after) if after else mtime"),
    "S7 the line goes to steward, not to the owner (the one person who can Give back)":
        ('        ctx.say("owner", body(lines), from_agent="steward")',
         '        ctx.say("steward", body(lines), from_agent="steward")'),
    "S8 a given-back desk's state is never dropped":
        ("        del state[a]", "        pass"),
    "S9 an unknown since is re-read as now each tick (the ladder never climbs)":
        ('        since = d["since"] if d["since"] is not None else s.get("since", now)',
         '        since = d["since"] if d["since"] is not None else now'),
    "S10 a down display is skipped instead of read as unwatched":
        ('                    "viewers": count(port) if port else 0})',
         '                    "viewers": count(port) if port else 1})'),
    "S11 the desk's own seat is counted as a viewer (every live desk reads watched forever)":
        ("        elif not all(seat):", "        else:"),
    "S12 the server end is counted instead of the client's (the seat can't be told apart)":
        ('f"( dport = :{int(port)} )"', 'f"( sport = :{int(port)} )"'),
    "S13 the seat is matched loosely (any python client reads as the seat)":
        ('SEAT = "hands_seat.py"', 'SEAT = "python"'),
    "S14 another stopper's flag text is dropped (a bailed runner reads as the owner's walk-away)":
        ('            by = "" if why in (None, OWNER_WHY) else', '            by = "" if True else'),
    "S15 the carried flag text keeps its brackets (an embed rides steward's embed root; a4 #57354 R1)":
        ('            flat = str(why).translate({ord("["): None, ord("]"): None})[:80]', '            flat = str(why)[:80]'),
    "S16 an unreadable client counts as a viewer (the one unknown that silenced; a4 #57354 MC)":
        ("        if not seat or None in seat:\n            unknown = True\n        elif not all(seat):",
         "        if not seat or None in seat or not all(seat):"),
}
