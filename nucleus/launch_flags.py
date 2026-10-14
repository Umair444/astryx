#!/usr/bin/env python3
"""astryx · launch flags: every live resident body runs with the flags the org depends on.

A resident is launched by spawn.sh with `--dangerously-load-development-channels server:astryx`
(without it the wire's doorbell is dropped silently: the MCP tools still work, so the agent looks
fine and hears nothing) and `--permission-mode bypassPermissions` (the owner's full-trust fleet;
a charter line `Permissions: relay` asks for `--permission-mode default` instead, and that is
correct for that agent, never a finding). This reads what is ACTUALLY running: the argv of the
`claude` process under each ax-<name> tmux pane, judged against that agent's charter.

CLI: python -m nucleus.launch_flags   one line per body; exit 0 EVERY body was read and is good · 1 a body
     is missing a flag · 77 not proven: tmux gave no answer, no bodies run, or any body could not be read (an
     unread body is not evidence: a pane whose claude died looks exactly like one still booting).
"""
import subprocess
import sys
from pathlib import Path

CHANNELS = "--dangerously-load-development-channels"
CHANNEL_SERVER = "server:astryx"


def _opt(argv: list[str], flag: str) -> str | None:
    """The value given to `flag` (`--flag v` or `--flag=v`), else None."""
    for i, a in enumerate(argv):
        if a == flag and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


def missing(argv: list[str], perm: str | None) -> list[str]:
    """What this body's argv lacks, given its charter's Permissions line ('' / None = the default)."""
    out = []
    chan = _opt(argv, CHANNELS)
    if chan is None or CHANNEL_SERVER not in chan.split(","):
        out.append(f"{CHANNELS} {CHANNEL_SERVER} (the wire's doorbell is dropped without it)")
    want = "default" if (perm or "").strip() == "relay" else "bypassPermissions"   # spawn.sh's exact test
    mode = _opt(argv, "--permission-mode")
    if mode != want:
        out.append(f"--permission-mode {want} (running with {mode or 'no --permission-mode'})"
                   + (" per its charter's Permissions: relay" if want == "default" else ""))
    return out


def charter_perm(name: str) -> str | None:
    from nucleus import charter
    p = charter.resolve(name)
    if p is None:
        return None
    for line in p.read_text(errors="replace").splitlines():
        if line.startswith("Permissions:"):
            return line.split(":", 1)[1].strip()
    return None


def _children(pid: int, proc: Path) -> list[int]:
    try:
        return [int(x) for x in (proc / str(pid) / "task" / str(pid) / "children").read_text().split()]
    except OSError:
        return []


def claude_argv(pane_pid: int, proc: Path = Path("/proc")) -> list[str] | None:
    """The argv of the first `claude` process under the pane (breadth-first), else None."""
    queue, seen = [pane_pid], set()
    while queue:
        pid = queue.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        try:
            argv = (proc / str(pid) / "cmdline").read_bytes().split(b"\0")
            comm = (proc / str(pid) / "comm").read_text().strip()
        except OSError:
            continue
        argv = [a.decode(errors="replace") for a in argv if a]
        if comm == "claude" or (argv and Path(argv[0]).name == "claude"):
            return argv
        queue += _children(pid, proc)
    return None


def bodies(run=subprocess.run) -> dict[str, int] | None:
    """{agent: pane pid} for every ax-<agent> tmux session; None when tmux can't answer."""
    try:
        r = run(["tmux", "list-panes", "-a", "-F", "#{session_name} #{pane_pid}"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return {} if "no server running" in r.stderr else None
    out = {}
    for line in r.stdout.splitlines():
        sess, _, pid = line.partition(" ")
        if sess.startswith("ax-") and pid.isdigit():
            out.setdefault(sess[3:], int(pid))
    return out


def main(live=None, read=claude_argv, perm=charter_perm, say=print) -> int:
    live = bodies() if live is None else live
    if live is None:
        say("launch flags: UNVERIFIED (tmux gave no answer)")
        return 77
    if not live:
        say("launch flags: no resident bodies running")
        return 77
    bad = unread = 0
    for name, pane in sorted(live.items()):
        argv = read(pane)
        if argv is None:
            say(f"  ? {name}: no claude process under its pane (booting, or its claude died)")
            unread += 1
            continue
        gaps = missing(argv, perm(name))
        if gaps:
            bad += 1
            say(f"  ✗ {name}: missing " + "; ".join(gaps)
                + f" — restart it: tmux kill-session -t =ax-{name} && nucleus/spawn.sh {name}")
        else:
            say(f"  ✓ {name}")
    say(f"launch flags: {len(live) - bad - unread}/{len(live)} verified, {bad} missing a flag, {unread} unread")
    if bad:
        return 1
    return 77 if unread else 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.exit(main())
