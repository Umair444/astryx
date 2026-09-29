#!/usr/bin/env python3
"""Oracle: `spawn.sh --render` produces the home a spawn would, with no side effect. Through it,
every RESIDENT gets the registry door and the tool nudge, and no STATIONED agent gets the door
(goal 4227 S4, abstractor-4's W1 + W3; seed's --render follow-up).

    venv/bin/python tests/test_spawn_wiring.py        (also run by nucleus/check.sh)
    SPAWN_SRC=<path> …                                 (the subject; mutation_probe sets it)

THE GENERATION PATH, NOT ITS TEXT. spawn.sh runs for real: from a temp repo tree (its copy at
nucleus/spawn.sh, with FIXTURE charters, local.md, runtime.json and .env), with `--render`. So
charter resolution, the grants loop, Think:, runtime_env's provider splice and the heredocs all
execute exactly as they would in a spawn.

IT CAN'T BECOME A REAL SPAWN, even under a mutant. tmux, psql, claude and pgrep are SHIMS first
on PATH that log every invocation and touch nothing. The .env DSN points nowhere, HOME is the
temp tree, and every fixture agent name is one no real org uses. A broken render guard shows up
as a logged side effect, never as a session.

  R1 a resident renders exactly CLAUDE.md, .mcp.json and .claude/settings.json, and nothing else
  R2 .mcp.json: {astryx, tools}, and with a grant spliced in {astryx, tools, gmail}, valid JSON
  R3 settings.json: the nudge in its OWN UserPromptSubmit group at timeout 3, usage.py at 5;
     Think: off and the provider token splice both land, as in a real spawn
  R4 CLAUDE.md = charter + "## The law (local.md)" + local.md
  R5 NO side effect: zero tmux/psql/claude/pgrep invocations, and the real home path
     (<root>/homes/<agent>) is never created, even for an agent that is ALREADY resident
  R6 an <outdir> inside the repo is refused and nothing is created (a render holds a token)
  R7 <outdir> is 0700 and settings.json is 0600
  R8 a stationed agent renders nothing (it has no home), exit 0
  S5 station.py never references the door, the registry, or --mcp-config
"""
import ast
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("SPAWN_SRC") or REPO / "nucleus" / "spawn.sh")
STATION = REPO / "nucleus" / "station.py"
TOKEN = "tok-fixture-4227-render"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def make_tree() -> Path:
    t = Path(tempfile.mkdtemp(prefix="t_render_"))
    (t / "nucleus").mkdir()
    shutil.copy(SUBJECT, t / "nucleus" / "spawn.sh")
    for f in ("charter.py", "runtime_env.py"):          # both derive their paths from __file__
        shutil.copy(REPO / "nucleus" / f, t / "nucleus" / f)
    # The RUNNING interpreter's venv, not <repo>/venv: a worktree or CI clone has none.
    (t / "venv").symlink_to(Path(sys.prefix))
    (t / ".env").write_text("ASTRYX_DSN=postgresql://nobody@127.0.0.1:1/none\n"
                            f"FIXTURE_TOKEN={TOKEN}\n")
    (t / "local.md").write_text("# fixture law\nbe good\n")
    (t / "runtime.json").write_text(json.dumps({"zzgrant": {
        "base_url": "https://example.invalid/anthropic", "token_env": "FIXTURE_TOKEN"}}))
    for name, body in (("zzres", "# zzres\nfixture resident\n"),
                       ("zzgrant", "# zzgrant\nGrants: gmail\nThink: off\n"),
                       ("zzstat", "# zzstat\nType: stationed\n")):
        (t / "agents" / name).mkdir(parents=True)
        (t / "agents" / name / f"{name}.md").write_text(body)
    shims = t / "shims"
    shims.mkdir()
    for tool in ("tmux", "psql", "claude", "pgrep"):
        # has-session answers from $RESIDENT so R5 can present an already-resident agent;
        # capture-pane shows a ready prompt so a mutant that falls through to the boot drain
        # finishes fast instead of looping.
        (shims / tool).write_text(
            "#!/bin/bash\n"
            f'echo "{tool} $*" >> "$SHIM_LOG"\n'
            'if [ "$1" = "has-session" ]; then [ -n "$RESIDENT" ] && exit 0 || exit 1; fi\n'
            'if [ "$1" = "capture-pane" ]; then echo "❯"; fi\n'
            f'[ "{tool}" = pgrep ] && exit 1\nexit 0\n')
        (shims / tool).chmod(0o755)
    return t


def render(root: Path, agent: str, out: Path, resident=False):
    log = root / "shim.log"
    env = {"PATH": f"{root / 'shims'}:/usr/bin:/bin", "HOME": str(root), "SHIM_LOG": str(log),
           "ASTRYX_NODE": "/N/node", "RESIDENT": "1" if resident else ""}
    r = subprocess.run(["bash", str(root / "nucleus" / "spawn.sh"), "--render", agent, str(out)],
                       env=env, capture_output=True, text=True, timeout=60)
    calls = log.read_text().splitlines() if log.exists() else []
    if log.exists():
        log.unlink()
    return r, calls


def files_under(d: Path) -> set:
    return {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file()} if d.exists() else set()


