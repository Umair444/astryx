#!/usr/bin/env python3
"""plan-11859 U5 (D10, a1 F7; a2 #62560): the CLI adapter table is the ONE source of a resident's launch, and the line
spawn types parses, in the pane's shell, to the argv this oracle expects: exactly today's for every value the live
charters use, and ONE argument for a value that isn't shell-safe.

  A1 ARGV over the derived input space: each Model: value the shipped and live charters name (plus haiku, sonnet,
     opus), × both permission modes, × resume on and off. `runtime_env.py --launch` prints a line; bash parses it as
     the pane will (eval "set -- …"); the argv equals THIS oracle's own literal list (never derived from the table),
     and its bytes equal today's line (the secondary pin: every live value is shell-safe)
  A2 a value that isn't safe (a charter's Model: with `;`, a space, `$(…)`, a glob): ONE argument, verbatim, and the
     command it carries never runs (its marker file never exists)
  A3 spawn.sh types the line --launch prints (the send-keys carries "$LINE", LINE is --launch's), refuses when there
     is none, and carries none of the row's resident-only tokens itself
  A4 THE LAUNCH-PATH CENSUS: the claude row's literal tokens, but for the flags other claude launches share (declared
     below with why), appear in no tracked code file outside the table (comments and docstrings dropped; tests/
     excluded), but the plugin hook, the declared mirror (A5). A planted copy of the old literal line is accused
  A5 the plugin hook (standard library only: it runs in any project and can't import astryx) mirrors the row: its
     channel flag, channel server and permission flag ARE the row's
  A6 DERIVATION: runtime_env.CLIS and LAUNCHERS are the table's (gemini's and codex's keys declared, neither a
     launcher); a fixture table with a new CLI and key is CLIS by itself, with no code edit
  A7 a CLI with no launcher: --launch exits 3 and names its why; nothing on stdout
  A8 a table that can't launch on the wire is refused at LOAD, and --launch prints no line (rc ≠ 0): no channel flag,
     no channel server, no {mcp}, a permission flag without {perm}, credentials malformed, a non-launcher with no why
Seams: ASTRYX_CLI_ADAPTERS (a table), CLI_ADAPTERS_SRC (a mutant cli_adapters.py), SPAWN_SRC (a mutant spawn.sh).
Exit 0 · 1.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "devtools"))
from org_census import code_lines  # noqa: E402

PY = sys.executable
fails = []
TODAY = ["{cli}", "{resume}", "--model", "{model}", "--permission-mode", "{perm}", "--disallowedTools", "AskUserQuestion",
         "--strict-mcp-config", "--mcp-config", "{mcp}", "--dangerously-load-development-channels", "server:astryx"]
# flags other claude launches use too (vega's conjure, stationed agents, persona_llm's `claude -p`): not the resident
# launch's signature, so the census leaves them to their own files
SHARED = {"--model", "--permission-mode", "--strict-mcp-config", "--mcp-config"}


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def expected(cli, model, perm, mcp, resume):
    """THIS oracle's argv for today's line, from its own literal TODAY."""
    out = []
    for t in TODAY:
        out += {"{cli}": [cli], "{resume}": ["--resume", resume] if resume else [], "{model}": [model],
                "{perm}": [perm], "{mcp}": [mcp]}.get(t, [t])
    return out


def today_bytes(cli, model, perm, mcp, resume):
    """Today's spawn.sh:382 line, as it typed it (unquoted interpolation)."""
    r = f"--resume {resume} " if resume else ""
    return (f"{cli} {r}--model {model} --permission-mode {perm} --disallowedTools AskUserQuestion --strict-mcp-config "
            f"--mcp-config {mcp} --dangerously-load-development-channels server:astryx")


