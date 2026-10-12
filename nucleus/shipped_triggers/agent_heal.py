"""astryx · agent heal — a resident whose body died comes back by itself (owner 10-12: "at production level, restart
should be smooth and preferably automatic"; SHIPPED REFERENCE; one writer).

agent_dark (seed's) DETECTS a charter with no tmux body and re-nags; nothing ACTED, so a reboot whose spawn-all half
failed, or a session that crashed, stayed dead until someone ran spawn.sh by hand. This is the actuator: every minute,
each resident with no body is spawned (nucleus/spawn.sh, which resumes its session and refuses a live body, an example
or a tombstoned charter). The boot path is unchanged (astryx-residents → spawn-all.sh); this is the same act on the
pulse, the system's one clock (no second timer: the one-clock ruling).

SAFE BY CONSTRUCTION:
  · only a MISSING body is spawned; a live one is never touched (a body that's alive but deaf is a different repair,
    one that kills a session, and it stays a judged act, not this trigger's);
  · at most HEAL_PER_TICK spawns a tick, so a cold boot fills in over a few minutes rather than in one burst;
  · a CRASH LOOP stops: an agent spawned CRASH_MAX times in CRASH_WINDOW_S is left dark and reported, never retried
    forever (agent_dark keeps re-nagging it).
Who is expected to have a body is agent_dark's rule (residents by type, minus `Body: none`), read from the live tree.

Install:
  printf 'from nucleus.shipped_triggers.agent_heal import agent_heal  # noqa: F401\\n' > triggers/seed/agent_heal.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from astryx import trigger

REPO = Path(__file__).resolve().parents[2]
HEAL_PER_TICK = 4
CRASH_MAX = 3
CRASH_WINDOW_S = 1800
SPAWN_TIMEOUT_S = 90


def expected() -> list[str]:
    """Residents that should have a body: resident by type, not `Body: none`, resolvable."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import nucleus.charter as ch
    out = []
    for name in ch.roster(ch.AGENTS):
        try:
            path = ch.resolve(name, ch.AGENTS)
            if path is None or ch.agent_type(name, ch.AGENTS) != "resident":
                continue
            head = path.read_text(errors="replace")[:4000]
        except Exception:                                  # noqa: BLE001: a charter problem is charter.py's alarm
            continue
        if any(line.strip().lower() == "body: none" for line in head.splitlines()):
            continue
        out.append(name)
    return out


def bodies() -> set[str] | None:
    """Live ax-* tmux sessions, the prefix stripped. No tmux server at all (a cold boot) is the EMPTY set; None only
    when tmux itself can't answer, and then nothing is spawned (a blind healer would double-spawn)."""
    try:
        r = subprocess.run(["tmux", "ls", "-F", "#{session_name}"], capture_output=True, text=True, timeout=10)
    except Exception:                                      # noqa: BLE001
        return None
    if r.returncode != 0:
        err = (r.stderr or "").lower()
        return set() if ("no server running" in err or "error connecting" in err) else None
    return {s[3:] for s in r.stdout.split() if s.startswith("ax-")}


def spawn(name: str) -> tuple[bool, str]:
    try:
        r = subprocess.run([str(REPO / "nucleus" / "spawn.sh"), name], cwd=REPO, capture_output=True, text=True,
                           timeout=SPAWN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"spawn.sh timed out after {SPAWN_TIMEOUT_S}s"
    last = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-1:] or [""]
    return r.returncode == 0 and "refusing" not in last[0].lower(), last[0][:160]


def heal(state: dict, now: float | None = None, want=expected, have=bodies, do=spawn) -> dict:
    """One pass. Returns {healed, failed, gave_up, blind}; state["attempts"] holds each agent's recent spawn times."""
    now = time.time() if now is None else now
    out = {"healed": [], "failed": [], "gave_up": [], "blind": False}
    live = have()
    if live is None:
        out["blind"] = True
        return out
    attempts = state.setdefault("attempts", {})
    for name in sorted(set(want()) - live):
        recent = [t for t in attempts.get(name, []) if now - t < CRASH_WINDOW_S]
        attempts[name] = recent
        if len(recent) >= CRASH_MAX:
            out["gave_up"].append(name)
            continue
        if len(out["healed"]) + len(out["failed"]) >= HEAL_PER_TICK:
            break
        ok, why = do(name)
        attempts[name].append(now)
        (out["healed"] if ok else out["failed"]).append(name if ok else f"{name} ({why})")
    for name in list(attempts):                            # forget agents that stayed healthy past the window
        if not [t for t in attempts[name] if now - t < CRASH_WINDOW_S]:
            del attempts[name]
    return out


def tick(state: dict, now: float | None = None, **kw) -> str | None:
    r = heal(state, now, **kw)
    parts = []
    if r["healed"]:
        parts.append(f"respawned {len(r['healed'])} resident(s) whose body had died: {', '.join(r['healed'])}")
    if r["failed"]:
        parts.append(f"could NOT respawn: {'; '.join(r['failed'])}")
    gave = sorted(r["gave_up"])
    if gave != state.get("gave_up_said", []):             # say a crash loop once per change of the SET, not every tick
        state["gave_up_said"] = gave
        if gave:
            parts.append(f"CRASH LOOP, left dark ({CRASH_MAX} spawns in {CRASH_WINDOW_S // 60} min): {', '.join(gave)} "
                         "— read its pane / journal before spawning it again by hand")
    return ("agent_heal: " + " · ".join(parts)) if parts else None


@trigger("* * * * *", note="seed: a resident whose tmux body died is respawned (crash-loop guarded); the actuator "
                           "behind agent_dark's alarm (owner 10-12: restarts smooth and automatic)")
def agent_heal(ctx):
    return tick(ctx.state)
