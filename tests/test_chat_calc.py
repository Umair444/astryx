#!/usr/bin/env python3
"""Oracle: the chat calculator's server (observatory/api/calc.py, owner 11-15), on this host's real qalc and sandbox.

  C1 it answers: arithmetic, a unit conversion, a currency conversion (a plain minus sign for agents)
  C2 the gate: an empty, a too-long, a multi-line expression and the system functions (export/save/load/command) are
     refused before qalc runs; a leading '-' is an expression, never a qalc option
  C3 THE SANDBOX holds when the gate is bypassed: export() writes nothing, load()/command() (with or without
     parentheses, medic 12192) read no host file and run no program, and nothing inside reaches the network
  C4 a runaway expression is cut at the timeout, never a hung worker
  C5 a member reaches it (main.MEMBER); the public face does not
Exit 0 pass · 1 fail · 77 qalc or user namespaces unavailable."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO), str(REPO / "src")]
fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


if not shutil.which("qalc") or subprocess.run(["unshare", "-rn", "true"], capture_output=True).returncode:
    print("  NOT VERIFIED: qalc or unprivileged user namespaces are missing on this host")
    sys.exit(77)
sys.path.insert(0, str(REPO / "src"))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_chat_calc", REPO, deps=('fastapi',), env=False)   # a clean clone (no venv): 77, not an import crash
from observatory.api import calc as C  # noqa: E402

print("C answers")
arm("C1 arithmetic", C.evaluate("2+3*4") == "14", C.evaluate("2+3*4"))
arm("C1 a unit conversion", C.evaluate("5 km/h to m/s").endswith("m/s"))
cur = C.evaluate("10 usd to pkr")
arm("C1 a currency conversion", cur.startswith("PKR "), cur)
arm("C1 a plain minus sign", C.evaluate("-5+3") == "-2", C.evaluate("-5+3"))
print("C the gate")
arm("C2 empty, too long, multi-line are refused", all(C.judge(e) for e in ("", " ", "1" * 301, "1+1\n2+2")))
arm("C2 the system functions are refused, any case, any spacing",
    all(C.judge(e) for e in ('export([1],"/x")', 'SAVE (3, "y")', 'load("/etc/hostname")', 'Command("echo", "hi")')))
arm("C2 ordinary words that only contain those names pass", not C.judge("downloads per hour") and not C.judge("savings * 2"))
print("C the sandbox")
with tempfile.TemporaryDirectory(dir=str(REPO)) as td:
    target = Path(td) / "written.csv"
    try:
        C.evaluate(f'export([1,2], "{target}")')
    except Exception:
        pass
    arm("C3 export() straight through evaluate() writes nothing (the filesystem is read-only inside)", not target.exists())
r = subprocess.run(["unshare", "-rnm", "--propagation", "private", "sh", "-c",
                    "python3 -c \"import socket; socket.create_connection(('1.1.1.1', 443), 2)\" 2>/dev/null && echo NET || echo none"],
                   capture_output=True, text=True, timeout=20)
arm("C3 nothing inside reaches the network", r.stdout.strip() == "none", r.stdout)
cdir = Path(tempfile.mkdtemp(prefix="calccanary", dir=str(REPO)))     # outside /tmp: the jail's /tmp is its own
canary = cdir / "canary.txt"
canary.write_text("424242\n")
try:
    # THE PRECONDITION, measured (a test that can't fail proves nothing): qalc OUTSIDE the sandbox does read it
    plain = subprocess.run(["qalc", "-t", f' load "{canary}"'], capture_output=True, text=True, timeout=10, cwd="/").stdout
    arm("C3 precondition: unsandboxed qalc reads the canary with `load \"…\"` (else the arm below is vacuous)",
        "424242" in plain, plain[:120])
    attacks = [f'load "{canary}"', f'load("{canary}")', 'command "id"', 'command("id")', 'command "sh" "-c" "echo 777"',
               'load "/etc/hostname"', f'load "{REPO / ".env"}"']
    outs = []
    for e in attacks:
        try:
            outs.append(C.evaluate(e))
        except Exception:
            outs.append("")
    arm("C3 medic 12192's forms (no parentheses) straight through evaluate(): no host file read, no program run",
        not any("424242" in o or "uid=" in o or o.strip() == "777" for o in outs), outs)
    arm("C2 ...and the gate refuses them by bare name", all(C.judge(e) for e in attacks if "load" in e or "command" in e))
finally:
    shutil.rmtree(cdir, ignore_errors=True)
print("C the clock")
t0 = time.time()
try:
    C.evaluate("factorial(10^9)")
    out = "answered"
except Exception:
    out = "cut"
arm("C4 a runaway expression is cut within the timeout", time.time() - t0 < C.TIMEOUT + 3, (out, round(time.time() - t0, 1)))
print("C who reaches it")
src = (REPO / "observatory" / "api" / "main.py").read_text()
arm("C5 a member reaches it, and it is not public", '("POST", "/api/chat/calc")' in src.split("MEMBER = {", 1)[1].split("}", 1)[0]
    and "/api/chat/calc" not in src.split("PUBLIC = {", 1)[1].split("}", 1)[0])
print(f"{'PASS' if not fails else 'FAIL'}: chat calc ({fails} failing)")
sys.exit(1 if fails else 0)
