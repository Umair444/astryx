#!/usr/bin/env python3
"""test_launch_flags — a resident body missing the wire's channel flag or its charter's permission mode is
named (owner 10-14: "astryx works with bypass permission and --dangerously-load-development-channels; make sure the
check is there"). Hermetic: argv fixtures and a fake /proc tree; no tmux, no live body is read."""
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from nucleus import launch_flags as L  # noqa: E402

fails = 0


def arm(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails += 1


FULL = ["claude", "--resume", "x", "--model", "opus", "--permission-mode", "bypassPermissions",
        "--disallowedTools", "AskUserQuestion", "--strict-mcp-config", "--mcp-config", "/h/.mcp.json",
        "--dangerously-load-development-channels", "server:astryx"]


def without(argv, flag):
    i = argv.index(flag)
    return argv[:i] + argv[i + 2:]


def swap(argv, flag, value):
    i = argv.index(flag)
    return argv[:i + 1] + [value] + argv[i + 2:]


arm("spawn.sh's own argv is clean", L.missing(FULL, None) == [], L.missing(FULL, None))
m = L.missing(without(FULL, "--dangerously-load-development-channels"), None)
arm("no channels flag → named (the doorbell is dropped)", len(m) == 1 and "server:astryx" in m[0], m)
m = L.missing(swap(FULL, "--dangerously-load-development-channels", "server:other"), None)
arm("the channels flag without server:astryx → named", len(m) == 1 and "server:astryx" in m[0], m)
arm("server:astryx among several channels → clean",
    L.missing(swap(FULL, "--dangerously-load-development-channels", "plugin:x@y,server:astryx"), None) == [])
m = L.missing(without(FULL, "--permission-mode"), None)
arm("no --permission-mode → named (an absent flag inherits user settings)", len(m) == 1 and "bypassPermissions" in m[0], m)
m = L.missing(swap(FULL, "--permission-mode", "default"), None)
arm("a default-mode body whose charter is NOT relay → named", len(m) == 1 and "bypassPermissions" in m[0], m)
relay = swap(FULL, "--permission-mode", "default")
arm("a `Permissions: relay` charter running --permission-mode default → clean (never a finding)",
    L.missing(relay, "relay") == [], L.missing(relay, "relay"))
m = L.missing(FULL, "relay")
arm("a relay charter running WITH bypass → named", len(m) == 1 and "relay" in m[0], m)
arm("`Permissions: Relay` (not spawn.sh's exact 'relay') expects bypass, as spawn.sh launches it (N1)",
    L.missing(FULL, "Relay") == [], L.missing(FULL, "Relay"))
arm("--flag=value form is read", L.missing(["claude", "--permission-mode=bypassPermissions",
                                            "--dangerously-load-development-channels=server:astryx"], None) == [])

with tempfile.TemporaryDirectory() as d:          # a fake /proc: bash(10) → claude(11) → node(12)
    proc = Path(d)
    for pid, comm, argv, kids in ((10, "bash", ["-bash"], [11]), (11, "claude", FULL, [12]),
                                  (12, "node", ["node", "server.mjs"], [])):
        (proc / str(pid) / "task" / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "comm").write_text(comm + "\n")
        (proc / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (proc / str(pid) / "task" / str(pid) / "children").write_text(" ".join(map(str, kids)))
    arm("the claude process under a pane is found through its children", L.claude_argv(10, proc) == FULL,
        L.claude_argv(10, proc))
    (proc / "11" / "comm").write_text("bash\n")
    (proc / "11" / "cmdline").write_bytes(b"bash\0")
    arm("no claude under the pane → None (never a guessed verdict)", L.claude_argv(10, proc) is None)


# ── main(): every exit code, and what it says (a2 #51503 B1/B2) ──────────────────────────
BAD = without(FULL, "--dangerously-load-development-channels")


def run_main(live, argvs, perms=None):
    lines = []
    rc = L.main(live=live, read=lambda pane: argvs.get(pane), perm=lambda n: (perms or {}).get(n), say=lines.append)
    return rc, lines


rc, out = run_main({"a": 1, "b": 2}, {1: FULL, 2: FULL})
arm("every body read and clean → rc 0, each named ✓", rc == 0 and sum("✓" in x for x in out) == 2, (rc, out))
rc, out = run_main({"a": 1, "b": 2}, {1: FULL, 2: BAD})
arm("one body missing a flag → rc 1 with a ✗ line naming it", rc == 1 and any(x.startswith("  ✗ b:") for x in out), (rc, out))
rc, out = run_main({"a": 1, "b": 2}, {1: FULL})
arm("16 ✓ + 1 unread is NOT 'every': rc 77, the ? line and the counts are said (B2)",
    rc == 77 and any(x.startswith("  ? b:") for x in out) and "1/2 verified" in out[-1] and "1 unread" in out[-1], (rc, out))
rc, out = run_main({"a": 1}, {})
arm("every body unread → rc 77, never 0", rc == 77, (rc, out))
rc, out = run_main({"a": 1, "b": 2}, {1: BAD})
arm("a missing flag outranks an unread body → rc 1", rc == 1, (rc, out))
arm("no bodies running → rc 77 (nothing proven)", L.main(live={}, say=lambda *_: None) == 77)
lines, real_bodies = [], L.bodies
L.bodies = lambda: None
try:
    rc = L.main(say=lines.append)
finally:
    L.bodies = real_bodies
arm("tmux gave no answer → rc 77, said as UNVERIFIED", rc == 77 and "UNVERIFIED" in lines[0], (rc, lines))


class R:
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


arm("bodies(): only ax- sessions, keyed by agent name (the owner's own sessions are ignored)",
    L.bodies(run=lambda *a, **k: R(0, "ax-seed 10\nwork 11\nax-forge 12\nmax-x 13\n")) == {"seed": 10, "forge": 12})
arm("bodies(): 'no server running' → {} (no bodies), never None",
    L.bodies(run=lambda *a, **k: R(1, err="no server running on /tmp/tmux-1000/default")) == {})
arm("bodies(): any other tmux error → None (UNVERIFIED), never {}",
    L.bodies(run=lambda *a, **k: R(1, err="lost server")) is None)


def boom(*a, **k):
    raise OSError("no tmux")


arm("bodies(): tmux not installed → None", L.bodies(run=boom) is None)

print("ALL PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
