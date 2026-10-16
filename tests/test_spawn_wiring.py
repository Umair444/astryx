#!/usr/bin/env python3
"""Oracle: `spawn.sh --render` produces the home a spawn would, with no side effect. Through it,
every RESIDENT gets the registry door and the tool nudge, and no STATIONED agent gets the door
(goal 4227 S4, abstractor-4's W1 + W3; seed's --render follow-up).

    venv/bin/python tests/test_spawn_wiring.py        (also run by devtools/check.sh)
    SPAWN_SRC=<path> …                                 (the subject; mutation_probe sets it)

THE GENERATION PATH, NOT ITS TEXT. spawn.sh runs for real: from a temp repo tree (its copy at
scripts/spawn.sh, with FIXTURE charters, local.md, runtime.json and .env), with `--render`. So
charter resolution, the grants loop, Think:, runtime_env's provider splice and the heredocs all
execute exactly as they would in a spawn.

IT CAN'T BECOME A REAL SPAWN, even under a mutant. tmux, psql, claude and pgrep are SHIMS first
on PATH that log every invocation and touch nothing. The .env DSN points nowhere, HOME is the
temp tree, and every fixture agent name is one no real org uses. A broken render guard shows up
as a logged side effect, never as a session.

  R1 a resident renders exactly CLAUDE.md, .mcp.json and .claude/settings.json, and nothing else
  R2 .mcp.json: {astryx, tools, hands, influence}, and with a grant spliced in {astryx, tools, hands, influence,
     gmail}, valid JSON
  R11 influence (who_should_i_ask, plan-11324, seed #58432) is the tree's mcp/influence/server.py with
      ASTRYX_AGENT = the agent written into its env (never inherited); `Grants: memory` mounts mcp/memory (ask)
      and adds ONLY memory to the resident set (the tool left that server; the grant gained nothing)
  R3 settings.json: the nudge in its OWN UserPromptSubmit group at timeout 3, usage.py at 5;
     Think: off and the provider token splice both land, as in a real spawn
  R4 CLAUDE.md = charter + "## The law (local.md)" + local.md
  R5 NO side effect: zero tmux/psql/claude/pgrep invocations, and the real home path
     (<root>/homes/<agent>) is never created, even for an agent that is ALREADY resident
  R6 an <outdir> inside the repo is refused and nothing is created (a render holds a token)
  R7 <outdir> is 0700 and settings.json is 0600
  R9 an EXISTING <outdir> is refused and left byte-identical: render never overwrites (else
     `--render seed ~` truncates the owner's own ~/.claude/settings.json)
  R10 ANDROID_ENABLED=1 in .env adds the phone server (plan-8675), named for the agent; without it,
      R2's exact set shows it absent
  R8 a stationed agent renders nothing (it has no home), exit 0: no influence, no door, no hands
  S5 station.py never references the door, influence, the registry, or --mcp-config
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
SUBJECT = Path(os.environ.get("SPAWN_SRC") or REPO / "scripts" / "spawn.sh")
STATION = REPO / "src" / "astryx" / "core" / "station.py"
TOKEN = "tok-fixture-4227-render"
# Every RESIDENT's core block: the wire, the door (4227 S4), hands (7862), influence (11324, seed #58432).
RESIDENT_SET = {"astryx", "tools", "hands", "influence"}
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
    for _d in ("devtools", "scripts", "src/astryx/contrib", "src/astryx/core", "src/astryx/data", "src/astryx/econ", "src/astryx/federation", "src/astryx/hands", "src/astryx/hearing", "src/astryx/memory", "src/astryx/people", "src/astryx/pg", "src/astryx/pulse", "src/astryx/pulse/shipped_triggers", "src/astryx/security", "src/astryx/security/sqlguard", "src/astryx/security/sqlguard/shim", "src/astryx/sql"):  # goal 10224 S4: the moved tree's dirs
        (t / _d).mkdir(parents=True, exist_ok=True)
    shutil.copy(SUBJECT, t / "scripts" / "spawn.sh")
    from _astryx_skel import mirror                     # goal 10224 S4: both derive their paths from __file__
    mirror(t, copy=("src/astryx/core/charter.py", "src/astryx/core/runtime_env.py"), skip=("scripts/spawn.sh",))
    # The RUNNING interpreter's venv, not <repo>/venv: a worktree or CI clone has none.
    (t / "venv").symlink_to(Path(sys.prefix))
    (t / ".env").write_text("ASTRYX_DSN=postgresql://nobody@127.0.0.1:1/none\n"
                            f"FIXTURE_TOKEN={TOKEN}\n")
    (t / "local.md").write_text("# fixture law\nbe good\n")
    (t / "runtime.json").write_text(json.dumps({"zzgrant": {
        "base_url": "https://example.invalid/anthropic", "token_env": "FIXTURE_TOKEN"}}))
    for name, body in (("zzres", "# zzres\nfixture resident\n"),
                       ("zzgrant", "# zzgrant\nGrants: gmail\nThink: off\n"),
                       ("zzmem", "# zzmem\nGrants: memory\n"),
                       ("zzstat", "# zzstat\nType: stationed\n")):
        (t / "agents" / name).mkdir(parents=True)
        (t / "agents" / name / f"{name}.md").write_text(body)
    # A real repo HAS homes/. Without it, a plain `mkdir <repo>/homes/x` fails for want of a
    # parent, and that would mask a missing inside-the-repo check (R6).
    (t / "homes").mkdir()
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
    r = subprocess.run(["bash", str(root / "scripts" / "spawn.sh"), "--render", agent, str(out)],
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
    check("R2 resident .mcp.json servers == {astryx, tools, hands, influence}",
          set(servers) == RESIDENT_SET,
          str(sorted(servers)))
    check("R2 the door points at the tree's mcp/tools/server.py",
          (servers.get("tools") or {}).get("args") == [f"{root}/mcp/tools/server.py"],
          str(servers.get("tools")))
    inf = servers.get("influence") or {}
    check("R11 influence is the tree's mcp/influence/server.py, ASTRYX_AGENT = this agent in its OWN env",
          inf.get("args") == [f"{root}/mcp/influence/server.py"] and inf.get("env") == {"ASTRYX_AGENT": "zzres"},
          str(inf))
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
    check("R2 with a grant spliced: {astryx, tools, hands, influence, gmail}",
          set(servers) == RESIDENT_SET | {"gmail"}, str(sorted(servers)))
    check("R3 Think: off lands (MAX_THINKING_TOKENS=0)", env_.get("MAX_THINKING_TOKENS") == "0",
          str(env_))
    check("R3 the provider token splice lands, as in a real spawn",
          env_.get("ANTHROPIC_AUTH_TOKEN") == TOKEN, str(sorted(env_)))
    check("R5 no side effect for the grant render either", calls == [], str(calls))

    # ── R10: the phone (plan-8675) only where the org opted in (ANDROID_ENABLED=1) ───────
    envf = root / ".env"
    plain = envf.read_text()
    envf.write_text(plain + "ANDROID_ENABLED=1\n")
    out = outs / "zzres-phone"
    r, calls = render(root, "zzres", out)
    envf.write_text(plain)
    try:
        servers = json.loads((out / ".mcp.json").read_text())["mcpServers"]
    except Exception as e:  # noqa: BLE001
        servers = {}
        check("R10 the opted-in render is valid JSON", False, f"{e}: {r.stderr[-200:]}")
    check("R10 ANDROID_ENABLED=1 → {astryx, tools, hands, influence, phone}",
          set(servers) == RESIDENT_SET | {"phone"}, str(sorted(servers)))
    ph = servers.get("phone") or {}
    check("R10 the phone server is the tree's mcp/phone/server.py, named for this agent",
          ph.get("args") == [f"{root}/mcp/phone/server.py"] and (ph.get("env") or {}).get("ASTRYX_AGENT") == "zzres",
          str(ph))

    # ── R11: `Grants: memory` mounts ask's server and NOTHING else new (who_should_i_ask moved to influence) ──
    out = outs / "zzmem"
    r, calls = render(root, "zzmem", out)
    try:
        servers = json.loads((out / ".mcp.json").read_text())["mcpServers"]
    except Exception as e:  # noqa: BLE001
        servers = {}
        check("R11 the memory-grant render is valid JSON", False, f"{e}: {r.stderr[-200:]}")
    check("R11 Grants: memory → the resident set + {memory}, and no other server",
          set(servers) == RESIDENT_SET | {"memory"}, str(sorted(servers)))
    check("R11 the memory grant is the tree's mcp/memory/server.py (ask), with no env of its own",
          servers.get("memory") == {"command": f"{root}/venv/bin/python", "args": [f"{root}/mcp/memory/server.py"]},
          str(servers.get("memory")))

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

    # ── R9: an existing outdir is refused, untouched ─────────────────────────────────────
    existing = outs / "zz-existing"
    (existing / ".claude").mkdir(parents=True)
    sentinel = b'{"permissions": {"defaultMode": "SENTINEL-owner-file"}}\n'
    (existing / ".claude" / "settings.json").write_bytes(sentinel)
    r, calls = render(root, "zzres", existing)
    check("R9 an existing <outdir> is refused (exit != 0)", r.returncode != 0, r.stdout[-200:])
    check("R9 ...its settings.json is byte-identical, and nothing was added",
          (existing / ".claude" / "settings.json").read_bytes() == sentinel
          and files_under(existing) == {".claude/settings.json"}, str(sorted(files_under(existing))))

    # ── R8: stationed ────────────────────────────────────────────────────────────────────
    out = outs / "zzstat"
    r, calls = render(root, "zzstat", out)
    check("R8 a stationed agent renders nothing, exit 0",
          r.returncode == 0 and files_under(out) == set() and calls == [],
          f"rc={r.returncode} files={files_under(out)} calls={calls}")
    check("R8 ...so no .mcp.json, and nothing it rendered names influence (who_should_i_ask is a RESIDENT's tool)",
          not (out / ".mcp.json").exists()
          and not any("influence" in p.read_text(errors="replace") for p in out.rglob("*") if p.is_file()),
          str(sorted(files_under(out))))
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
leaks = [s for s in code_strings if "mcp/tools" in s or "mcp/influence" in s or "registry.json" in s
         or s == "--mcp-config"]
check("S5 station.py never references the door, influence, the registry, or --mcp-config", not leaks,
      str(leaks))
check("S5 ...and still passes --strict-mcp-config", "--strict-mcp-config" in code_strings)

if fails:
    print(f"\nFAIL: {len(fails)} spawn render/wiring invariant(s) broken")
    sys.exit(1)
print("\nPASS: --render is the real generation with no side effect; residents get door + nudge")
