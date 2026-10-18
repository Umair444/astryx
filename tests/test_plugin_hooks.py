"""The plugin's hooks (plugin/hooks/astryx_hook.py): the join-marker gate and the SessionStart flag check.

GATE. Claude Code runs a plugin's hooks in every project the user opens, and the org's steps are public. So with no
join marker for the project every subcommand exits 0 having done NOTHING: session-start prints nothing, and relay
never executes the org's step.py (a stub that would leave a file proves it didn't run).

FLAGS (owner ruling R2). An astryx session runs with --permission-mode bypassPermissions (default for a charter
with `Permissions: relay`, the rule of src/astryx/core/launch_flags.py) AND --dangerously-load-development-channels naming
this plugin. The check reads permission_mode from the hook's input when Claude Code sends it, and the claude argv by
walking up /proc from the hook's parent. A fake /proc tree drives every arm: both present, each missing, relay mode,
the hook-input mode winning over argv, server:astryx and comma lists, an unreadable argv, and the marketplace in the
relaunch command (from the data dir, else the cache path).

Pure stdlib + node for the key-parity arm (77 without node). Run: venv/bin/python tests/test_plugin_hooks.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "plugin" / "hooks" / "astryx_hook.py"
fails = 0
skipped: list[str] = []


def arm(name: str, ok: bool, detail: str = "") -> None:
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail[-400:]}]" if detail and not ok else ""))
    fails += not ok


tmp = Path(tempfile.mkdtemp(prefix="plugin-hooks-"))
try:
    data = tmp / "plugins" / "data" / "astryx-astryx"
    project = tmp / "work project"
    project.mkdir(parents=True)
    home = tmp / "org"
    (home / "venv" / "bin").mkdir(parents=True)
    (home / "hooks").mkdir()
    (home / "agents" / "team").mkdir(parents=True)
    (home / ".env").write_text("ASTRYX_DSN=postgresql://x@127.0.0.1:1/x\n")
    ran = tmp / "step-ran"
    stub = home / "venv" / "bin" / "python"
    stub.write_text(f"#!/bin/sh\n{{ echo \"argv=$*\"; echo \"agent=$ASTRYX_AGENT\"; cat; }} > '{ran}'\n")  # org-home: inspection: a stub reports the env it was given
    stub.chmod(0o755)
    for s in ("step.py", "usage.py", "nudge.py"):
        (home / "hooks" / s).write_text("# stub\n")
    (home / "agents" / "builder.md").write_text("# builder\n")
    # tmux stubs, so the host's own residents never decide an arm: `has-session` says no, or yes
    for d, rc in (("tmux-none", 1), ("tmux-live", 0)):
        (tmp / d).mkdir()
        (tmp / d / "tmux").write_text(f"#!/bin/sh\nexit {rc}\n")
        (tmp / d / "tmux").chmod(0o755)
    (home / "agents" / "team" / "relayer.md").write_text("# relayer\nPermissions: relay\n")

    def proc_tree(argv: list[str] | None, mode_names=("sh", "tmux: server")) -> tuple[Path, int]:
        """A fake /proc: hook parent 300 (sh) -> 200 (claude, argv) -> 100 ('tmux: server') -> 1."""
        root = Path(tempfile.mkdtemp(dir=tmp, prefix="proc-"))
        chain = [(300, mode_names[0], ["/bin/sh", "-c", "python3 hook"], 200),
                 (200, "claude", argv, 100) if argv is not None else (200, "node", ["node", "x.js"], 100),
                 (100, mode_names[1], ["tmux", "new-session"], 1)]   # org-home: a FAKE process table's argv, never run
        for pid, name, av, ppid in chain:
            d = root / str(pid)
            d.mkdir()
            (d / "status").write_text(f"Name:\t{name}\nState:\tS\nPPid:\t{ppid}\n")
            (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in av) + b"\0")
        return root, 300

    def hook(*args, stdin: dict | None = None, env: dict | None = None, argv: list[str] | None = None,
             proc: tuple[Path, int] | None = None) -> subprocess.CompletedProcess:
        e = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "ASTRYX_"))}
        e.update({"CLAUDE_PLUGIN_DATA": str(data), "CLAUDE_PROJECT_DIR": str(project),
                  "CLAUDE_PLUGIN_ROOT": str(REPO / "plugin"), "CLAUDE_PLUGIN_OPTION_ASTRYX_HOME": str(home),
                  "PATH": f"{tmp / 'tmux-none'}:{os.environ.get('PATH', '')}"})
        if proc is None:
            proc = proc_tree(argv)
        e["ASTRYX_HOOK_PROC"], e["ASTRYX_HOOK_PPID"] = str(proc[0]), str(proc[1])
        e.update(env or {})
        return subprocess.run([sys.executable, str(HOOK), *args], input=json.dumps(stdin or {}),
                              capture_output=True, text=True, env=e, timeout=30)

    GOOD = ["claude", "--permission-mode", "bypassPermissions",
            "--dangerously-load-development-channels", "plugin:astryx@astryx"]

    def start(argv, stdin=None, env=None):
        r = hook("session-start", stdin={"session_id": "abc-123", "hook_event_name": "SessionStart",
                                         "source": "startup", **(stdin or {})}, env=env, argv=argv)
        try:
            out = json.loads(r.stdout) if r.stdout.strip() else {}
        except ValueError:
            out = {"raw": r.stdout}
        return r, out

    # ── the gate: no marker, nothing happens ────────────────────────────────────────────────────
    r, out = start(["claude"])                                       # both flags missing: would nag if it acted
    arm("gate: no marker -> session-start exits 0 and prints nothing", r.returncode == 0 and r.stdout == "",
        r.stdout + r.stderr)
    r = hook("relay", "step", stdin={"hook_event_name": "PreToolUse", "tool_name": "Bash"})
    arm("gate: no marker -> relay step exits 0 and never runs the org's step.py",
        r.returncode == 0 and r.stdout == "" and not ran.exists(), r.stdout + r.stderr)
    r = hook("relay", "step", env={"CLAUDE_PLUGIN_DATA": ""})
    arm("gate: no data dir at all -> nothing is joined, nothing runs", r.returncode == 0 and not ran.exists())

    # ── join ──────────────────────────────────────────────────────────────────────────────────────
    r = hook("join", "Bad Name", "--data", str(data), "--project", str(project))
    arm("join: refuses a name that isn't an agent name", r.returncode == 1 and "refused" in r.stdout, r.stdout)
    r = hook("join", "builder", "--data", str(data), "--project", str(project))
    arm("join: refuses an existing agent's name (it has a charter of its own)",
        r.returncode == 1 and "already has a charter" in r.stdout, r.stdout)
    r = hook("join", "newname", "--data", str(data), "--project", str(project),
             env={"PATH": f"{tmp / 'tmux-live'}:{os.environ.get('PATH', '')}"})
    arm("join: refuses a name with a live resident body (tmux ax-<name>)",
        r.returncode == 1 and "live resident" in r.stdout and not (data / "projects").exists(), r.stdout)
    r = hook("join", "laptop", "--data", str(data), "--project", str(project))
    marker = list((data / "projects").glob("*.json"))
    arm("join: a new name marks the project and writes its charter",
        r.returncode == 0 and len(marker) == 1 and (home / "agents" / "laptop.md").is_file(), r.stdout + r.stderr)
    arm("join: prints the exact relaunch command",
        "claude --permission-mode bypassPermissions --dangerously-load-development-channels plugin:astryx@astryx"
        in r.stdout, r.stdout)
    r = hook("join", "laptop", "--data", str(data), "--project", str(project))
    arm("join: re-joining a plugin-made name is allowed", r.returncode == 0, r.stdout)

    # ── relay, joined ─────────────────────────────────────────────────────────────────────────────
    r = hook("relay", "step", stdin={"hook_event_name": "PreToolUse", "tool_name": "Bash"})
    got = ran.read_text() if ran.exists() else ""
    arm("relay: joined -> the org's venv python runs hooks/step.py as the joined agent, with the hook input",
        f"argv={home / 'hooks' / 'step.py'}" in got and "agent=laptop" in got and '"PreToolUse"' in got, got)
    ran.unlink(missing_ok=True)
    r = hook("relay", "rm-rf")
    arm("relay: an unknown script name runs nothing", r.returncode == 0 and not ran.exists())

    # ── the flag check ───────────────────────────────────────────────────────────────────────────
    r, out = start(GOOD)
    arm("flags: both present -> no relaunch, says it's on the wire",
        r.returncode == 0 and "on the wire as laptop" in out.get("systemMessage", "")
        and "relaunch" not in json.dumps(out).lower(), r.stdout + r.stderr)
    r, out = start(["claude", "--permission-mode", "bypassPermissions"])
    msg = out.get("systemMessage", "")
    arm("flags: channels flag missing -> names it and prints the relaunch command with --resume",
        "missing --dangerously-load-development-channels plugin:astryx@astryx" in msg
        and "claude --permission-mode bypassPermissions --dangerously-load-development-channels "
            "plugin:astryx@astryx --resume abc-123" in msg, msg)
    arm("flags: Claude is told too (additionalContext)",
        "missing" in out.get("hookSpecificOutput", {}).get("additionalContext", ""), json.dumps(out))
    r, out = start(["claude", "--dangerously-load-development-channels", "plugin:astryx@astryx"])
    msg = out.get("systemMessage", "")
    arm("flags: permission mode missing -> names --permission-mode bypassPermissions",
        "--permission-mode bypassPermissions (this session runs default)" in msg
        and "plugin:astryx@astryx" not in msg.split("missing", 1)[1].split("Exit")[0], msg)
    r, out = start(["claude"])
    msg = out.get("systemMessage", "")
    arm("flags: both missing -> both named", "--permission-mode bypassPermissions (" in msg
        and "missing" in msg and "--dangerously-load-development-channels plugin:astryx@astryx (" in msg, msg)
    r, out = start(GOOD[:1] + ["--dangerously-skip-permissions"] + GOOD[3:])
    arm("flags: --dangerously-skip-permissions counts as bypassPermissions",
        "on the wire" in out.get("systemMessage", ""), json.dumps(out))
    r, out = start(GOOD, stdin={"permission_mode": "default"})
    arm("flags: the hook input's permission_mode wins over argv (the mode the session is really in)",
        "this session runs default" in out.get("systemMessage", ""), json.dumps(out))
    r, out = start(GOOD[:1] + GOOD[3:], stdin={"permission_mode": "bypassPermissions"})
    arm("flags: bypass from settings (hook input) with no argv flag is fine",
        "on the wire" in out.get("systemMessage", ""), json.dumps(out))
    r, out = start(["claude", "--permission-mode=bypassPermissions",
                    "--dangerously-load-development-channels=server:astryx"])
    arm("flags: --flag=value forms and the repo's server:astryx entry are accepted",
        "on the wire" in out.get("systemMessage", ""), json.dumps(out))
    r, out = start(["claude", "--permission-mode", "bypassPermissions",
                    "--dangerously-load-development-channels", "server:other,plugin:astryx@elsewhere"])
    arm("flags: a comma list holding plugin:astryx@<any marketplace> is accepted",
        "on the wire" in out.get("systemMessage", ""), json.dumps(out))
    r, out = start(["claude", "--permission-mode", "bypassPermissions",
                    "--dangerously-load-development-channels", "plugin:astryxx@astryx"])
    arm("flags: a look-alike plugin name is not accepted", "missing" in out.get("systemMessage", ""),
        json.dumps(out))
    r = hook("session-start", stdin={"session_id": "s"}, proc=proc_tree(None))
    out = json.loads(r.stdout or "{}")
    arm("flags: no claude process in the chain -> says the flags are unverified, with the launch command",
        "unverified" in out.get("systemMessage", "") and "plugin:astryx@astryx" in out.get("systemMessage", ""),
        r.stdout + r.stderr)

    # relay mode: the charter at any depth asks for the default mode
    mp = next((data / "projects").glob("*.json"))
    mp.write_text(json.dumps({"agent": "relayer", "project": str(project), "home": str(home)}))
    r, out = start(["claude", "--permission-mode", "default",
                    "--dangerously-load-development-channels", "plugin:astryx@astryx"])
    arm("relay mode: Permissions: relay + default mode + channel -> fine",
        "on the wire as relayer" in out.get("systemMessage", ""), json.dumps(out))
    r, out = start(GOOD)
    msg = out.get("systemMessage", "")
    arm("relay mode: bypassPermissions is a finding too, and the relaunch asks for default",
        "--permission-mode default (this session runs bypassPermissions, and its charter says Permissions: relay)"
        in msg and "claude --permission-mode default --dangerously-load-development-channels" in msg, msg)
    r, out = start(["claude", "--permission-mode", "default"])
    msg = out.get("systemMessage", "")
    arm("relay mode: a missing channel flag is still named",
        "--dangerously-load-development-channels plugin:astryx@astryx (" in msg
        and "--permission-mode default (" not in msg, msg)
    mp.write_text(json.dumps({"agent": "laptop", "project": str(project), "home": str(home)}))

    # the marketplace in the relaunch command
    data2 = tmp / "plugins" / "data" / "astryx-my-market"
    shutil.copytree(data, data2)
    r, out = start(["claude", "--permission-mode", "bypassPermissions"], env={"CLAUDE_PLUGIN_DATA": str(data2)})
    arm("marketplace: from the data dir name (astryx-<marketplace>)",
        "plugin:astryx@my-market --resume" in out.get("systemMessage", ""), json.dumps(out))
    cache_root = tmp / "cfg" / "plugins" / "cache" / "acme" / "astryx" / "0.1.0"
    cache_root.mkdir(parents=True)
    r = hook("status", env={"CLAUDE_PLUGIN_DATA": "", "CLAUDE_PLUGIN_ROOT": str(cache_root)})
    st = json.loads(r.stdout or "{}")
    arm("marketplace: from the cache path when there's no data dir; the data dir is derived from it too",
        st.get("marketplace") == "acme" and "plugin:astryx@acme" in st.get("relaunch", ""), r.stdout + r.stderr)

    # the claude walk survives a comm with a space ('tmux: server' broke an awk walk on 10-14)
    r = hook("session-start", stdin={"session_id": "s"}, proc=proc_tree(GOOD, ("bash", "tmux: server")))
    arm("walk: finds claude through a shell parent, with a spaced comm above it",
        "on the wire" in json.loads(r.stdout or "{}").get("systemMessage", ""), r.stdout + r.stderr)

    # ── N2: UserPromptSubmit carries permission_mode (measured on 2.1.293); warn once per session per wrong mode ─
    def prompt(mode, sid="sess-1"):
        r = hook("prompt-check", stdin={"session_id": sid, "hook_event_name": "UserPromptSubmit", "prompt": "hi",
                                        **({"permission_mode": mode} if mode else {})})
        return r.returncode, json.loads(r.stdout).get("systemMessage", "") if r.stdout.strip() else ""
    seq = [prompt("bypassPermissions"), prompt("default"), prompt("default"), prompt("acceptEdits"),
           prompt("bypassPermissions"), prompt("default"), prompt(None), prompt("default", "sess-2")]
    arm("prompt-check: the right mode is silent", seq[0] == (0, ""), repr(seq[0]))
    arm("prompt-check: a wrong mode warns, naming the mode and the relaunch",
        seq[1][0] == 0 and "now in default mode" in seq[1][1] and "--resume sess-1" in seq[1][1], repr(seq[1]))
    arm("prompt-check: the same wrong mode again in that session is silent (once per session)", seq[2] == (0, ""),
        repr(seq[2]))
    arm("prompt-check: a different wrong mode warns again", "now in acceptEdits mode" in seq[3][1], repr(seq[3]))
    arm("prompt-check: back to the right mode is silent and re-arms; a later slip warns again",
        seq[4] == (0, "") and "now in default mode" in seq[5][1], repr(seq[4:6]))
    arm("prompt-check: no permission_mode in the input says nothing", seq[6] == (0, ""), repr(seq[6]))
    arm("prompt-check: another session warns on its own", "now in default mode" in seq[7][1], repr(seq[7]))

    # ── the org never embodies a joined agent (spawn.sh skips a `Plugin: joined` charter) ─────────
    # A copied root (spawn.sh + charter.py) in --render mode: render never touches the DB or tmux, so even a
    # missing guard could only write files into the render dir, which this arm then sees.
    root = tmp / "spawnroot"
    (root / "nucleus").mkdir(parents=True)
    for _d in ("devtools", "scripts", "src/astryx/contrib", "src/astryx/core", "src/astryx/data", "src/astryx/econ", "src/astryx/federation", "src/astryx/hands", "src/astryx/hearing", "src/astryx/memory", "src/astryx/people", "src/astryx/pg", "src/astryx/pulse", "src/astryx/pulse/shipped_triggers", "src/astryx/security", "src/astryx/security/sqlguard", "src/astryx/security/sqlguard/shim", "src/astryx/sql"):  # goal 10224 S4: the moved tree's dirs
        (root / _d).mkdir(parents=True, exist_ok=True)
    for f in ("scripts/spawn.sh", "src/astryx/core/charter.py", "astryx.py", "src/astryx/__init__.py",
              "src/astryx/paths.py", "src/astryx/_version.py",    # the moved tree (goal 10224 S4)
              "src/astryx/orgs.py", "src/astryx/config.py",         # spawn asks THE org predicate and the resolver (S3a)
              "scripts/org_tmux.sh"):                              # ...and sources the org's tmux (S3b)
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / f, root / f)
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "python").symlink_to(sys.executable)
    (root / "agents").mkdir()
    shutil.copy2(home / "agents" / "laptop.md", root / "agents" / "laptop.md")   # the charter join wrote
    (root / "agents" / "plain.md").write_text("# plain\n")
    rend = tmp / "render-joined"
    r = subprocess.run(["bash", str(root / "scripts" / "spawn.sh"), "--render", "laptop", str(rend)],
                       capture_output=True, text=True, timeout=60)
    arm("spawn.sh: a charter join wrote is never embodied (skip, exit 0, nothing rendered)",
        r.returncode == 0 and "nothing to spawn" in r.stdout and not any(rend.iterdir()), r.stdout + r.stderr)
    rend2 = tmp / "render-plain"
    r = subprocess.run(["bash", str(root / "scripts" / "spawn.sh"), "--render", "plain", str(rend2)],
                       capture_output=True, text=True, timeout=60)
    arm("spawn.sh: an ordinary charter goes on past the guard (it fires on that line only)",
        "nothing to spawn" not in r.stdout + r.stderr and rend2.exists(), r.stdout + r.stderr)

    # ── leave ─────────────────────────────────────────────────────────────────────────────────────
    r = hook("leave", "--data", str(data), "--project", str(project))
    r2, out = start(["claude"])
    arm("leave: removes the marker; the hooks go quiet again",
        r.returncode == 0 and not list((data / "projects").glob("*.json")) and r2.stdout == "", r.stdout)
    arm("gate: prompt-check in an unjoined project says nothing, even in a wrong mode",
        prompt("default", "sess-3") == (0, ""))

    # ── the key is the same in python (hooks) and node (channel/join.mjs) ─────────────────────────
    node = shutil.which("node")
    if node:
        sys.path.insert(0, str(HOOK.parent))
        import astryx_hook                                    # noqa: E402
        js = subprocess.run([node, "--input-type=module", "-e",
                             f"import {{ projectKey }} from {json.dumps((REPO / 'channel' / 'join.mjs').as_uri())};"
                             f"console.log(projectKey({json.dumps(str(project))}))"],
                            capture_output=True, text=True, timeout=30)
        arm("key parity: python project_key == node projectKey (spaces in the path included)",
            js.stdout.strip() == astryx_hook.project_key(project), js.stdout + js.stderr)
    else:
        skipped.append("key parity (no node)")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if fails:
    print(f"FAIL: {fails} arm(s)")
    sys.exit(1)
if skipped:
    print("PARTIAL: not verified: " + ", ".join(skipped))
    sys.exit(77)
print("ALL PASS")
sys.exit(0)