def child_env(extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ASTRYX_CLI_ADAPTERS", "ASTRYX_ORG_CLI"))}
    env.setdefault("ASTRYX_COG_REGISTRY", "/nonexistent/cog.json")
    env.update(extra or {})
    return env


def launch(model, perm, resume=None, env=None, cli="/fx/bin/claude", mcp="/fx/home/.mcp.json"):
    args = [PY, "-c", SEAT, str(REPO / "src"), str(REPO / "src/astryx/core/runtime_env.py"), "--launch", "--cli", cli, "--model", model, "--perm", perm,
            "--mcp", mcp] + (["--resume", resume] if resume else [])
    return subprocess.run(args, capture_output=True, text=True, timeout=60, env=child_env(env))


def parse(line, cwd):
    """The argv the pane's shell gives the CLI for `line` (spawn types it into an interactive bash)."""
    r = subprocess.run(["bash", "--norc", "--noprofile", "-c", 'eval "set -- $1"; printf "%s\\0" "$@"', "_", line],
                       capture_output=True, text=True, timeout=30, cwd=cwd)
    return [x for x in r.stdout.split("\0") if x != ""] if r.returncode == 0 else None


def charter_models():
    out = set()
    for p in list((REPO / "agents").glob("**/*.md")):   # org-home: the input space, the checkout's charters, as data
        for ln in p.read_text(errors="replace").splitlines():
            if ln.startswith("Model:"):
                v = ln.split(":", 1)[1].strip()
                if v:
                    out.add(v)
    return out


# the child: the real tree, with CLI_ADAPTERS_SRC (a mutant) seated as astryx.core.cli_adapters BEFORE anything imports
# it, under the real file's name (so its data/ path is the real table), then the script asked for, run as __main__
SEAT = ("import os, runpy, sys, types; src = sys.argv.pop(1); sys.path.insert(0, src); mut = os.environ.get("
        "'CLI_ADAPTERS_SRC'); real = src + '/astryx/core/cli_adapters.py'\n"
        "if mut:\n import astryx.core\n m = types.ModuleType('astryx.core.cli_adapters'); m.__file__ = real\n"
        " sys.modules[m.__name__] = m; exec(compile(open(mut).read(), real, 'exec'), m.__dict__)\n"
        "script = sys.argv.pop(1); sys.argv[0] = script; runpy.run_path(script, run_name='__main__')")


def main():
    t = Path(tempfile.mkdtemp(prefix="astryx-cliad-")).resolve()
    try:
        run(t)
    finally:
        shutil.rmtree(t, True)
    print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: one adapter row per CLI, and the line spawn types "
          "is today's argv, every value one argument")
    return 1 if fails else 0


