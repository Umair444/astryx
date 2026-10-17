"""astryx · agent heal — a resident whose body died comes back by itself (owner 10-12: "at production level, restart
should be smooth and preferably automatic"; SHIPPED REFERENCE; one writer).

agent_dark (seed's) DETECTS a charter with no tmux body and re-nags; nothing ACTED, so a reboot whose spawn-all half
failed, or a session that crashed, stayed dead until someone ran spawn.sh by hand. This is the actuator: every minute,
each resident with no body is spawned (scripts/spawn.sh, which resumes its session and refuses a live body, an example
or a tombstoned charter). The boot path is unchanged (astryx-residents → spawn-all.sh); this is the same act on the
pulse, the system's one clock (no second timer: the one-clock ruling).

ARM TWO, a DEAF body (steward #50608 at seed #50607; 10-12: seed's own `deploy.sh residents` killed every ear, its
own too, and nothing restarts the hub, so seed sat deaf ~2h with owner WhatsApp turns pending): a resident whose
tmux body is alive but has NO ear (no channel/server.mjs process carrying ASTRYX_AGENT=<it> in /proc/<pid>/environ;
argv can name anyone, the environ is the ear's identity) AND has local rows pending past DEAF_PENDING_S AND whose
pane is IDLE ("done <time>" above an empty prompt, no "esc to interrupt") is restarted: its pane is captured to
homes/<it>/.deaf-<utc>.pane (0600; DOT-named, so embed_root refuses it as a [[file:]] to every
audience: a pane can show tier content, steward MC-1 #50610) FIRST, then kill-session, then spawn() as arm one does, and the next ticks report
its ears and the pending rows draining. A BUSY pane is never killed: it is reported and re-checked every tick. A
dead ear with nothing pending is idle, not deaf, and silent.

SAFE BY CONSTRUCTION:
  · only a MISSING body is spawned, and only a DEAF + IDLE one is killed; a live ear, an empty inbox or a turn in
    flight is never touched;
  · a session younger than DEAF_GRACE_S, or one this trigger (re)spawned that recently, is still bringing its ear up
    and is left alone;
  · at most HEAL_PER_TICK spawns a tick (both arms together), so a cold boot fills in over a few minutes rather than in one burst;
  · a CRASH LOOP stops: an agent spawned CRASH_MAX times in CRASH_WINDOW_S (by either arm: one count) is left dark
    or deaf and reported, never retried forever (agent_dark keeps re-nagging a dark one).
Who is expected to have a body is agent_dark's rule (residents by type, minus `Body: none`), read from the live tree.

Install:
  printf 'from astryx.pulse.shipped_triggers.agent_heal import agent_heal  # noqa: F401\\n' > triggers/seed/agent_heal.py
"""
from __future__ import annotations
# imported as a module only (a trigger shim imports it), never run by path, so no sys.path preamble: an import
# inside a top-level conditional makes the trigger_names static reader defer every lookup (reorg 10-14)
from astryx.paths import repo_root
from astryx import config, paths  # noqa: E402

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from astryx import trigger

REPO = repo_root(__file__)


def _estate():
    """The org's estate, read at CALL time: REPO on one org (exactly what it was, an oracle's `H.REPO = tmp` rebinding
    included: save() then writes the tmp tree, never the live homes/), the HOME on a multi-org host (plan-11324 S3a)."""
    from astryx import orgs
    return paths.home() if orgs.multi() else REPO


HEAL_PER_TICK = 4
CRASH_MAX = 3
CRASH_WINDOW_S = 1800
DEAF_PENDING_S = 300        # rows to it pending this long, with no ear, is deaf (a brief MCP restart doesn't age them)
DEAF_GRACE_S = 300          # a body this young is still bringing its ear up
IDLE_TAIL = 12              # the pane's last non-blank lines that decide IDLE
DONE = re.compile(r"\bdone \d{1,2}:\d{2}")


def expected() -> list[str]:
    """Residents that should have a body: resident by type, not `Body: none`, resolvable."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import astryx.core.charter as ch
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


def spawn(name: str, script: Path | None = None) -> tuple[bool, str]:
    """LAUNCH spawn.sh detached and return at once: a boot waits up to a minute on its dialogs, and pulse kills any check
    past 30s, taking this tick's crash-loop count with it (10-14: 4 spawns a tick timed out every tick). A launch that
    dies leaves no body; the next tick sees that and the crash-loop guard counts it. Its output is in the log named."""
    log = _estate() / "var" / "agent_heal" / f"{name}.spawn.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "wb") as f:
            subprocess.Popen([str(script or REPO / "scripts" / "spawn.sh"), name], cwd=REPO, stdin=subprocess.DEVNULL,
                             stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:
        return False, f"spawn.sh could not start: {e}"[:160]
    return True, str(log.relative_to(REPO))


def heal(state: dict, now: float | None = None, want=None, have=None, do=None) -> dict:
    """One pass. Returns {healed, failed, gave_up, blind}; state["attempts"] holds each agent's recent spawn times."""
    now = time.time() if now is None else now
    want, have, do = want or expected, have or bodies, do or spawn
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


