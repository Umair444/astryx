"""mcp/scan.py: a server that fails a rescan keeps its last good tools, with the error that names the failure
(owner 13928: the Tools page showed astryx with 0 tools; medic 13932)."""
import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("scan_under_test", REPO / "mcp" / "scan.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
R = subprocess.CompletedProcess
GOOD = [{"name": "send", "description": "x"}]
REAL = subprocess.run
fails = []


def arm(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    ok or fails.append(label)


def run(fake):
    """One scan of the wire server alone, in a temp repo holding a last good list, with --list-tools faked."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "mcp").mkdir()
    (tmp / "mcp" / "manifest.json").write_text(json.dumps({"servers": [{"server": "astryx", "tools": GOOD}]}))
    S.REPO, S.REGISTRY, S.org_local = tmp, {"astryx": S.REGISTRY["astryx"]}, lambda spec: False
    subprocess.run = lambda c, *a, **k: fake(c) if "--list-tools" in c else REAL(c, *a, **k)
    try:
        asyncio.run(S.main())
    finally:
        subprocess.run = REAL
    return json.loads((tmp / "mcp" / "manifest.json").read_text())["servers"][0]


def timeout(c):
    raise subprocess.TimeoutExpired("node", 30)


err = "node:internal/x\n    at y\nError [ERR_MODULE_NOT_FOUND]: Cannot find package 'pg'\n    at ModuleLoader.z\n"
got = run(lambda c: R(c, 1, "", err))
arm("a failed exit keeps the tools", got["tools"] == GOOD)
arm("its error is the line naming the failure", got.get("error") == "rc 1: Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'pg'")
got = run(lambda c: R(c, 0, "", ""))
arm("empty stdout keeps the tools, with an error", got["tools"] == GOOD and bool(got.get("error")))
got = run(timeout)
arm("a timeout keeps the tools, with an error", got["tools"] == GOOD and "timed out" in got.get("error", ""))
fresh = [{"name": "send", "description": "y"}, {"name": "subscribe", "description": "z"}]
got = run(lambda c: R(c, 0, json.dumps(fresh), ""))
arm("a clean scan replaces the tools, no error", got["tools"] == fresh and "error" not in got)

print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: a failed rescan keeps the last good tools")
sys.exit(1 if fails else 0)
