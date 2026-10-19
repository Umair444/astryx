#!/usr/bin/env python3
"""Oracle: the wall in a cog (scripts/wall.sh --cog, the owner's ask 10-19: "make the cog well integrated … also
wall.sh"). One org: the wall as before. A cog of several orgs: one wall of every org's agents, each pane titled
agent@org and rendered from THAT org's table, its bell ringing THAT org's wire.

A fake checkout runs the REAL wall.sh, wallpane.sh, org_tmux.sh, doorbell.sh and orgs.py against a fixture registry
(the primary `fxp`, its HOME the checkout; `fxl`, a HOME of its own). tmux is REAL, on private servers only: every
run carries a TMUX_TMPDIR of this oracle's own and no TMUX/TMUX_PANE, so neither the default socket nor -L ax-fxl
is ever a resident's. psql is a logging STUB on PATH that answers per database (fxwall_p, fxwall_l).

  W1 one org (no registry): session `wall` on the default socket, panes titled by bare name, the one-org status line,
     C-b m bound straight to doorbell.sh, no pane carrying an ASTRYX_HOME, no `cogwall`
  W2 --cog: session `cogwall` on the PRIMARY's server (the default socket), one pane per agent of every org titled
     agent@org (lab's residents read from lab's own server, -L ax-fxl), each pane's command carrying its org's HOME,
     and each pane RENDERING its org's rows (the stub's "hello from <db> <agent>"), never the other org's; the status
     line names the cog's orgs; a name outside the charter grammar never reaches a pane
  W3 --cog picks: a bare name in every org, agent@org in that org only
  W4 the bell: C-b m is bound to wall.sh --bell; --bell agent@fxl INSERTs to lab's database only, as owner;
     agent@<an org not in the cog> refuses with no INSERT; a bare title rings the one-org doorbell
  W5 a re-run with the same roster JOINS the cog wall (its panes untouched), never rebuilds it
  W6 --cog on one org refuses (exit 1) and says so, building nothing
Seam: WALL_SRC (a mutant wall.sh). Exit 0 pass · 1 fail · 77 (no tmux).
Every wait is on a condition with a deadline that names itself, never on time alone.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
fails = []

PSQL = r"""#!/usr/bin/env bash
a="$*"; echo "psql ${a//$'\n'/ }" >> "$WALL_FX_LOG"
db="${1##*/}"; q="${@: -1}"
case "$q" in
  *"DISTINCT agent"*)
    case "$db" in fxwall_p) printf 'seed\nalpha\n' ;; fxwall_l) printf 'seed\nbeta\nBad;name\n' ;; esac ;;
  *"FROM steps WHERE agent="*)
    a=$(sed -n "s/.*agent='\([^']*\)'.*/\1/p" <<< "$q"); echo "12:00|milestone|hello from $db $a" ;;
esac
exit 0
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def until(what, test, secs=30):
    end = time.time() + secs
    while time.time() < end:
        v = test()
        if v:
            return v
        time.sleep(0.25)
    print(f"        (timed out after {secs}s waiting for {what})")
    return None


