#!/usr/bin/env python3
"""plan-11324 S3b (#58435, HOST-WIDE NAMESPACES), kind tmux: `ax-<agent>` is a name the HOST shares, so on a host
that runs several orgs two orgs' `seed` were ONE session (the second spawn read "already resident" and stopped).
Each org's residents now live on a tmux server of their own, `-L ax-<org>` (src/astryx/orgs.py socket, the ONE
resolver; shell callers source scripts/org_tmux.sh). One org (no registry): the default socket, byte for byte.

  R1 one org: orgs.tmux() is ["tmux"]; `orgs.py socket` exits 1 and prints nothing; org_tmux.sh asks nothing (a
     ROOT with no python at all still gets its `tmux`)
  R2 several orgs: HOME-A's socket is ax-<A>, HOME-B's is ax-<B>; with no HOME carried both doors REFUSE (exit 2),
     never the default socket as a guess
  N1 BOTH orgs spawn the SAME agent name: both come up resident, each on its own org's server (B's spawn does not
     read A's session as its own). Positive control: a second spawn in the SAME org still reads "already resident"
  N2 a pane action reaches only its org: context_compact's /compact, sent from org A's environment, lands in A's
     pane and not in B's; agent_heal's body listing from A holds A's extra body, from B it doesn't
  N3 the one-body guard is per org: a channel-server body of the agent carrying HOME-A does NOT stop B's spawn;
     it DOES stop A's (positive control)

The residents are fixture ones: an ASTRYX_CLI stub (it prints spawn's boot marker, then echoes what it's typed),
on the fixture orgs' own servers, which the fixture kills at exit. All of it runs under a PRIVATE TMUX_TMPDIR, so the
"default socket" the arms ask about is this test's own: a mutant that drops the socket spawns there, never beside the
host's residents. The stand-in body is a `sleep` named like a channel server; nothing here
reads another process's /proc/<pid>/environ (spawn.sh does, as it always has).

Seams (org_home_fixture.SEAMS): ORG_HOME_SPAWN_SRC, ORG_HOME_ORGS_SRC, ORG_HOME_ORGTMUX_SRC,
ORG_HOME_COMPACT_SRC, ORG_HOME_HEAL_SRC. Exit 0 · 1 · 77 (no tmux, no fixture).
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from org_home_fixture import FixtureUnavailable, OrgHomes, private_tmux  # noqa: E402

fails = []
AGENT = f"fxns-{os.getpid()}"
ONLY_A = f"fxns-only-a-{os.getpid()}"

STUB = """#!/bin/bash
echo "bypass permissions"
exec cat
"""

PROBE = r"""
import sys
sys.path.insert(0, sys.argv[1] + "/src")
from astryx import orgs
print(" ".join(orgs.tmux()))
"""

PANE_ACT = r"""
import importlib.util, sys
sys.path.insert(0, sys.argv[1] + "/src")
def load(rel, name):
    s = importlib.util.spec_from_file_location(name, sys.argv[1] + "/" + rel); m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m); return m
if sys.argv[2] == "compact":
    cc = load("src/astryx/pulse/shipped_triggers/context_compact.py", "cc_under_test")
    print("sent" if cc._send_compact(sys.argv[3]) else "not-sent")
