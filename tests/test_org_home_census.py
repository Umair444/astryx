#!/usr/bin/env python3
"""Gate for plan-11324 S3a's census (devtools/org_census.py) and its two declared partitions.

  C1 THE CENSUS IS CLEAN on this tree: no ASTRYX_DSN read outside the resolvers (BC-S1(2)), no checkout-based read of
     an ORG-class estate path and no literal DSN default (BC-S2(2)), no environment-first read of an org name
     (BC-S3(3)), and no .py or .sh file the census can't parse (unscanned is a finding, never "nothing to report").
     Guarded and declared sites are LISTED, with counts. It reads what git doesn't ignore: a gitignored file is the
     org's estate (merge_check links the live one in), never the core's code; a new, not-ignored file is read.
  C2 IT SEES THE CLASS (positive controls): run over the tree BEFORE S3a (PRE_S3A, an archive of it), it finds every
     site the reviewers named: a1's pulse.py DSN, a2's spawn.sh `$ROOT/local.md`, restore_drill.sh's literal default
     and backup.sh's bare `backups/` rotation, a3's people.py computed-name read and contacts' private .env parse.
  C3 THE PARTITION (a4 #58453, a2 #58454): every .gitignore entry is classed org | host | build; an entry with no
     class FAILS (a mutant .gitignore with one extra line goes red); the org class holds local.md, .env and agents/.
  C4 THE ENVIRONMENT'S CLASSES (a4 #58598 (a)): every name in THIS process's environment is classed (host, pane,
     session, home) or is an org name (derived from the code's .env writers and readers, or a key of the HOME's .env);
     no derived org name sits in a PASS class; an unclassed name FAILS (a mutant environment goes red).
  C5 GUARDS RUN FIRST: each guarded file's prefix (through its guard) exits non-zero under a two-org registry and 0
     with none, and nothing executable precedes the guard but the declared preamble.
Seams: ORG_CENSUS_SRC (a mutant census), ORG_HOME_CLASSES_SRC (a mutant org_env.json, for C4) and org_home_fixture.SEAMS (a mutant subject the census reads in place:
ORG_HOME_PULSE_SRC, ORG_HOME_SPAWN_SRC). Exit 0 · 1 · 77 (PRE_S3A absent from this clone: C2 only).
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
from org_home_fixture import seam_overrides  # noqa: E402
PRE_S3A = "cda0351"      # main before plan-11324 S3a: every reviewer-named site is still there
fails = []
src = os.environ.get("ORG_CENSUS_SRC") or str(REPO / "devtools" / "org_census.py")
spec = importlib.util.spec_from_file_location("org_census_under_test", src)
oc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oc)


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def partition_gaps(root: Path) -> list:
    doc = json.loads((root / "src/astryx/data/estate_partition.json").read_text())
    entries = [ln.strip() for ln in (root / ".gitignore").read_text().splitlines()
               if ln.strip() and not ln.lstrip().startswith(("#", "!"))]
    return [e for e in entries if doc["classes"].get(e) not in ("org", "host", "build")]


def main():
    print("C1 THE CENSUS IS CLEAN:")
    # FIRST, on a planted tree: the census reads the CORE's code, never the org's gitignored estate (merge_check links
    # the live estate in: a personal bridge there is the org's own, moved with its estate). A new, untracked,
    # NOT-ignored file is still read.
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "src/astryx/data").mkdir(parents=True)
        for f in ("estate_partition.json", "org_env.json"):
            (t / "src/astryx/data" / f).write_text((REPO / "src/astryx/data" / f).read_text())
        (t / "bridges").mkdir()
        (t / ".gitignore").write_text("bridges/estate_reader.py\n")
        for f in ("estate_reader.py", "new_reader.py"):
            (t / "bridges" / f).write_text('import os\nDSN = os.environ.get("ASTRYX_DSN")\n')   # org-home: a fixture reader the control plants
        # the walk is DERIVED (a2 #58917 R-1): a top-level directory nobody listed is read, by default
        (t / "newroot").mkdir()
        (t / "newroot" / "reader.py").write_text('import os\nDSN = os.environ.get("ASTRYX_DSN")\n')   # org-home: a fixture reader the control plants
        # two shell forms the grammar must read (R-2's vitals.sh): a QUOTED command substitution, and a `:-` default
        (t / "newroot" / "panel.sh").write_text('#!/bin/bash\ncd "$ROOT"\nD="$(ls -t backups/*.dump 2>/dev/null)"\n'
                                                'S="${STAMP:-backups/.last-check}"\n')
        # the namespace axis, kind tmux (S3b): a default-socket tmux in each language, beside its routed twin
        (t / "newroot" / "ns_bare.py").write_text('import subprocess\nsubprocess.run(["tmux", "ls"])\n'   # org-home: a planted default-socket call
                                                  'subprocess.run(["tmux", "-L", "fx", "ls"])\n'
                                                  'TOOLS = ("tmux", "psql")\n')
        (t / "newroot" / "ns_routed.py").write_text('import subprocess\nfrom astryx import orgs\n'
                                                    'subprocess.run([*orgs.tmux(), "ls"])\n')
        (t / "newroot" / "ns_bare.sh").write_text('#!/bin/bash\ntmux ls\necho "run tmux attach -t ax-x"\n'
                                                  'tmux -L fx ls\n')
        (t / "newroot" / "ns_routed.sh").write_text('#!/bin/bash\nROOT=/x\ntmux ls\n. "$ROOT/scripts/org_tmux.sh"\n'
                                                    'tmux ls\nexec tmux attach\n'
                                                    'exec tmux ${AX_SOCK:+-L "$AX_SOCK"} attach\n')
        (t / "newroot" / "ns_spawn.mjs").write_text("import { spawn } from 'node:child_process'\nspawn('tmux', ['ls'])\n")
        # kind unit (4/n): a one-org unit name written out, beside a message that mentions one and a test's expectation
        (t / "newroot" / "ns_unit.py").write_text('TIMER = "astryx-pulse.timer"\n'
                                                  'MSG = "start astryx-pulse.timer when it stops"\n')
        (t / "newroot" / "ns_unit.sh").write_text('#!/bin/bash\nsystemctl start astryx-pulse.timer\n'
                                                  'echo "run: systemctl start astryx-pulse.timer"\n')
        (t / "tests").mkdir()
        (t / "tests" / "test_fx_units.py").write_text('WANT = "astryx-pulse.timer"\n')
        (t / "newroot" / "reader.ts").write_text('const d = process.env.ASTRYX_DSN\n')   # org-home: a planted node-side reader (.ts, a2 #59037)
        subprocess.run(["git", "init", "-q", str(t)], check=True)
        res_t = oc.census(t)
        ns = {(r["file"], r["line"]) for r in res_t["namespace"]}
        check("namespace: a python argv on the default socket is found; -L and a tuple of tool names are not",
              ("newroot/ns_bare.py", 2) in ns and not {("newroot/ns_bare.py", 3), ("newroot/ns_bare.py", 4)} & ns,
              str(sorted(ns)))
        check("namespace: `[*orgs.tmux(), …]` is routed", not any(f == "newroot/ns_routed.py" for f, _ in ns),
              str(sorted(ns)))
        check("namespace: a shell `tmux` is found; a quoted message and an explicit -L are not",
              ("newroot/ns_bare.sh", 2) in ns and not {("newroot/ns_bare.sh", 3), ("newroot/ns_bare.sh", 4)} & ns,
              str(sorted(ns)))
        check("namespace: org_tmux.sh routes only the calls AFTER it is sourced; `exec tmux` bypasses it unless it "
              "spells the socket", {f_l for f_l in ns if f_l[0] == "newroot/ns_routed.sh"}
              == {("newroot/ns_routed.sh", 3), ("newroot/ns_routed.sh", 6)}, str(sorted(ns)))
        check("namespace: a js spawn('tmux') is found", ("newroot/ns_spawn.mjs", 2) in ns, str(sorted(ns)))
        check("namespace/unit: a unit name written out is found (python and shell); a message and a test's "
              "expectation are not", {("newroot/ns_unit.py", 1), ("newroot/ns_unit.sh", 2)} <= ns
              and not {("newroot/ns_unit.py", 2), ("newroot/ns_unit.sh", 3), ("tests/test_fx_units.py", 1)} & ns,
              str(sorted(ns)))
        check("a .ts file is read (a2 #59037: a node-side reader)",
              any(r["file"] == "newroot/reader.ts" for r in res_t["dsn"]), str(sorted(r["file"] for r in res_t["dsn"])))
        hit = sorted(r["file"] for r in res_t["dsn"])
        walk_ok = "bridges/new_reader.py" in hit and "bridges/estate_reader.py" not in hit
        check("a gitignored (estate) file is not read; a new, not-ignored one is (control)", walk_ok, str(hit))
        check("a NEW top-level directory is read by default (the walk is derived from git, never a list of roots)",
              "newroot/reader.py" in hit, str(hit))
        sh = sorted(r["line"] for r in res_t["estate"] if r["file"] == "newroot/panel.sh")
        check("a quoted command substitution (\"$(ls backups/…)\") is code, not a label", 3 in sh, str(sh))
        check("a `${X:-backups/…}` default is a path", 4 in sh, str(sh))

    # the org's TRIGGER BODIES (S3b, a2 #59697 / seed #59699): a planted HOME, the RED control FIRST (#59151's order)
    with tempfile.TemporaryDirectory() as td:
        h = Path(td)
        tdir = h / "triggers" / "fxagent"
        (tdir / "__pycache__").mkdir(parents=True)
        (tdir / "bare.py").write_text('import subprocess\nsubprocess.run(["tmux", "ls"])\n')   # org-home: a planted default-socket trigger
        (tdir / "shell.py").write_text('import os, subprocess\nos.system("tmux ls")\n'
                                       'subprocess.run(f"tmux send-keys -t {x} Enter", shell=True)\n')
        (tdir / "routed.py").write_text('import subprocess\nfrom astryx import orgs\nsubprocess.run([*orgs.tmux(), "ls"])\n')
        (tdir / "advice.py").write_text('print(f"    tmux kill-session -t =ax-{n} && spawn.sh {n}")\n'
                                        'MSG = "restart: tmux kill-session"\n')
        (tdir / "__pycache__" / "bare.py").write_text('import subprocess\nsubprocess.run(["tmux", "ls"])\n')   # org-home: a planted cache copy (skipped)
        (tdir / "notes.sh").write_text("tmux ls\n")
        (tdir / "broken.py").write_text("def x(:\n")          # a body that won't parse fails closed (a2 #59955 A-2)
        got, read = oc.trigger_sites(h)
        hits = sorted((r["file"], r["line"]) for r in got)
        want = [("triggers/fxagent/bare.py", 2), ("triggers/fxagent/broken.py", 0), ("triggers/fxagent/shell.py", 2),
                ("triggers/fxagent/shell.py", 3)]
        check("RED control: a planted trigger body's bare argv, its two shell lines and an unparseable body are found, "
              "nothing else (routed, advice text, __pycache__, a non-.py file)", read and hits == want, str(hits))
        (h / "empty").mkdir()
        got, read = oc.trigger_sites(h / "empty")
        check("a HOME with no triggers/ is SKIPPED (not read), never a pass of an empty set", not read and not got,
              f"{read} {got}")

    if not walk_ok:
        # a walk that reads gitignored files would point the live census at the org's estate (homes/, memory/, tier/:
        # personal files, and minutes of walking: seed #59151). It is never run through a broken walk.
        print("  ·  the live census is NOT run: its walk reads the org's gitignored estate")
        return 1
    res = oc.census(REPO, seam_overrides())
    for k, what in (("dsn", "ASTRYX_DSN read outside the resolvers"), ("estate", "checkout-based estate read / literal "
                    "DSN default"), ("env", "environment-first read of an org name"),
                   ("namespace", "host-wide name (a tmux call on the default socket)"),
                   ("triggers", "default-socket tmux in the org's trigger bodies (HOME/triggers)"),
                   ("unparsed", "file the census can't parse (unscanned: fails closed)")):
        if k == "triggers" and not res["triggers_read"]:
            continue                            # nothing read is not a pass: stated below instead
        check(f"no {what}: {len(res[k])}", not res[k],
              "; ".join(f"{r['file']}:{r['line']} {r['what']}" for r in res[k][:12]))
    if not res["triggers_read"]:
        print("  ·  the org's trigger bodies: NOT READ (this HOME has no triggers/: a worktree; merge_check links them)")
    print(f"  ·  guarded: {len(res['guarded'])} site(s) in {len(res['guarded_files'])} file(s); declared: "
          f"{len(res['declared'])}; org names derived: {len(res['org_names'])}")

    print("\nC2 IT SEES THE CLASS (the tree before S3a):")
    if subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", PRE_S3A + "^{commit}"], capture_output=True).returncode:
        print(f"  SKIP  {PRE_S3A} isn't in this clone")
        pre_ok = False
    else:
        pre_ok = True
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(f"git -C {REPO} archive {PRE_S3A} | tar -x -C {td}", shell=True, check=True)
            # the partition and the environment's classes are S3a's own: the old tree is judged by THESE
            (Path(td) / "src/astryx/data").mkdir(parents=True, exist_ok=True)
            for f in ("estate_partition.json", "org_env.json"):
                (Path(td) / "src/astryx/data" / f).write_text((REPO / "src/astryx/data" / f).read_text())
            old = oc.census(Path(td))
        rows = [r for k in ("dsn", "estate", "env") for r in old[k]]

        def found(f, line=None, kind=None, what=None):
            return any(r["file"] == f and (line is None or r["line"] == line) and (kind is None or r["kind"] == kind)
                       and (what is None or what in r["what"]) for r in rows)
        for label, args in (("a1: pulse.py's private DSN resolver", ("src/astryx/pulse/pulse.py", None, "dsn")),
                            ("a2: spawn.sh:122 `$ROOT/local.md`", ("scripts/spawn.sh", 122, "estate", "local.md")),   # org-home: a label naming the class
                            ("a2: restore_drill.sh:31 `${DSN:-postgresql://…}`", ("scripts/restore_drill.sh", 31,   # org-home: a label naming the class
                                                                                  "estate", "literal DSN")),
                            ("a2: backup.sh:280's bare `backups/` rotation", ("scripts/backup.sh", 280, "estate",
                                                                             "backups/")),
                            ("a3: people.py's computed-name environment read", ("src/astryx/people/people.py", None,
                                                                                "env", "PEOPLE_SALT")),
                            ("a3: contacts' private .env parse on parents[2]", ("mcp/contacts/server.py", None,
                                                                               "estate", ".env"))):
            check(f"finds {label}", found(*args))
        check("...and derives PEOPLE_SALT and WA_CLI as org names (a3's members), from the code alone",
              {"PEOPLE_SALT", "WA_CLI"} <= set(old["org_names"]), str(old["org_names"]))

    print("\nC3 THE PARTITION:")
    gaps = partition_gaps(REPO)
    check("every .gitignore entry is classed org | host | build", not gaps, str(gaps))
    doc = json.loads((REPO / "src/astryx/data/estate_partition.json").read_text())["classes"]
    check("the org class holds local.md, .env and agents/", all(doc.get(e) == "org" for e in ("local.md", ".env",
                                                                                               "agents/*")))
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "src/astryx/data").mkdir(parents=True)
        (t / "src/astryx/data/estate_partition.json").write_text(
            (REPO / "src/astryx/data/estate_partition.json").read_text())
        (t / ".gitignore").write_text((REPO / ".gitignore").read_text() + "\nnewly_ignored_org_file.json\n")
        check("RED control: a gitignored entry nobody classed fails", partition_gaps(t) == ["newly_ignored_org_file.json"],
              str(partition_gaps(t)))

    print("\nC4 THE ENVIRONMENT'S CLASSES:")
    from astryx import config, orgenv, paths
    cls = orgenv.classes()
    if os.environ.get("ORG_HOME_CLASSES_SRC"):   # a mutant org_env.json (tests/mutants_org_census_classes.py)
        doc = json.loads(Path(os.environ["ORG_HOME_CLASSES_SRC"]).read_text())
        cls = {"classes": doc["classes"], "pass": tuple(doc["pass"])}
    derived = set(res["org_names"])
    try:
        held = set(config.read_env(paths.estate(__file__) / ".env"))
    except Exception:  # noqa: BLE001
        held = set()

    def unclassed(names):
        return sorted(n for n in names if orgenv.class_of(n, cls) is None and n not in derived and n not in held)
    check("every name in this process's environment is classed or an org name", not unclassed(os.environ),
          str(unclassed(os.environ)))
    clash = sorted(n for n in derived if orgenv.class_of(n, cls) in cls["pass"])
    check("no org name sits in a PASS class (it would ride into another org's pane)", not clash, str(clash))
    # sets, not ordered lists: an unclassed name already present that sorts after FX_ must not break the control
    check("RED control: an unclassed name in the environment fails",
          set(unclassed({**os.environ, "FX_NOBODY_CLASSED_THIS": "1"})) == set(unclassed(os.environ)) |
          {"FX_NOBODY_CLASSED_THIS"})
    # the environments the gate really runs in, pinned on every tree (medic #59415: the census stamp went red under its
    # own timer, whose TRIGGER_* no class held). The names are systemd.exec(5)'s, typed here, never read from the
    # classes; the ambient environment adds nothing to this arm.
    timer = {"TRIGGER_UNIT": "astryx-fx.timer", "TRIGGER_TIMER_REALTIME_USEC": "1", "TRIGGER_TIMER_MONOTONIC_USEC": "1"}
    check("C4 under a timer's environment: TRIGGER_* adds no unclassed name",
          set(unclassed({**os.environ, **timer})) == set(unclassed(os.environ)),
          str(sorted(set(unclassed({**os.environ, **timer})) - set(unclassed(os.environ)))))
    for shape, names in (("a timer-started service", ("TRIGGER_UNIT", "TRIGGER_TIMER_REALTIME_USEC",
                                                       "TRIGGER_TIMER_MONOTONIC_USEC", "INVOCATION_ID", "JOURNAL_STREAM",
                                                       "SYSTEMD_EXEC_PID")),
                         ("a path-started service", ("TRIGGER_UNIT", "TRIGGER_PATH")),
                         ("an OnFailure= service", ("MONITOR_SERVICE_RESULT", "MONITOR_EXIT_CODE", "MONITOR_EXIT_STATUS",
                                                    "MONITOR_INVOCATION_ID", "MONITOR_UNIT")),
                         ("a notify / watchdog / socket service", ("NOTIFY_SOCKET", "WATCHDOG_PID", "WATCHDOG_USEC",
                                                                    "LISTEN_FDS", "LISTEN_PID", "LISTEN_FDNAMES",
                                                                    "MAINPID", "MANAGERPID")),
                         ("a unit with directories", ("RUNTIME_DIRECTORY", "STATE_DIRECTORY", "CACHE_DIRECTORY",
                                                      "LOGS_DIRECTORY", "CONFIGURATION_DIRECTORY",
                                                      "CREDENTIALS_DIRECTORY"))):
        bad = sorted(n for n in names if orgenv.class_of(n, cls) != "session")
        check(f"{shape}'s names are session (dropped, never passed): {len(names) - len(bad)}/{len(names)}", not bad,
              str(bad))

    print("\nC5 GUARDS RUN FIRST:")
    with tempfile.TemporaryDirectory() as td:
        reg = Path(td) / "orgs.json"
        reg.write_text(json.dumps({"orgs": {"fxa": {"home": str(Path(td) / "a"), "db": "fxorg_a"},
                                            "fxb": {"home": str(Path(td) / "b"), "db": "fxorg_b"}}}))
        for rel in res["guarded_files"]:
            text = (REPO / rel).read_text().splitlines(keepends=True)
            gi = next(i for i, ln in enumerate(text) if oc.GUARD.search(ln))
            end = next(i for i in range(gi, len(text)) if re.match(r"\s*fi\b", text[i]) or
                       (i == gi and re.search(r";\s*fi\s*$", text[i])))
            prefix = "".join(text[:end + 1])
            pre_exec = [ln for ln in text[:gi] if ln.strip() and not ln.lstrip().startswith("#")]
            bad = [ln.strip() for ln in pre_exec if not re.match(
                r"\s*(set -[euo]+|set -euo pipefail|ROOT=|REPO=|PY=|HERE=|_self=|_hops=|_t=|while |done|case |esac|"
                r"cd |unset |\[ |\{|\}|.*\) _self=|if \[ -e \"\$\{ASTRYX_ORG_REGISTRY)", ln)]
            with tempfile.TemporaryDirectory() as wd:
                f = Path(wd) / "prefix.sh"
                f.write_text(prefix.replace("cd \"$(dirname \"$_self\")\"", f"cd {REPO}"))
                env = {k: os.environ[k] for k in ("PATH", "HOME", "USER") if k in os.environ}
                r_multi = subprocess.run(["bash", str(f)], env={**env, "ASTRYX_ORG_REGISTRY": str(reg)}, cwd=REPO,
                                         capture_output=True, text=True, timeout=30)
                r_one = subprocess.run(["bash", str(f)], env={**env, "ASTRYX_ORG_REGISTRY": str(Path(wd) / "none")},
                                       cwd=REPO, capture_output=True, text=True, timeout=30)
            check(f"{rel}: refuses under two orgs ({r_multi.returncode}), passes with none ({r_one.returncode}), "
                  "nothing but preamble before it", r_multi.returncode != 0 and r_one.returncode == 0 and not bad,
                  f"{bad} {r_multi.stderr[-200:]} {r_one.stderr[-200:]}")
    return 1 if fails else (0 if pre_ok else 77)


if __name__ == "__main__":
    rc = main()
    print()
    if rc == 1:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    elif rc == 0:
        print("org census: every org-state read goes through the HOME; the partitions are total")
    sys.exit(rc)