def main():
    try:
        import psycopg  # noqa: F401  (the panes' renderer and the bell read each org's database through it)
    except ImportError:
        print("SKIP (77): psycopg not importable by this python")
        return 77
    if not shutil.which("tmux"):
        print("SKIP (77): no tmux")
        return 77
    t = Path(tempfile.mkdtemp(prefix="wcog-")).resolve()
    tmx = Path(tempfile.mkdtemp(prefix="wcog-tmx-", dir="/tmp"))   # a socket path must fit sun_path (108 bytes)
    try:
        root, lab, bin_ = t / "co", t / "lab", t / "bin"
        for d in (root / "scripts", root / "venv" / "bin", lab, bin_):
            d.mkdir(parents=True)
        for name in ("wallpane.sh", "org_tmux.sh", "doorbell.sh"):
            shutil.copy(REPO / "scripts" / name, root / "scripts" / name)
        shutil.copy(Path(os.environ.get("WALL_SRC") or REPO / "scripts" / "wall.sh"), root / "scripts" / "wall.sh")
        for f in (root / "scripts").iterdir():
            f.chmod(0o755)
        (root / "src").symlink_to(REPO / "src")
        (root / "venv" / "bin" / "python").write_text(f'#!/usr/bin/env bash\nexec "{sys.executable}" "$@"\n')
        (root / "venv" / "bin" / "python").chmod(0o755)
        (root / ".env").write_text("ASTRYX_DSN=postgresql://fx@127.0.0.1:5432/fxwall_p\n")
        (lab / ".env").write_text("ASTRYX_DSN=postgresql://fx@127.0.0.1:5432/fxwall_l\n")
        (bin_ / "psql").write_text(PSQL)
        (bin_ / "psql").chmod(0o755)
        reg = t / "cog.json"
        reg.write_text(json.dumps({"orgs": {
            "fxp": {"home": str(root), "db": "fxwall_p", "primary": True, "door": True},
            "fxl": {"home": str(lab), "db": "fxwall_l"}}}))
        log = t / "log"
        # built from nothing: no TMUX/TMUX_PANE (a bare tmux would follow it to the caller's own server)
        base = {"PATH": f"{bin_}:{os.environ['PATH']}", "HOME": str(t), "WALL_FX_LOG": str(log),
                "TMPDIR": str(t), "TMUX_TMPDIR": str(tmx), "TERM": "xterm-256color", "LANG": "C.UTF-8"}
        one = {**base, "ASTRYX_COG_REGISTRY": str(t / "no-registry.json")}
        cog = {**base, "ASTRYX_COG_REGISTRY": str(reg), "ASTRYX_HOME": str(root)}

        def tmux(*args, sock="default"):
            p = subprocess.run(["tmux", "-L", sock, *args], env=base, capture_output=True, text=True, timeout=20)
            return p.stdout

        def wall(*args, env):
            log.write_text("")
            return subprocess.run(["bash", str(root / "scripts" / "wall.sh"), *args], env=env, cwd=str(root),
                                  capture_output=True, text=True, timeout=120)

        def panes(s):
            out = tmux("list-panes", "-t", s, "-F", "#{pane_id}|||#{pane_title}|||#{pane_start_command}")
            return [ln.split("|||", 2) for ln in out.splitlines() if ln]

        def bound_m():
            # `list-keys -T prefix m` prints nothing on tmux 3.7: the table's own line for m
            return "".join(ln for ln in tmux("list-keys", "-T", "prefix").splitlines() if ln.split()[3:4] == ["m"])

        def shown(pid):
            return tmux("capture-pane", "-p", "-t", pid)

        print("W1 ONE ORG: THE WALL AS BEFORE")
        p = wall(env=one)
        ps = panes("wall")
        check("session `wall` on the default socket, panes seed and alpha by bare name",
              sorted(x[1] for x in ps) == ["alpha", "seed"], f"rc {p.returncode} {ps} {(p.stdout + p.stderr)[-300:]}")
        check("no pane carries an ASTRYX_HOME", ps and not any("ASTRYX_HOME" in x[2] for x in ps), str(ps))
        check("the one-org status line", "astryx wall │ mirror" in tmux("show", "-t", "wall", "-v", "status-left"))
        keys = bound_m()
        check("C-b m runs doorbell.sh straight", "scripts/doorbell.sh #{pane_title}" in keys
              and "--bell" not in keys, keys)
        check("no cogwall session", "cogwall" not in tmux("ls", "-F", "#{session_name}"))
        tmux("kill-session", "-t", "wall")

        print("\nW6 --cog ON ONE ORG REFUSES")
        p = wall("--cog", env=one)
        check("exit 1, it says this host runs one org, nothing built",
              p.returncode == 1 and "one org" in p.stdout and not tmux("ls", "-F", "#{session_name}").strip(),
              f"rc {p.returncode} {p.stdout + p.stderr}")

        print("\nW2 --cog: EVERY ORG'S AGENTS, EACH FROM ITS OWN TABLE")
        subprocess.run(["tmux", "-L", "ax-fxl", "new-session", "-d", "-s", "ax-gamma", "sleep 600"], env=base,
                       check=True, timeout=20)      # a lab resident with no steps yet: read from LAB's server
        p = wall("--cog", env=cog)
        ps = panes("cogwall")
        titles = sorted(x[1] for x in ps)
        check("session cogwall on the primary's (default) server, one pane per agent of every org, agent@org",
              titles == ["alpha@fxp", "beta@fxl", "gamma@fxl", "seed@fxl", "seed@fxp"],
              f"rc {p.returncode} {titles} {(p.stdout + p.stderr)[-400:]}")
        check("the lab resident came from lab's own server (-L ax-fxl), never the primary's",
              "ax-gamma" not in tmux("ls", "-F", "#{session_name}"))
        check("a name outside the charter grammar never reaches a pane", not any("bad" in x[1].lower() for x in ps))
        homes = {x[1]: x[2] for x in ps}
        check("each pane's command carries ITS org's HOME",
              ps and all((f"ASTRYX_HOME={lab}" if ti.endswith("@fxl") else f"ASTRYX_HOME={root}") in c
                         and (f"ASTRYX_HOME={root}" if ti.endswith("@fxl") else f"ASTRYX_HOME={lab}") not in c
                         for ti, c in homes.items()), str(homes))
        want = {"seed@fxp": "hello from fxwall_p seed", "alpha@fxp": "hello from fxwall_p alpha",
                "seed@fxl": "hello from fxwall_l seed", "beta@fxl": "hello from fxwall_l beta"}
        ids = {x[1]: x[0] for x in ps}
        got = until("every pane to render its own org's row",
                    lambda: all(w in shown(ids.get(ti, "%none")) for ti, w in want.items()), 40)
        check("each pane RENDERS its org's rows (seed@fxp from fxwall_p, seed@fxl from fxwall_l)", bool(got),
              str({ti: shown(ids.get(ti, "%none")).strip()[:80] for ti in want}))
        check("never the other org's: seed@fxl shows no fxwall_p row, seed@fxp no fxwall_l row",
              "fxwall_p" not in shown(ids.get("seed@fxl", "%none")) and "fxwall_l" not in shown(ids.get("seed@fxp", "%none")))
        sl = tmux("show", "-t", "cogwall", "-v", "status-left")
        check("the status line names the cog: fxl · fxp", "astryx cog" in sl and "fxl · fxp" in sl, sl)

        print("\nW5 A RE-RUN JOINS, NEVER REBUILDS")
        before = sorted(x[0] for x in panes("cogwall"))
        wall("--cog", env=cog)
        check("the same roster: the cog wall's panes are untouched", sorted(x[0] for x in panes("cogwall")) == before)

        print("\nW4 THE BELL RINGS THE PANE'S OWN ORG")
        keys = bound_m()
        check("C-b m is bound to wall.sh --bell #{pane_title}", "scripts/wall.sh --bell #{pane_title}" in keys, keys)
        p = wall("--bell", "beta@fxl", "hi there", env={**cog, "ASTRYX_HOME": str(root)})
        ins = [c for c in log.read_text().splitlines() if "INSERT" in c]
        check("--bell beta@fxl: one INSERT, to beta as owner, on lab's database only",
              p.returncode == 0 and len(ins) == 1 and "/fxwall_l " in ins[0] and "'owner', 'beta'" in ins[0]
              and "hi there" in ins[0], f"rc {p.returncode} {ins} {p.stderr[-200:]}")
        p = wall("--bell", "seed@nope", "hi", env=cog)
        check("an org not in the cog refuses, with no INSERT", p.returncode != 0 and "INSERT" not in log.read_text(),
              f"rc {p.returncode} {p.stderr}")
        p = wall("--bell", "seed", "plain", env=one)
        ins = [c for c in log.read_text().splitlines() if "INSERT" in c]
        check("a bare title (one org): the one-org doorbell, this checkout's database",
              p.returncode == 0 and len(ins) == 1 and "/fxwall_p " in ins[0] and "'owner', 'seed'" in ins[0], str(ins))

        print("\nW3 --cog PICKS")
        p = wall("--cog", "--rebuild", "seed@fxl", "alpha", env=cog)
        titles = sorted(x[1] for x in panes("cogwall"))
        check("seed@fxl (lab only) and alpha (every org that has one)", titles == ["alpha@fxp", "seed@fxl"],
              f"{titles} {(p.stdout + p.stderr)[-200:]}")
        return 1 if fails else 0
    finally:
        for sock in ("default", "ax-fxl"):
            subprocess.run(["tmux", "-L", sock, "kill-server"], env={"PATH": os.environ["PATH"], "TMUX_TMPDIR": str(tmx)},
                           capture_output=True, timeout=20)
        shutil.rmtree(t, ignore_errors=True)
        shutil.rmtree(tmx, ignore_errors=True)


if __name__ == "__main__":
    rc = main()
    print()
    if rc == 1:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    elif rc == 0:
        print("wall cog: one wall of every org's agents, each pane from its own org's table, each bell to its own org")
    sys.exit(rc)
