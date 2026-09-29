#!/usr/bin/env python3
"""Oracle: every RESIDENT is spawned with the registry door and the tool nudge, and no STATIONED
agent gets the door (goal 4227 S4, abstractor-4's wiring conditions W1 + W3).

    venv/bin/python tests/test_spawn_wiring.py        (also run by nucleus/check.sh)
    SPAWN_SRC=<path> …                                 (the subject; mutation_probe sets it)

HOW, AND ITS LIMIT. spawn.sh has no generate-only mode (it writes the home and then launches
tmux), and tests must never run spawn.sh itself. So this runs the two heredocs spawn.sh
EXECUTES, verbatim, in bash, with spawn's variables set, and parses what they produce. The
expansion is real, including a grant's $EXTRA splice, which is where a JSON comma goes wrong.
What it can't see is spawn.sh's control flow AROUND the heredocs. A real generation run needs
a dry-run mode in spawn.sh, which is seed's call.

  S1 .mcp.json is valid JSON, and has astryx AND tools (the door) pointing at mcp/tools/server.py
  S2 ...still valid with a grant spliced in via $EXTRA, and every server is present
  S3 settings.json is valid JSON. UserPromptSubmit has the nudge in its OWN group (parallel,
     measured on this host) with timeout 3, and usage.py stays in its group with timeout 5
  S4 the nudge's timeout is below usage.py's, so it never extends the worst-case prompt latency
  S5 station.py (the STATIONED kind, --tools "" fail-closed) never references the door, the
     registry, or an --mcp-config: there, the door WOULD be a new capability
The heredocs are located by their exact `cat > "$HOME_D/…" <<EOF` openers. Not finding exactly
one of each is a FAILURE: a moved heredoc must not turn this into a vacuous pass.
"""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("SPAWN_SRC") or REPO / "nucleus" / "spawn.sh")
STATION = REPO / "nucleus" / "station.py"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def heredoc(opener: str) -> str | None:
    lines = SUBJECT.read_text().splitlines()
    starts = [i for i, l in enumerate(lines) if l.strip() == opener]
    if len(starts) != 1:
        return None
    i = starts[0]
    end = next((j for j in range(i + 1, len(lines)) if lines[j] == "EOF"), None)
    if end is None:
        return None
    return "\n".join(["cat <<EOF"] + lines[i + 1:end] + ["EOF"])


def expand(doc: str, **vars_) -> str:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **vars_}
    return subprocess.run(["bash", "-c", doc], env=env, capture_output=True, text=True,
                          timeout=10).stdout


BASE = {"ROOT": "/R", "NODE": "/N/node", "AGENT": "zz", "EXTRA": "", "TENV": "", "RENV": ""}
GRANT = (',\n  "gmail": { "command": "/R/venv/bin/python", "args": ["/R/mcp/gmail/server.py"] }')

mcp_doc = heredoc('cat > "$HOME_D/.mcp.json" <<EOF')
set_doc = heredoc('cat > "$HOME_D/.claude/settings.json" <<EOF')
check("the .mcp.json heredoc is found exactly once", mcp_doc is not None)
check("the settings.json heredoc is found exactly once", set_doc is not None)

if mcp_doc:
    for label, extra, want in (("no grants", "", {"astryx", "tools"}),
                               ("a grant spliced via $EXTRA", GRANT, {"astryx", "tools", "gmail"})):
        out = expand(mcp_doc, **{**BASE, "EXTRA": extra})
        try:
            servers = json.loads(out)["mcpServers"]
            ok = set(servers) == want
            detail = str(sorted(servers))
        except Exception as e:  # noqa: BLE001
            servers, ok, detail = {}, False, f"not valid JSON ({e}): {out[:200]!r}"
        check(f"S1/S2 .mcp.json valid with {label}: servers == {sorted(want)}", ok, detail)
        tools = servers.get("tools") or {}
        check(f"S1 the door points at mcp/tools/server.py ({label})",
              tools.get("args") == ["/R/mcp/tools/server.py"], str(tools))

if set_doc:
    out = expand(set_doc, **BASE)
    try:
        ups = json.loads(out)["hooks"]["UserPromptSubmit"]
    except Exception as e:  # noqa: BLE001
        ups = []
        check("S3 settings.json is valid JSON", False, f"{e}: {out[:200]!r}")
    groups = [[h.get("command", "") for h in g.get("hooks", [])] for g in ups]
    timeouts = {h.get("command", "").rsplit("/", 1)[-1]: h.get("timeout")
                for g in ups for h in g.get("hooks", [])}
    nudge_groups = [g for g in groups if any(c.endswith("hooks/nudge.py") for c in g)]
    usage_groups = [g for g in groups if any(c.endswith("hooks/usage.py") for c in g)]
    check("S3 the nudge is registered on UserPromptSubmit exactly once", len(nudge_groups) == 1,
          str(groups))
    check("S3 ...in its OWN group, not sharing usage.py's",
          len(nudge_groups) == 1 and len(nudge_groups[0]) == 1 and nudge_groups != usage_groups,
          str(groups))
    check("S3 usage.py is still registered, timeout 5",
          len(usage_groups) == 1 and timeouts.get("usage.py") == 5, str(timeouts))
    check("S4 the nudge's timeout is 3, below usage.py's",
          timeouts.get("nudge.py") == 3 and 3 < (timeouts.get("usage.py") or 0), str(timeouts))

# ── S5: the stationed kind never gets the door ──────────────────────────────────────────────
if not STATION.exists():
    check("S5 station.py present", False, f"{STATION} missing")
else:
    tree = ast.parse(STATION.read_text())
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)}
    code_strings = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
    leaks = [s for s in code_strings
             if "mcp/tools" in s or "registry.json" in s or s == "--mcp-config"]
    check("S5 station.py's executable strings never reference the door, the registry, or "
          "--mcp-config", not leaks, str(leaks))
    check("S5 ...and it still passes --strict-mcp-config (zero MCP by default)",
          "--strict-mcp-config" in code_strings)

if fails:
    print(f"\nFAIL: {len(fails)} spawn-wiring invariant(s) broken")
    sys.exit(1)
print("\nPASS: residents get the door + the nudge (own group, timeout 3); stationed agents don't")
