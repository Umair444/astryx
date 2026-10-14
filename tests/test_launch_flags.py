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

print("ALL PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
