"""astryx · phone resume sweep: a RESUME of a phone's desktop near an agent's act on the owner's laptop (plan-8675 S2,
a3 #48213 C2; SHIPPED REFERENCE; one writer).

The owner's stop for a phone is the stop flag of the phone's desktop (the observatory's Hands stop button). It is
PREVENTION against the agent's phone and Hands tools. It is only DETECTION against an agent acting on Hands' "laptop"
screen: the owner's real screen, where the observatory tab may be open, so an agent can click its resume button, and no
mechanism can tell that click from his (a3 C1). This is the detector: a RESUME of a phone-* desktop within WINDOW_S of
any Hands act on the laptop (by any agent) is flagged to this trigger's agent, once.

Sources, one writer each, names and times only: nucleus/hands_desktop.owner_log(desk) (every stop/resume, any caller)
and nucleus/hands_desktop.laptop_acts() (every agent act on the laptop). A resume is judged once its +WINDOW_S has
passed, so an act just after it still counts.

Install:
  printf 'from astryx.pulse.shipped_triggers.phone_resume_sweep import phone_resume_sweep  # noqa: F401\\n' \\
      > triggers/seed/phone_resume_sweep.py
"""
from __future__ import annotations

import time

from astryx import trigger
from astryx.hands import android, hands_desktop as hd

WINDOW_S = 60


def sweep(state: dict, now: float | None = None) -> list[dict]:
    """Resumes of phone desktops, judged (their +WINDOW_S has passed) and not judged before, that had a laptop act
    within ±WINDOW_S. Advances state["through"]."""
    now = time.time() if now is None else now
    through = state.get("through", 0.0)
    ready = now - WINDOW_S
    acts = hd.laptop_acts()
    flags = []
    names = sorted(d.name for d in hd.STATE_ROOT.iterdir()) if hd.STATE_ROOT.exists() else []
    for desk in names:
        if android.avd_of_desktop(desk) is None:
            continue
        for ts, verb in hd.owner_log(desk):
            if verb != "resume" or not (through < ts <= ready):
                continue
            near = [(a_ts, act, who) for a_ts, act, who in acts if abs(a_ts - ts) <= WINDOW_S]
            if near:
                flags.append({"desktop": desk, "resume_ts": ts,
                              "agents": sorted({who for _, _, who in near}), "acts": len(near)})
    state["through"] = max(through, ready)
    return flags


def tick(state: dict, now: float | None = None) -> str | None:
    flags = sweep(state, now)
    if not flags:
        return None
    lines = [f"{f['desktop']} resumed at {time.strftime('%H:%M:%S', time.localtime(f['resume_ts']))} with "
             f"{f['acts']} Hands act(s) on the laptop by {', '.join(f['agents'])} within {WINDOW_S}s" for f in flags]
    return ("A phone's desktop was RESUMED close to an agent acting on the owner's laptop screen, so that agent may have "
            "clicked resume, not the owner (plan-8675 C2). Ask the owner whether he resumed it: " + " | ".join(lines))


@trigger("*/5 * * * *", note="phone: flag a resume of a phone desktop near an agent's act on the owner's laptop")
def phone_resume_sweep(ctx):
    return tick(ctx.state)