root = make_tree()
outs = Path(tempfile.mkdtemp(prefix="t_render_out_"))
try:
    # ── R1–R5, R7: a plain resident ──────────────────────────────────────────────────────
    out = outs / "zzres"
    r, calls = render(root, "zzres", out)
    check("R1 render exits 0", r.returncode == 0, (r.stdout + r.stderr)[-300:])
    check("R1 exactly CLAUDE.md, .mcp.json, .claude/settings.json",
          files_under(out) == {"CLAUDE.md", ".mcp.json", ".claude/settings.json"},
          str(sorted(files_under(out))))
    check("R5 no side effect: zero tmux/psql/claude/pgrep calls", calls == [], str(calls))
    check("R5 the real home path is never created", not (root / "homes" / "zzres").exists())
    try:
        servers = json.loads((out / ".mcp.json").read_text())["mcpServers"]
    except Exception as e:  # noqa: BLE001
        servers = {}
        check("R2 .mcp.json is valid JSON", False, str(e))
    check("R2 resident .mcp.json servers == {astryx, tools}", set(servers) == {"astryx", "tools"},
          str(sorted(servers)))
    check("R2 the door points at the tree's mcp/tools/server.py",
          (servers.get("tools") or {}).get("args") == [f"{root}/mcp/tools/server.py"],
          str(servers.get("tools")))
    try:
        ups = json.loads((out / ".claude" / "settings.json").read_text())["hooks"]["UserPromptSubmit"]
    except Exception as e:  # noqa: BLE001
        ups = []
        check("R3 settings.json is valid JSON", False, str(e))
    groups = [[h.get("command", "") for h in g.get("hooks", [])] for g in ups]
    timeouts = {h.get("command", "").rsplit("/", 1)[-1]: h.get("timeout")
                for g in ups for h in g.get("hooks", [])}
    nudge_groups = [g for g in groups if any(c.endswith("hooks/nudge.py") for c in g)]
    check("R3 the nudge is ALONE in its own UserPromptSubmit group",
          len(nudge_groups) == 1 and len(nudge_groups[0]) == 1, str(groups))
    check("R3 nudge timeout 3 < usage.py's 5",
          timeouts.get("nudge.py") == 3 and timeouts.get("usage.py") == 5, str(timeouts))
    law = (out / "CLAUDE.md").read_text() if (out / "CLAUDE.md").exists() else ""
    check("R4 CLAUDE.md = charter + the law",
          law.startswith("# zzres\nfixture resident\n") and "## The law (local.md)" in law
          and law.rstrip().endswith("be good"), law[:120])
    mode = lambda p: stat.S_IMODE(p.stat().st_mode) if p.exists() else None  # noqa: E731
    check("R7 <outdir> is 0700", mode(out) == 0o700, str(mode(out)))
    check("R7 settings.json is 0600", mode(out / ".claude" / "settings.json") == 0o600,
          str(mode(out / ".claude" / "settings.json")))

    # ── R2/R3 with a grant, Think: off, and a provider override ─────────────────────────
    out = outs / "zzgrant"
    r, calls = render(root, "zzgrant", out)
    try:
        servers = json.loads((out / ".mcp.json").read_text())["mcpServers"]
        env_ = json.loads((out / ".claude" / "settings.json").read_text())["env"]
    except Exception as e:  # noqa: BLE001
        servers, env_ = {}, {}
        check("R2 grant render is valid JSON", False, f"{e}: {r.stderr[-200:]}")
    check("R2 with a grant spliced: {astryx, tools, gmail}",
          set(servers) == {"astryx", "tools", "gmail"}, str(sorted(servers)))
    check("R3 Think: off lands (MAX_THINKING_TOKENS=0)", env_.get("MAX_THINKING_TOKENS") == "0",
          str(env_))
    check("R3 the provider token splice lands, as in a real spawn",
          env_.get("ANTHROPIC_AUTH_TOKEN") == TOKEN, str(sorted(env_)))
    check("R5 no side effect for the grant render either", calls == [], str(calls))

    # ── R5: an agent that is ALREADY resident still renders, with no side effect ────────
    out = outs / "zzres-live"
    r, calls = render(root, "zzres", out, resident=True)
    check("R5 an already-resident agent still renders (no 'already resident' exit)",
          (out / ".mcp.json").exists(), (r.stdout + r.stderr)[-200:])
    check("R5 ...and still makes zero tmux/psql/claude/pgrep calls", calls == [], str(calls))

    # ── R6: inside the repo is refused ───────────────────────────────────────────────────
    inside = root / "homes" / "zz-inside"
    r, calls = render(root, "zzres", inside)
    check("R6 an <outdir> inside the repo is refused (exit != 0)", r.returncode != 0,
          r.stdout[-200:])
    check("R6 ...and nothing is created there", not inside.exists())

    # ── R8: stationed ────────────────────────────────────────────────────────────────────
    out = outs / "zzstat"
    r, calls = render(root, "zzstat", out)
    check("R8 a stationed agent renders nothing, exit 0",
          r.returncode == 0 and files_under(out) == set() and calls == [],
          f"rc={r.returncode} files={files_under(out)} calls={calls}")
finally:
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(outs, ignore_errors=True)

# ── S5: the stationed kind never gets the door ──────────────────────────────────────────────
tree = ast.parse(STATION.read_text())
docs = {id(n.body[0].value) for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
code_strings = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
leaks = [s for s in code_strings if "mcp/tools" in s or "registry.json" in s or s == "--mcp-config"]
check("S5 station.py never references the door, the registry, or --mcp-config", not leaks,
      str(leaks))
check("S5 ...and still passes --strict-mcp-config", "--strict-mcp-config" in code_strings)

if fails:
    print(f"\nFAIL: {len(fails)} spawn render/wiring invariant(s) broken")
    sys.exit(1)
print("\nPASS: --render is the real generation with no side effect; residents get door + nudge")