def run(t):
    print("A1 ARGV OVER THE DERIVED INPUT SPACE")
    models = sorted({"haiku", "sonnet", "opus"} | charter_models())
    n = bad = 0
    for model in models:
        for perm in ("bypassPermissions", "default"):
            for resume in (None, "fx-sess-0001"):
                n += 1
                r = launch(model, perm, resume)
                line = r.stdout.rstrip("\n")
                want = expected("/fx/bin/claude", model, perm, "/fx/home/.mcp.json", resume)
                if r.returncode != 0 or parse(line, t) != want or line != today_bytes(
                        "/fx/bin/claude", model, perm, "/fx/home/.mcp.json", resume):
                    bad += 1
                    if bad == 1:
                        print(f"        first miss: {model}/{perm}/{resume}: rc {r.returncode} {line[:160]!r} "
                              f"{r.stderr[-160:]}")
    check(f"{n} cases (models {models}): the parsed argv is the oracle's, and the bytes are today's line", bad == 0,
          f"{bad} differ")

    print("\nA2 A VALUE THAT ISN'T SHELL-SAFE IS ONE ARGUMENT")
    for model in (f"opus; touch {t}/pwned1", "x y", f"$(touch {t}/pwned2)", "opus[1m]", "`touch " + str(t) + "/pwned3`"):
        r = launch(model, "bypassPermissions")
        argv = parse(r.stdout.rstrip("\n"), t)
        check(f"Model: {model.replace(str(t), '$T')!r} reaches the CLI verbatim as one argument, and runs nothing",
              r.returncode == 0 and argv == expected("/fx/bin/claude", model, "bypassPermissions", "/fx/home/.mcp.json",
                                                     None) and not list(t.glob("pwned*")), str(argv)[:200])

    print("\nA3 SPAWN TYPES THE ADAPTER'S LINE")
    sp = Path(os.environ.get("SPAWN_SRC") or REPO / "scripts/spawn.sh")
    code = [c for _, c, _ in code_lines(sp)]
    sends = [c for c in code if "send-keys" in c and "Enter" in c and "$SESS" in c and '"1"' not in c]
    joined = "\n".join(code)
    check("its one launch send-keys types \"$LINE\"", sends == [c for c in sends if '"$LINE" Enter' in c] and len(sends) == 1,
          str(sends))
    check("LINE is runtime_env.py --launch's, and no line means no spawn (exit 1)",
          re.search(r'LINE=\$\("\$PY" "\$ROOT/src/astryx/core/runtime_env\.py" --launch .*\|\| \{[^}]*exit 1; \}',
                    joined, re.S) is not None, "")

    print("\nA4 THE LAUNCH-PATH CENSUS")
    row = json.loads((REPO / "src/astryx/data/cli_adapters.json").read_text())["adapters"]["claude"]
    tokens = sorted({x for x in row["launch"] if not x.startswith("{") and x.startswith(("-", "server:"))} - SHARED)
    files = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True).stdout.split()
    mirror = {"plugin/hooks/astryx_hook.py"}

    def census(extra=()):
        out = {}
        for f in [*files, *extra]:
            p = REPO / f if not os.path.isabs(f) else Path(f)
            if f.startswith("tests/") or f in mirror or p.suffix not in (".py", ".sh", ".mjs", ".js", ".ts", ".tsx") \
                    or not p.is_file():
                continue
            hits = sorted({tok for _, c, _ in code_lines(p) for tok in tokens if tok in c})
            if hits:
                out[f] = hits
        return out
    found = census()
    check(f"the row's resident-only tokens {tokens} are in no code file outside the table (but the declared mirror)",
          tokens and not found, str(found))
    plant = t / "planted_spawn.sh"
    plant.write_text('tmux send-keys -t "=$SESS:" "$CLI --model $MODEL --disallowedTools AskUserQuestion '
                     '--dangerously-load-development-channels server:astryx" Enter\n')
    check("RED control: a planted copy of the old literal line is accused", str(plant) in census([str(plant)]))

    print("\nA5 THE PLUGIN HOOK MIRRORS THE ROW")
    hook = (REPO / "plugin/hooks/astryx_hook.py").read_text()
    m = re.search(r'^CHANNELS_FLAG = "([^"]+)"', hook, re.M)
    check("its CHANNELS_FLAG is the row's channel_flag", m is not None and m.group(1) == row["channel_flag"],
          m.group(1) if m else "absent")
    check("it names the row's channel_server and permission_flag", f'"{row["channel_server"]}"' in hook
          and f'"{row["permission_flag"]}"' in hook)

    print("\nA6 DERIVATION")
    probe = t / "probe_clis.py"
    probe.write_text("import json\nfrom astryx.core import runtime_env as r\n"
                     "print(json.dumps({'clis': {k: {c: list(v) for c, v in d.items()} for k, d in r.CLIS.items()}, "
                     "'launchers': sorted(r.LAUNCHERS)}))\n")

    def derived(env=None):
        p = subprocess.run([PY, "-c", SEAT, str(REPO / "src"), str(probe)], capture_output=True, text=True, timeout=60,
                           env=child_env(env))
        return json.loads(p.stdout) if p.returncode == 0 else {"err": p.stderr[-300:]}
    table = json.loads((REPO / "src/astryx/data/cli_adapters.json").read_text())["adapters"]
    got = derived()
    check("runtime_env.CLIS is every row's credentials, LAUNCHERS every launcher row's (gemini and codex keys "
          "declared, neither a launcher)",
          got.get("clis") == {c: r["credentials"] for c, r in table.items()}
          and got.get("launchers") == sorted(c for c, r in table.items() if r.get("launcher") is True)
          and "gemini" in got.get("clis", {}) and "codex" in got.get("clis", {}) and got.get("launchers") == ["claude"],
          str(got)[:300])
    fx = json.loads(json.dumps(table))
    fx["fxcli"] = {"launcher": False, "why": "fx: not built", "credentials": {"subscription": [], "metered": ["FX_CLI_KEY"]}}
    ft = t / "fx_adapters.json"
    ft.write_text(json.dumps({"adapters": fx}))
    got = derived({"ASTRYX_CLI_ADAPTERS": str(ft)})
    check("a fixture table's new CLI and key are CLIS by themselves (no code edit)",
          got.get("clis", {}).get("fxcli") == {"subscription": [], "metered": ["FX_CLI_KEY"]}, str(got)[:300])

    print("\nA7 A CLI WITH NO LAUNCHER")
    nl = json.loads(json.dumps(table))
    nl["claude"] = {"launcher": False, "why": "fx: claude's launcher withdrawn", "credentials": table["claude"]["credentials"]}
    nt = t / "nolauncher.json"
    nt.write_text(json.dumps({"adapters": nl}))
    r = launch("opus", "bypassPermissions", env={"ASTRYX_CLI_ADAPTERS": str(nt)})
    check("--launch exits 3, names its why, prints no line", r.returncode == 3 and "withdrawn" in r.stderr
          and r.stdout == "", f"rc {r.returncode} {r.stderr[-200:]}")

    print("\nA8 A TABLE THAT CAN'T LAUNCH ON THE WIRE IS REFUSED AT LOAD")
    def broken(name, fn):
        b = json.loads(json.dumps(table))
        fn(b)
        p = t / f"broken_{len(list(t.glob('broken_*')))}.json"
        p.write_text(json.dumps({"adapters": b}))
        r = launch("opus", "bypassPermissions", env={"ASTRYX_CLI_ADAPTERS": str(p)})
        check(f"{name}: no line, rc ≠ 0", r.returncode != 0 and r.stdout == "", f"rc {r.returncode} {r.stdout[:120]!r}")
    broken("no channel flag", lambda b: b["claude"]["launch"].remove("--dangerously-load-development-channels"))
    broken("no channel server", lambda b: b["claude"]["launch"].remove("server:astryx"))
    broken("no {mcp}", lambda b: b["claude"]["launch"].remove("{mcp}"))
    broken("a permission flag without {perm}", lambda b: b["claude"]["launch"].remove("{perm}"))
    broken("credentials malformed", lambda b: b["claude"]["credentials"].pop("metered"))
    broken("a non-launcher with no why", lambda b: b["gemini"].pop("why"))


if __name__ == "__main__":
    sys.exit(main())