def ears(proc: str = "/proc") -> dict[str, int] | None:
    """Live ears by agent: channel/server.mjs processes counted by the ASTRYX_AGENT in their ENVIRON (argv can name
    anyone). Read here, never with tr/cat (an environ holds secrets). None when /proc can't be listed."""
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return None
    out: dict[str, int] = {}
    for pid in pids:
        try:
            if not any(a.endswith(b"channel/server.mjs") for a in Path(proc, pid, "cmdline").read_bytes().split(b"\0")):
                continue
            env = Path(proc, pid, "environ").read_bytes().split(b"\0")
        except OSError:                                    # gone, or not ours to read
            continue
        for kv in env:
            if kv.startswith(b"ASTRYX_AGENT="):
                name = kv.split(b"=", 1)[1].decode(errors="replace")
                out[name] = out.get(name, 0) + 1
    return out


def _dsn() -> str:
    try:
        return config.dsn(_estate() / ".env")
    except LookupError:
        return ""


def stale(min_age: int = DEAF_PENDING_S, dsn: str | None = None) -> dict[str, tuple[int, int]] | None:
    """Local rows still pending past min_age: agent -> (count, oldest age in s). None when the table can't be read
    (then nothing is killed: a blind arm never cuts)."""
    try:
        import psycopg
        with psycopg.connect(dsn or _dsn(), connect_timeout=5) as c:
            rows = c.execute("SELECT to_agent, count(*), extract(epoch FROM now() - min(ts))::int FROM messages "
                             "WHERE status = 'pending' AND coalesce(to_org, 'local') = 'local' "
                             "AND ts < now() - make_interval(secs => %s) GROUP BY to_agent", (min_age,)).fetchall()
    except Exception:                                      # noqa: BLE001
        return None
    return {r[0]: (int(r[1]), int(r[2])) for r in rows}


def pane(name: str) -> tuple[str, float] | None:
    """(the pane's text, the session's age in s), or None when there is no body or tmux can't say."""
    try:
        t = subprocess.run(["tmux", "capture-pane", "-p", "-S", "-400", "-t", f"=ax-{name}:"],
                           capture_output=True, text=True, timeout=10)
        b = subprocess.run(["tmux", "display-message", "-p", "-t", f"=ax-{name}:", "#{session_created}"],
                           capture_output=True, text=True, timeout=10)
        born = int(b.stdout.strip())
    except Exception:                                      # noqa: BLE001
        return None
    return (t.stdout, time.time() - born) if t.returncode == 0 and b.returncode == 0 else None


def idle(text: str) -> bool:
    """Between turns: "done <time>" above an EMPTY prompt, and no "esc to interrupt" (a turn in flight). Anything
    else (a turn, a dialog, typed text, an unreadable pane) is NOT idle, and a pane that isn't idle is never cut."""
    lines = [ln for ln in text.splitlines() if ln.strip()][-IDLE_TAIL:]
    if any("esc to interrupt" in ln for ln in lines):
        return False
    prompts = [i for i, ln in enumerate(lines) if ln.lstrip().startswith("❯")]
    if not prompts or lines[prompts[-1]].lstrip()[1:].strip():
        return False
    return any(DONE.search(ln) for ln in lines[:prompts[-1]])


def pane_file(name: str, now: float) -> Path:
    """Where a deaf body's pane is kept: its own (gitignored) home, DOT-named so no [[file:]] embed can carry it to any
    surface (bridges/embed_root refuses every dot-path under a home; a pane can show tier content, steward MC-1)."""
    return _estate() / "homes" / name / f".deaf-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(now))}.pane"


def save(name: str, text: str, now: float) -> Path:
    """The pane, captured BEFORE the kill, 0600 at pane_file()."""
    f = pane_file(name, now)
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    return f


def kill(name: str) -> bool:
    try:
        return subprocess.run(["tmux", "kill-session", "-t", f"=ax-{name}"], capture_output=True,
                              timeout=10).returncode == 0
    except Exception:                                      # noqa: BLE001
        return False


