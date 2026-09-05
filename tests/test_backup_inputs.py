#!/usr/bin/env python3
"""Every gitignored INPUT is captured by the backup — the class, not the instance.

THE DEFECT THIS EXISTS FOR, THREE TIMES NOW. `backups/*.state.tgz` carries the state that
lives in no repo and cannot be regenerated. It was created because the pg_dump captured
the triggers TABLE while its rows pointed at FILES in no repo. Then `agents/` turned out
to be missing the same way (2026-08-14). Then `nucleus/runners.conf` (2026-08-20), and
behind it `local.md` — THE ORG'S LAW — and `.env`, which holds the Ed25519 federation
identity that peers have already introduced themselves to and which therefore cannot be
regenerated at all. Each time the fix was to add one more name to a hand-kept list, and
each time the list was the thing that went stale.

So this gate does not check the list. It DERIVES what should be captured from a different
authority — `git status --ignored`, the same rules that decide what is absent from the
repo in the first place — and subtracts a manifest of the genuinely REGENERABLE. Whatever
remains is authored state, and it must be captured.

POLARITY, and it is the whole design: membership in REGENERABLE grants EXEMPTION, so
forgetting to add a member means the path is ACCUSED, not silently trusted. A manifest of
what-to-capture would have exactly the failure mode that produced all three instances —
forget, and the gate stays green while the file stays uncopied. Omission must be the safe
direction, and it only is when the manifest excuses rather than covers.

INDEPENDENCE: the actual capture set comes from `backup.sh --list-state`, i.e. we ASK the
emitter, never re-parse it. A verifier that read the file list out of backup.sh's source
would prove only that the script agrees with itself.

Exit 0 pass · 1 fail · 77 the gate could not run.
"""
import subprocess
import sys
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAIL, SKIP = [], []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def skip(name, why):
    print(f"  SKIP  {name}  — {why}")
    SKIP.append(f"{name} ({why})")


# ── the REGENERABLE manifest: membership grants EXEMPTION, so omission accuses ────────
# Every entry states what regenerates it. If you cannot name the producer, it is not
# regenerable and it belongs in the backup instead of here.
REGENERABLE = {
    "venv/":                          "pip install -r requirements.txt",
    "channel/node_modules/":          "npm install",
    "observatory/web/node_modules/":  "npm install",
    "observatory/web/dist/":          "npm run build (deploy.sh web)",
    "observatory/web/tsconfig.tsbuildinfo": "tsc build artifact",
    "units/":                         "init.sh units() regenerates from runners.conf",
    "backups/":                       "the artifact itself — capturing it would recurse",
    "homes/":                         "spawn.sh regenerates .mcp.json/settings.json; "
                                      "transcripts are large and deliberately excluded",
    "media/":                         "re-fetchable from the source chats",
    "harness/corpus/":                "test fixtures, reproducible",
    "harness/results/":               "test output",
    "var/":                           "derived runtime state (tokenwatch highwater, usage cache)",
    "harness/cell/canary/step.py":    "copied from hooks/step.py by harness/cell/build.sh",
}


def is_regenerable(path: str) -> bool:
    if "__pycache__" in path or path.endswith((".pyc", ".tsbuildinfo")):
        return True
    for r in REGENERABLE:
        rr = r.rstrip("/")
        if path == rr or path.startswith(rr + "/"):
            return True
    return False


def covered_by(path: str, captured: set) -> bool:
    """Captured as itself or under a captured ancestor — `agents/forge/` is covered by
    `agents`, which is how the directory captures have always worked."""
    p = path.rstrip("/")
    while p:
        if p in captured:
            return True
        p = p.rsplit("/", 1)[0] if "/" in p else ""
    return False