else:
    h = load("src/astryx/pulse/shipped_triggers/agent_heal.py", "heal_under_test")
    print(" ".join(sorted(h.bodies() or [])))
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def main():
    if not shutil.which("tmux"):
        print("SKIP (77): no tmux")
        return 77
    tdir = private_tmux()          # every server here, the "default" one included, is private: a mutant that drops the
    try:                           # socket reaches THIS directory's default server, never the host's residents
        fx = OrgHomes().__enter__()
    except FixtureUnavailable as e:
        shutil.rmtree(tdir, ignore_errors=True)
        print(f"SKIP (77): {e}")
        return 77
    body = None
    try:
        co, A, B = fx.co, fx.home["a"], fx.home["b"]
        py = str(co / "venv" / "bin" / "python")
        stub = fx.t / "cli_stub.sh"
        stub.write_text(STUB)
        stub.chmod(0o755)
        for h in (A, B):
            (h / "agents" / f"{AGENT}.md").write_text(f"# {AGENT}\nA fixture resident, the same name in both orgs.\n")

        def env(o=None, **over):
            return fx.env(ASTRYX_HOME=str(fx.home[o]) if o else None, ASTRYX_CLI=str(stub), **over)

        def tmux_of(o):
            return subprocess.run([py, "-c", PROBE, str(co)], env=env(o), cwd="/", capture_output=True, text=True,
                                  timeout=30)

        def socket_door(e):
            return subprocess.run([py, str(co / "src/astryx/orgs.py"), "socket"], env=e, cwd="/",
                                  capture_output=True, text=True, timeout=30)

        def lib(e, root):
            return subprocess.run(["bash", "--norc", "--noprofile", "-c",
                                   'ROOT=$1; . "$ROOT/scripts/org_tmux.sh"; echo "sock=[$AX_SOCK]"; type -t tmux',
                                   "lib", str(root)], env=e, cwd="/", capture_output=True, text=True, timeout=30)

        print("R1 ONE ORG: THE DEFAULT SOCKET, BYTE FOR BYTE")
        one = fx.env(ASTRYX_ORG_REGISTRY=str(fx.t / "no-registry.json"))
        r = subprocess.run([py, "-c", PROBE, str(co)], env=one, cwd=str(co), capture_output=True, text=True, timeout=30)
        check("orgs.tmux() is exactly ['tmux']", r.stdout.strip() == "tmux", r.stdout + r.stderr[-200:])
        r = socket_door(one)
        check("`orgs.py socket` exits 1 and prints nothing", r.returncode == 1 and not r.stdout, f"{r.returncode} "
              f"{r.stdout!r}")
        bare = fx.t / "bare-root"                # a ROOT with no python at all: one org asks nothing of it
        (bare / "scripts").mkdir(parents=True)
        shutil.copy(co / "scripts" / "org_tmux.sh", bare / "scripts" / "org_tmux.sh")
        r = lib(one, bare)
        check("org_tmux.sh: no socket, a `tmux` function, and no python asked (a ROOT without one)",
              r.returncode == 0 and "sock=[]" in r.stdout and "function" in r.stdout, r.stdout + r.stderr[-200:])

        print("\nR2 SEVERAL ORGS: EACH ORG'S OWN SERVER, OR A REFUSAL")
        ta, tb = tmux_of("a"), tmux_of("b")
        check(f"HOME-A's tmux is -L ax-{fx.org['a']}", ta.stdout.split() == fx.tmux("a"), ta.stdout + ta.stderr[-200:])
        check(f"HOME-B's tmux is -L ax-{fx.org['b']}", tb.stdout.split() == fx.tmux("b"), tb.stdout + tb.stderr[-200:])
        r = socket_door(env("a"))
        check("`orgs.py socket` under HOME-A prints its socket (exit 0)",
              r.returncode == 0 and r.stdout.strip() == f"ax-{fx.org['a']}", f"{r.returncode} {r.stdout!r}")
        r = socket_door(fx.env())
        check("no HOME carried: `orgs.py socket` REFUSES (exit 2)", r.returncode == 2, f"{r.returncode} {r.stdout!r}")
        r = lib(fx.env(), co)
        check("no HOME carried: org_tmux.sh REFUSES (exit 2), never the default socket",
              r.returncode == 2 and "sock=" not in r.stdout, f"{r.returncode} {r.stdout!r}")
        r = tmux_of(None)
        check("no HOME carried: orgs.tmux() raises", r.returncode != 0 and "NoHome" in r.stderr, r.stderr[-200:])

        def spawn(o):
            return subprocess.run(["bash", str(co / "scripts" / "spawn.sh"), AGENT], env=env(o), cwd="/",
                                  capture_output=True, text=True, timeout=150)

        def has(o):
            return subprocess.run([*fx.tmux(o), "has-session", "-t", f"=ax-{AGENT}"], capture_output=True).returncode

        print("\nN3 THE ONE-BODY GUARD IS PER ORG")
        # a body of the agent that runs OUTSIDE tmux (a founder CLI's channel server), carrying HOME-A
        body = subprocess.Popen(["bash", "-c", 'exec -a "node channel/server.mjs fxns" sleep 300'],
                                env={**env("a"), "ASTRYX_AGENT": AGENT}, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        rb = spawn("b")
        check("A's out-of-tmux body does NOT stop org B's spawn of the same name", rb.returncode == 0
              and "resident" in rb.stdout and "live body" not in rb.stdout, (rb.stdout + rb.stderr)[-400:])
        ra = spawn("a")
        check("positive control: it DOES stop org A's own spawn", ra.returncode != 0 and "live body" in ra.stdout,
              (ra.stdout + ra.stderr)[-400:])
        body.kill()
        body.wait()
        body = None

        print("\nN1 TWO ORGS, ONE AGENT NAME, TWO RESIDENTS")
        ra = spawn("a")
        check("org A's spawn of the same name comes up resident (not B's session read as its own)",
              ra.returncode == 0 and "resident" in ra.stdout and "already resident" not in ra.stdout,
              (ra.stdout + ra.stderr)[-400:])
        check(f"ax-{AGENT} is live on A's server", has("a") == 0)
        check(f"ax-{AGENT} is live on B's server", has("b") == 0)
        d = subprocess.run(["tmux", "has-session", "-t", f"=ax-{AGENT}"], env=fx.env(), capture_output=True).returncode   # org-home: the PRIVATE default socket (fx.env: TMUX_TMPDIR, and no inherited $TMUX)
        check("...and on neither org's behalf on the default socket", d != 0)
        again = spawn("a")
        check("positive control: a second spawn in the SAME org reads 'already resident'",
              again.returncode == 0 and "already resident" in again.stdout, (again.stdout + again.stderr)[-300:])

        print("\nN2 A PANE ACTION REACHES ONLY ITS ORG")
        subprocess.run([*fx.tmux("a"), "new-session", "-d", "-s", f"ax-{ONLY_A}", "sleep 300"], check=True)

        def act(o, *a):
            return subprocess.run([py, "-c", PANE_ACT, str(co), *a], env=env(o), cwd="/", capture_output=True,
                                  text=True, timeout=60)

        def pane(o):
            return subprocess.run([*fx.tmux(o), "capture-pane", "-p", "-t", f"=ax-{AGENT}:"], capture_output=True,
                                  text=True).stdout

        time.sleep(1)
        before_b = pane("b").count("/compact")
        r = act("a", "compact", AGENT)
        check("context_compact from org A's environment sends", r.stdout.strip() == "sent", r.stdout + r.stderr[-300:])
        deadline = time.time() + 10
        while time.time() < deadline and "/compact" not in pane("a"):
            time.sleep(0.3)
        check("...and /compact lands in A's pane", "/compact" in pane("a"), pane("a")[-300:])
        check("...and NOT in B's pane", pane("b").count("/compact") == before_b, pane("b")[-300:])
        la, lb = act("a", "bodies").stdout.split(), act("b", "bodies").stdout.split()
        check("agent_heal's bodies() from A: both A bodies", set(la) == {AGENT, ONLY_A}, str(la))
        check("agent_heal's bodies() from B: B's one body, never A's", set(lb) == {AGENT}, str(lb))
        return 1 if fails else 0
    finally:
        if body is not None:
            body.kill()
            body.wait()
        fx.__exit__(None, None, None)
        # THIS test's private default server, by its PATH: a bare `tmux kill-server` would follow an inherited $TMUX
        # (a test run from inside a resident's pane) to the host's real server
        subprocess.run(["tmux", "-S", str(tdir / f"tmux-{os.getuid()}" / "default"), "kill-server"], capture_output=True)
        shutil.rmtree(tdir, ignore_errors=True)


if __name__ == "__main__":
    rc = main()
    print()
    if rc == 1:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    elif rc == 0:
        print("org home namespace: each org's residents live on its own tmux server; one org is the default socket")
    sys.exit(rc)
