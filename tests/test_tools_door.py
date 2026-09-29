#!/usr/bin/env python3
"""Oracle: the registry door (mcp/tools/server.py, goal 4227 S4) is a convenience, never a new
capability.

    venv/bin/python tests/test_tools_door.py        (also run by nucleus/check.sh)

  D1 find() returns registered tools, and the no-hit reply points at the tool-building skill.
  D2 run() refuses anything that isn't a registered script id: tier/, a '..' escape, a shell
     metacharacter smuggled into the id, and an arbitrary path.
  D3 run() never starts an MCP server. An mcp: id gets a pointer and NO subprocess, because
     starting a server would walk past the capability grant (spawn.sh `Grants:`).
  D4 args are an argv list, never a shell: a `$(…)` argument is not executed.
  D5 the timeout is clamped: a huge request can't hold the door open indefinitely.

The server module is imported and its tool functions called directly. FastMCP's decorator
returns the plain function, so this exercises the same code the MCP call runs, without a
stdio session.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXIT_SKIP = 77
SRC = Path(os.environ.get("DOOR_SRC") or REPO / "mcp" / "tools" / "server.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


# The door derives REPO from its own path, so the subject runs from a temp repo tree: its copy
# at mcp/tools/server.py, with everything it reaches symlinked in. That's how a mutant copy
# (mutation_probe hands one over by DOOR_SRC) is tested rather than skipped.
TREE = Path(tempfile.mkdtemp(prefix="t_door_"))
(TREE / "mcp" / "tools").mkdir(parents=True)
import shutil  # noqa: E402
shutil.copy(SRC, TREE / "mcp" / "tools" / "server.py")
for rel in ("nucleus", "skills", "venv", "mcp/registry.json", "mcp/manifest.json"):
    if (REPO / rel).exists():
        (TREE / rel).symlink_to(REPO / rel)
import atexit  # noqa: E402
atexit.register(shutil.rmtree, TREE, True)

try:
    spec = importlib.util.spec_from_file_location("tools_door_under_test",
                                                  TREE / "mcp" / "tools" / "server.py")
    door = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(door)
except Exception as e:  # noqa: BLE001 — no mcp package in this env: nothing verified
    print(f"SKIP: the door is not importable here ({type(e).__name__}: {e}).")
    sys.exit(EXIT_SKIP)

# ── D1 ────────────────────────────────────────────────────────────────────────────────────
hits = door.find("registry tool find")
check("D1 find returns the registry itself for 'registry tool find'",
      "script:nucleus/toolreg.py" in hits, hits[:200])
none = door.find("zzqx9 vbnmq7")
check("D1 no hit → points at the tool-building skill",
      "skills/tool-building/SKILL.md" in none, none)

# ── D2 + D3 + D4: watch every subprocess the door starts ─────────────────────────────────
started = []
real_run = subprocess.run


def spy(cmd, *a, **k):
    started.append(cmd)
    return real_run(cmd, *a, **k)


door.subprocess.run = spy
for bad in ("script:tier/x.py", "script:nucleus/../tests/test_tools_door.py",
            "script:nucleus/toolreg.py; touch /tmp/pwn", "/bin/sh", "script:nucleus/nope.py"):
    out = door.run(bad)
    check(f"D2 refused: {bad[:44]!r}", out.startswith("refused"), out[:100])
check("D2 no refused id started a process", started == [], str(started))

out = door.run("mcp:org/economy")
check("D3 an mcp: id gets a pointer to the granted tool name",
      "mcp__org__economy" in out and "never starts a server" in out, out[:160])
check("D3 ... and NO subprocess was started", started == [], str(started))

marker = Path(tempfile.gettempdir()) / f"door_pwn_{os.getpid()}"
out = door.run("script:nucleus/toolreg.py", ["find", f"$(touch {marker})", f"`touch {marker}`"])
check("D4 a $(…)/backtick argument is passed as data, never executed",
      out.startswith("exit ") and not marker.exists(), out[:120])
check("D4 the script ran with an argv LIST (no shell)",
      len(started) == 1 and isinstance(started[0], list), str(started)[:160])
marker.unlink(missing_ok=True)

# ── D5 ────────────────────────────────────────────────────────────────────────────────────
seen = {}


def spy_timeout(cmd, *a, **k):
    seen["timeout"] = k.get("timeout")
    return real_run(cmd, *a, **k)


door.subprocess.run = spy_timeout
door.run("script:nucleus/toolreg.py", ["find", "x"], timeout=10**9)
check("D5 the timeout is clamped to the door's maximum",
      seen.get("timeout") == door.RUN_TIMEOUT_MAX, str(seen))
door.subprocess.run = real_run

if fails:
    print(f"\nFAIL: {len(fails)} door invariant(s) broken")
    sys.exit(1)
print("\nPASS: the door finds and runs registered scripts only; it is never a new capability")