def main():
    print("backup captures every gitignored INPUT (goal: the class, not the instance)\n")

    r = subprocess.run(["git", "status", "--ignored", "--porcelain"],
                       cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        skip("derive ignored paths from git", "git status failed")
        return verdict()
    ignored = [l[3:].strip() for l in r.stdout.splitlines() if l.startswith("!!")]
    if not ignored:
        skip("derive ignored paths from git", "no ignored paths reported")
        return verdict()

    r2 = subprocess.run(["bash", str(REPO / "nucleus" / "backup.sh"), "--list-state"],
                        cwd=REPO, capture_output=True, text=True)
    if r2.returncode != 0:
        skip("ask backup.sh what it captures", f"--list-state exited {r2.returncode}")
        return verdict()
    captured = {l.strip().rstrip("/") for l in r2.stdout.splitlines() if l.strip()}
    print(f"  backup.sh --list-state declares {len(captured)} path(s)")
    print(f"  git reports {len(ignored)} ignored path(s) present\n")

    inputs = [p for p in ignored if not is_regenerable(p)]
    uncaptured = sorted(p for p in inputs if not covered_by(p, captured))
    check("every gitignored INPUT is in backup.sh's capture set",
          not uncaptured,
          "UNCAPTURED — authored state that no repo and no backup holds:\n        "
          + "\n        ".join(uncaptured)
          + "\n        Add it to backup.sh, or add it to REGENERABLE here NAMING what"
            " regenerates it.")

    # the instances this gate was built from — pinned by name so a future refactor that
    # drops them shows up as these lines rather than as a silent set difference
    for f in ("local.md", ".env", "nucleus/runners.conf"):
        if (REPO / f).exists():
            check(f"pinned: {f} is captured", covered_by(f, captured))

    # ── and does the REAL artifact carry them? ───────────────────────────────────────
    # The list is a promise; the tarball is the thing a restore actually opens. Only red
    # on an artifact NEWER than backup.sh — an older one legitimately predates the fix,
    # and failing on that would be accusing the past.
    arts = sorted(REPO.glob("backups/*.state.tgz"), key=lambda p: p.stat().st_mtime)
    if not arts:
        skip("the newest real artifact carries the inputs", "no .state.tgz on disk")
    elif arts[-1].stat().st_mtime < (REPO / "nucleus" / "backup.sh").stat().st_mtime:
        skip("the newest real artifact carries the inputs",
             f"{arts[-1].name} predates backup.sh — not yet re-run")
    else:
        try:
            with tarfile.open(arts[-1]) as t:
                names = set(t.getnames())
        except Exception as e:
            skip("the newest real artifact carries the inputs", f"unreadable: {type(e).__name__}")
            return verdict()
        missing = sorted(p for p in inputs if not covered_by(p, names))
        check(f"the newest artifact ({arts[-1].name}) carries every input",
              not missing, "missing from the tarball: " + ", ".join(missing))

    # ── AGENT MEMORY, COUNT-MATCHED, DENOMINATOR FROM THE ROSTER ────────────────────
    # Agent memory lives OUTSIDE the repo, so the git-derived population above is
    # structurally blind to it however correct that gate is — the third instance of the
    # one-disk defect, and the first that the previous fix could never have caught.
    #
    # THE DENOMINATOR COMES FROM THE ROSTER, NOT FROM THE CAPTURE GLOB. A gate whose
    # denominator is the same glob whose failure it exists to catch cannot tell
    # nothing-found from everything-found — it would read a glob that matched zero
    # directories as a clean pass. The roster is the substrate that knows which agents
    # exist; the glob is the thing being measured.
    home = Path.home()
    try:
        sys.path.insert(0, str(REPO))
        from nucleus import charter
        roster = charter.roster()
    except Exception as e:                                   # noqa: BLE001
        skip("agent memory is captured", f"roster unavailable ({type(e).__name__})")
        roster = None

    if roster is not None and arts:
        newest = arts[-1]
        try:
            with tarfile.open(newest) as t:
                names = set(t.getnames())
        except Exception as e:                               # noqa: BLE001
            skip("agent memory is captured", f"tarball unreadable ({type(e).__name__})")
        else:
            proj = home / ".claude" / "projects"
            # roster-derived candidates: the repo-root project plus one per resident
            cands = [proj / "-home-umair-astryx"] + \
                    [proj / f"-home-umair-astryx-homes-{a}" for a in roster]
            existing = [c / "memory" for c in cands if (c / "memory").is_dir()]
            check("the roster-derived memory set is NON-EMPTY (a glob matching nothing "
                  "must not read as a pass)", bool(existing), "no memory dir found at all")
            for d in existing:
                rel = str(d.relative_to(home))
                on_disk = [f for f in d.rglob("*") if f.is_file()]
                if not on_disk:
                    # EMPTY IS A LEGAL, DISTINCT STATE. A gate that can never go green on a
                    # legitimately empty directory is a gate somebody disables.
                    print(f"  EMPTY {rel} — 0 files on disk, nothing to capture (legal)")
                    continue
                # COVERAGE, GUARDED BY THE SNAPSHOT CLOCK — not equal counts. The tarball is
                # a point-in-time snapshot; agent memory is written at ALL hours. A file whose
                # mtime is NEWER than the artifact legitimately postdates the snapshot and
                # cannot be in it (the next backup carries it) — counting it as a gap accuses
                # the FUTURE, the exact mirror of the "accusing the past" guard on the artifact
                # check above, and left this gate red for the whole window after every write.
                # An equal-count test also mis-fires the other way: an edited-since file bumps
                # its mtime past the snapshot while its captured old version still sits in the
                # tarball. So the real question is coverage: every file that EXISTED WHEN THE
                # BACKUP RAN (mtime <= snapshot) must be in the tarball — matched by its EXACT
                # full path, never a prefix, so the container-vs-content trap the old count
                # guarded against cannot return. Created-since, edited-since and deleted-since
                # are all correctly ignored; only a snapshot-era file truly dropped reds.
                snap = newest.stat().st_mtime
                dropped = sorted(
                    str(f.relative_to(home)) for f in on_disk
                    if f.stat().st_mtime <= snap and str(f.relative_to(home)) not in names)
                check(f"agent memory captured in full: {rel}",
                      not dropped,
                      f"{len(dropped)} snapshot-era file(s) missing from the tarball: "
                      + ", ".join(dropped[:5]) + (" …" if len(dropped) > 5 else ""))

    return verdict()


def verdict():
    print()
    if FAIL:
        print(f"FAILED ({len(FAIL)}): " + "; ".join(FAIL))
        return 1
    if SKIP:
        print(f"NOT RUN ({len(SKIP)}): " + "; ".join(SKIP))
        print("a gate that observed nothing is not a pass — exit 77")
        return 77
    print("every gitignored input is captured, and the newest artifact proves it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
