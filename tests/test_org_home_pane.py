#!/usr/bin/env python3
"""Oracle for a3's HARD BC-S3 (#58597) with a4's precision (#58598): on a multi-org host an org process's environment
is BUILT, never inherited. Keyed to what owns the property: the resident's PANE, not spawn's process.

  P1 A tmux server on a PRIVATE socket is started from an "org-A operator shell" (WA_CLI, PEOPLE_SALT, ASTRYX_ORG,
     ASTRYX_DSN = A's, PGHOST: sentinels) and given PEOPLE_SALT in its GLOBAL environment too; spawn.sh (whose own
     environment carries the same sentinels) then creates an org-B resident on that socket. What the resident's CLI
     runs with holds NONE of A's names, ASTRYX_HOME = HOME-B, ASTRYX_DSN = B's own DSN.
     Positive control: the server's global environment DID hold A's sentinel (the premise is real).
  P2 FUNCTIONAL (a4 (b)): the built resident still works: its PATH, HOME and USER are the spawner's (so node found
     through mise and git resolve), a git operation on its checkout succeeds, and the node spawn wrote into .mcp.json
     runs. NOT TESTED HERE: a real claude harness booting in the built pane (it would spend a session); the declared
     swappable seam ASTRYX_CLI (spawn.sh) runs a stub that records its environment's NAMES (and only the home class's
     values), so the property is proven of what the pane hands its CLI, not of claude's own startup.

WHERE IT LOOKS: the CLI stub is a child of the pane's shell, which exports everything it was given and reads no rc
file (bash --norc --noprofile), so its names are a superset of the pane process's. It reads its OWN environment;
nothing here reads another process's /proc/<pid>/environ (a standing rule of this builder), and the sentinels and
fixture DSNs carry no secret.

Seams: org_home_fixture.SEAMS (a mutant copied over its file in the fixture checkout): ORG_HOME_SPAWN_SRC,
ORG_HOME_ORGENV_SRC, ORG_HOME_CLASSES_SRC. Exit 0 · 1 · 77 (no DB, no git, no tmux).
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from org_home_fixture import FixtureUnavailable, OrgHomes  # noqa: E402

fails = []
A_NAMES = ("WA_CLI", "PEOPLE_SALT", "ASTRYX_ORG", "PGHOST")
AGENT = "fxorgb-pane"


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


STUB = r"""#!/bin/bash
# the resident's CLI (ASTRYX_CLI): record what it runs with, prove it can work, then sit like a booted harness
out="$ORG_HOME_STUB_OUT_DIR_PLACEHOLDER"
{ compgen -e | sort; } > "$out/names.tmp" && mv "$out/names.tmp" "$out/names"
for k in ASTRYX_HOME ASTRYX_DSN ASTRYX_AGENT PATH HOME USER; do printf '%s=%s\n' "$k" "${!k-<unset>}"; done > "$out/home"
git -C "$CO_PLACEHOLDER" rev-parse --verify -q HEAD >/dev/null 2>&1; echo "git=$?" > "$out/work"
node_cmd=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["mcpServers"]["astryx"]["command"])' .mcp.json 2>/dev/null)
"$node_cmd" --version >/dev/null 2>&1; echo "node=$?" >> "$out/work"
echo "bypass permissions"
sleep 600
"""


def main():
    real_tmux = shutil.which("tmux")
    if not real_tmux:
        print("SKIP (77): no tmux")
        return 77
    try:
        fx = OrgHomes().__enter__()
    except FixtureUnavailable as e:
        print(f"SKIP (77): {e}")
        return 77
    sock = f"ax-fxorghome-{os.getpid()}"
    try:
        co, A, B = fx.co, fx.home["a"], fx.home["b"]
        (B / "agents" / f"{AGENT}.md").write_text(f"# {AGENT}\nA fixture resident of fixture org b.\n")
        shim = fx.t / "shim"
        shim.mkdir()
        (shim / "tmux").write_text(f"#!/bin/sh\nexec {real_tmux} -L {sock} \"$@\"\n")
        (shim / "tmux").chmod(0o755)
        out = fx.t / "stub-out"
        out.mkdir()
        stub = fx.t / "cli_stub.sh"
        stub.write_text(STUB.replace("$ORG_HOME_STUB_OUT_DIR_PLACEHOLDER", str(out)).replace("$CO_PLACEHOLDER", str(co)))
        stub.chmod(0o755)
        path = f"{shim}:{os.environ.get('PATH', '/usr/bin:/bin')}"
        sentinels = {"WA_CLI": "SENTINEL-A", "PEOPLE_SALT": "SENTINEL-A", "ASTRYX_ORG": "SENTINEL-A",
                     "PGHOST": "sentinel-a.invalid", "ASTRYX_DSN": fx.dsn["a"]}
        # the org-A operator shell starts the server; the server's global environment is what panes inherit
        subprocess.run([real_tmux, "-L", sock, "new-session", "-d", "-s", "fxa-hold", "sleep 600"],
                       env=fx.env(PATH=path, ASTRYX_HOME=str(A), **sentinels), check=True, timeout=30)
        subprocess.run([real_tmux, "-L", sock, "set-environment", "-g", "PEOPLE_SALT", "SENTINEL-A"], check=True)
        g = subprocess.run([real_tmux, "-L", sock, "show-environment", "-g", "PEOPLE_SALT"], capture_output=True,
                           text=True).stdout.strip()
        check("positive control: the tmux server's GLOBAL environment holds A's sentinel (what -e can't remove)",
              g == "PEOPLE_SALT=SENTINEL-A", g)
        spawner = fx.env(PATH=path, ASTRYX_HOME=str(B), ASTRYX_CLI=str(stub), **sentinels)
        r = subprocess.run(["bash", str(co / "scripts" / "spawn.sh"), AGENT], env=spawner, cwd="/",
                           capture_output=True, text=True, timeout=150)
        check("spawn.sh brings the org-B resident up on the private socket", r.returncode == 0
              and "resident" in r.stdout, (r.stdout + r.stderr)[-400:])
        deadline = time.time() + 30
        while time.time() < deadline and not ((out / "names").is_file() and (out / "work").is_file()
                                              and len((out / "work").read_text().splitlines()) >= 2):
            time.sleep(0.5)
        names = set((out / "names").read_text().split()) if (out / "names").is_file() else set()
        home = dict(ln.split("=", 1) for ln in (out / "home").read_text().splitlines()) if (out / "home").is_file() else {}
        work = dict(ln.split("=", 1) for ln in (out / "work").read_text().splitlines()) if (out / "work").is_file() else {}

        print("P1 BUILT, NEVER INHERITED:")
        check("the resident's CLI ran (it recorded its environment)", bool(names), str(sorted(out.iterdir())))
        leaked = sorted(n for n in A_NAMES if n in names)
        check("NONE of A's names reach it (WA_CLI, PEOPLE_SALT, ASTRYX_ORG, PGHOST)", names and not leaked, str(leaked))
        check("ASTRYX_HOME = HOME-B", home.get("ASTRYX_HOME") == str(B), home.get("ASTRYX_HOME"))
        check("ASTRYX_DSN = B's own DSN, set from HOME-B/.env (never A's inherited one)",
              home.get("ASTRYX_DSN") == fx.dsn["b"], "differs" if home.get("ASTRYX_DSN") else "unset")
        check("ASTRYX_AGENT = the resident", home.get("ASTRYX_AGENT") == AGENT, home.get("ASTRYX_AGENT"))
        sys.path.insert(0, str(REPO / "src"))
        from astryx import orgenv
        cls = orgenv.classes()
        stray = sorted(n for n in names if orgenv.class_of(n, cls) not in (*cls["pass"], "home", "session"))
        check("every name it carries is in a PASS class, the home class, or set by its own shell (session)",
              not stray, str(stray))

        print("\nP2 IT STILL WORKS:")
        for k in ("PATH", "HOME", "USER"):
            check(f"{k} is the spawner's (host class, passed)", home.get(k) == spawner.get(k), f"{home.get(k)!r}")
        check("a git operation on its checkout succeeds", work.get("git") == "0", str(work))
        check("the node spawn.sh wrote into .mcp.json runs (the channel server's interpreter resolves)",
              work.get("node") == "0", str(work))
        return 1 if fails else 0
    finally:
        subprocess.run([real_tmux, "-L", sock, "kill-server"], capture_output=True)
        fx.__exit__(None, None, None)


if __name__ == "__main__":
    rc = main()
    print()
    if rc == 1:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    elif rc == 0:
        print("org home pane: an org-B resident's environment is built from HOME-B, with none of org A's names")
    sys.exit(rc)