def deaf(state: dict, now: float, budget: int, want=None, listen=None, late=None, look=None, cut=None, do=None,
         keep=None) -> dict:
    """Arm two, one pass. Returns {restarted, failed, busy, gave_up, verified, blind}; restarts share
    state["attempts"] (one crash-loop count with arm one) and are verified on later ticks via state["verify"]."""
    out = {"restarted": [], "failed": [], "busy": [], "gave_up": [], "verified": [], "blind": False}
    want, do, look, cut, keep = want or expected, do or spawn, look or pane, cut or kill, keep or save
    heard, queued = (listen or ears)(), (late or stale)()
    if heard is None or queued is None:
        out["blind"] = True
        return out
    attempts, verify = state.setdefault("attempts", {}), state.setdefault("verify", {})
    for name in sorted(verify):                            # a restart is proven by its ear and its drained inbox
        v, n_ears, left = verify[name], heard.get(name, 0), queued.get(name, (0, 0))[0]
        if (n_ears and not left) or now - v["at"] >= DEAF_GRACE_S:
            out["verified"].append((name, n_ears, v["pending"], left))
            del verify[name]
    for name in sorted(set(want()) & set(queued)):
        if heard.get(name) or name in verify:
            continue
        recent = [t for t in attempts.get(name, []) if now - t < CRASH_WINDOW_S]
        if recent and now - recent[-1] < DEAF_GRACE_S:     # we just (re)spawned it: its ear is still coming up
            continue
        if len(recent) >= CRASH_MAX:
            out["gave_up"].append(name)
            continue
        seen = look(name)
        if seen is None:                                   # no body at all: arm one's case
            continue
        text, age = seen
        if age < DEAF_GRACE_S:                             # someone just started it
            continue
        n, oldest = queued[name]
        what = f"{n} pending, oldest {oldest // 60} min"
        if not idle(text):
            out["busy"].append(f"{name} ({what})")
            continue
        if len(out["restarted"]) + len(out["failed"]) >= budget:
            break
        path = keep(name, text, now)
        attempts[name] = recent + [now]
        if not cut(name):
            out["failed"].append(f"{name} (kill-session failed; pane saved to {path})")
            continue
        ok, why = do(name)
        if ok:
            out["restarted"].append(f"{name} ({what}; pane saved to {path})")
            verify[name] = {"at": now, "pending": n}
        else:
            out["failed"].append(f"{name} (killed, then spawn failed: {why}; pane saved to {path})")
    return out


def tick(state: dict, now: float | None = None, deaf_kw: dict | None = None, **kw) -> str | None:
    """Arm one, then (when deaf_kw is given: the trigger passes {}, a hermetic arm-one test passes nothing) arm two."""
    now = time.time() if now is None else now
    r = heal(state, now, **kw)
    if deaf_kw is not None:
        d = deaf(state, now, HEAL_PER_TICK - len(r["healed"]) - len(r["failed"]),
                 **{k: v for k, v in kw.items() if k in ("want", "do")}, **deaf_kw)
        r["gave_up"] = r["gave_up"] + d["gave_up"]
    else:
        d = {"restarted": [], "failed": [], "busy": [], "verified": []}
    parts = []
    if r["healed"]:
        parts.append(f"spawn launched for {len(r['healed'])} resident(s) whose body had died: {', '.join(r['healed'])} "
                     "(a launch that fails shows as dark next tick; output in var/agent_heal/<name>.spawn.log)")
    if r["failed"]:
        parts.append(f"could NOT respawn: {'; '.join(r['failed'])}")
    if d["restarted"]:
        parts.append(f"restarted {len(d['restarted'])} DEAF resident(s) (body alive, no ear, rows pending, pane idle): "
                     + "; ".join(d["restarted"]))
    if d["failed"]:
        parts.append(f"could NOT restart deaf: {'; '.join(d['failed'])}")
    for name, n_ears, before, left in d["verified"]:
        parts.append(f"{name} after restart: {n_ears} ear(s), aged pending {before} -> {left}"
                     + ("" if n_ears == 1 and not left else " — NOT healed, read its saved pane"))
    busy = sorted(d["busy"])
    if [b.split(" (")[0] for b in busy] != state.get("busy_said", []):   # once per change of the SET
        state["busy_said"] = [b.split(" (")[0] for b in busy]
        if busy:
            parts.append(f"DEAF but mid-turn, NOT killed (re-checked every tick): {'; '.join(busy)}")
    gave = sorted(set(r["gave_up"]))
    if gave != state.get("gave_up_said", []):             # say a crash loop once per change of the SET, not every tick
        state["gave_up_said"] = gave
        if gave:
            parts.append(f"CRASH LOOP, left dark or deaf ({CRASH_MAX} spawns in {CRASH_WINDOW_S // 60} min): {', '.join(gave)} "
                         "— read its pane / journal before spawning it again by hand")
    return ("agent_heal: " + " · ".join(parts)) if parts else None


@trigger("* * * * *", note="seed: a resident whose tmux body died is respawned, and one alive but DEAF (no ear, rows "
                           "pending, pane idle) is captured, killed and respawned (crash-loop guarded); the actuator "
                           "behind agent_dark's alarm (owner 10-12: restarts smooth and automatic)")
def agent_heal(ctx):
    return tick(ctx.state, deaf_kw={})
