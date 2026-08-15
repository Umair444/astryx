#!/usr/bin/env python3
"""NUCLEUS · reachability — every committed nucleus script is INVOKED by something, or
is explicitly exempted with a reason. Nothing lands in nucleus/ and runs nowhere by
accident.

THE DEFECT THIS CLOSES (found 2026-08-16, live). `nucleus/pushed_tree_check.sh` was
committed as the org's answer to "will check.sh pass on a machine that is not mine?"
and was invoked by NOTHING — not check.sh, not hooks/pre-push, not init.sh, not a unit,
not a trigger. Zero references repo-wide, confirmed independently by seed and by its own
author. An instrument built to catch "green only on the author's machine" shipped in a
state where it ran only when a human typed its name.

WHY THE EXISTING GUARDS COULD NOT SEE IT — three healthy guards, three domains, and the
file sat in none of them:
  test_check_coverage.py  authority is the `nucleus/test_*.py` GLOB. Wrong prefix, wrong
                          extension -> invisible. Its author PREDICTED this exact case in
                          its own docstring §2 ("If an unwired non-test check ever
                          appears, THAT is the trigger to generalise this") and left it
                          deliberately, because as of 08-13 the convention had no
                          violators. This file is the trip condition firing.
  privacy_gate.sh (c2)    warns on ORPHANED nucleus files, scoped to `git ls-files
                          --others` — i.e. UNTRACKED. Committing the file is precisely
                          what moved it out of that guard's view.
  test_hook_integrity.py  speaks only about what the installed hook already names.
This is a coverage-TOPOLOGY finding, not a guard defect: the dangerous artifact is the
one that lands OUTSIDE every derivation's domain, because every gate stays green and
green reads as covered.

WHY AN EXEMPTION MANIFEST AND NOT A DERIVATION — the polarity is the whole argument.
The org has twice refused a hand-maintained set for good reason: abstractor-2 refused a
which-oracle-reads-which-subject manifest, and test_check_coverage replaced a hand-kept
list with a glob. Both were right, and neither applies here, because THE DANGER OF A
HAND-MAINTAINED SET IS NOT ITS HANDEDNESS, IT IS WHAT AN UNKNOWN MEMBER DEFAULTS TO:

    a set that grants COVERAGE   -> unknown member defaults to UNCHECKED  (unsafe)
    a set that grants EXEMPTION  -> unknown member defaults to ACCUSED    (fail-closed)

Same data structure, opposite polarity. EXEMPT below grants exemption, so a new script
that nobody wires and nobody exempts FAILS. That is the property the glob could not have:
membership in `test_*.py` is decided by whoever names the file, at authoring time, with
no gate.

WHY NOT A KIND DECLARATION (the fix §2 names). "A declared kind, not a cleverer regex" is
right and this file is its cheap half: the exemption reason IS the kind, declared once,
in one place, reviewable in a diff. Measured before choosing: only 10 of the 27 unwired
scripts carry the self-declared `Usage:`/`Run by hand:` header that §2 leans on, and it
misses fedtest.py, spawn.sh, wall.sh, deploy.sh and refresh.sh — all plainly operator
tools. Deriving kind from that convention would have accused ~17 healthy files, which is
exactly the "a wrong guess makes the suite red for a tool" §2 warns about. A per-file
`# Kind:` header is the better end state; it touches 71 files owned by other agents and
is an org decision, not a solo build at 1am.

SURFACES, AND WHY ABSENCE IS CLASSIFIED RATHER THAN ASSUMED. An invoker can live outside
the tracked tree. Each surface is probed and its ABSENCE is classified with
`git check-ignore`, never read as "nothing invokes this":
  tracked tree     git ls-files            always present. NOTE hooks/ is TRACKED (the
                                           template init.sh installs), so git hooks are
                                           readable here — I wrongly assumed otherwise.
  units/           systemd ExecStart       GITIGNORED. nucleus/canopus_inbound.py has NO
                                           tracked invoker at all; its only caller is
                                           units/astryx-canopus-inbound.service. Absent
                                           units/ therefore means UNVERIFIED, not RED.
  nucleus/runners.conf                     GITIGNORED (**/runners*.conf). The live runner
                                           table; runners.example.conf is a template whose
                                           entries are all commented out.
  triggers/*/*.py  the pulse discovers     GITIGNORED.
  .github/workflows/                       UNTRACKED BUT NOT IGNORED — a third state:
                                           pending the owner's workflow-scope commit.
If any surface is missing, the run reports UNVERIFIED (exit 77) instead of accusing what
it could not see. A SKIP IS NOT A PASS, and it is not a FAIL either.

INVOCATION POSITION, NOT MENTION. Edges are only drawn where a line actually runs the
file: after an interpreter (`bash`/`sh`/`$PY`/`python3`/`venv/bin/python`/`uv run`), after
`exec`/`source`/`.`, as the command word itself, from `ExecStart=`, from a runners.conf
row, or inside a subprocess call. Comment lines are stripped first. This distinction is
load-bearing and was measured, not assumed: a mention-grep "proves" privacy_gate.sh is
invoked by init.sh, check.sh and backup.sh — all three are COMMENTS — and by
`observatory/api/main.py`, which defines an unrelated middleware function of the same
name. Its one real invoker is the exec line in hooks/pre-push. (That citation said
":16" for about four hours and the line is now :61 — a2 caught it. A LINE NUMBER IN PROSE
IS A MECHANICAL CLAIM WITH NO RUNNER, and this hook is actively growing, so the file name
and the invocation form are the parts worth asserting.) A grep for the name answers a different
question than this file asks, and answers it in the covered-looking direction. (Same
reason d0bfbbd exists: prove a gate RUNS, not that its line exists.)

RESIDUAL, declared at birth. Edge extraction is a line parser, not a shell interpreter:
a path assembled at runtime (`$DIR/$name`), or invoked through a variable set elsewhere,
is a FALSE NEGATIVE — the file reads unreached and gets accused. That is why the fail set
is scoped to nucleus/ (calibrated below) and why EXEMPT carries a reason rather than a
bare name: a false accusation is answered by writing down why the file is legitimately
unreached, which is information the org keeps. This gate proves a script is REACHED FROM
A SURFACE IT CAN READ; it does not prove the invocation ever executes (a `run` line inside
`if false` is d0bfbbd's problem, and test_check_coverage owns it for the oracles).

Run: venv/bin/python nucleus/test_reachability.py   (also wired into nucleus/check.sh)
     venv/bin/python nucleus/test_reachability.py --report   (classification, no asserts)
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ.get("REACH_REPO", Path(__file__).resolve().parents[1]))

# ── THE EXEMPTION MANIFEST ────────────────────────────────────────────────────────────
# Membership grants EXEMPTION, so an unlisted uninvoked script FAILS. Every entry states
# the KIND and the REASON; "unused" is itself a failure, so an entry cannot outlive its
# subject. Seeded from the measured residue of 2026-08-16, one line read per file.
# DERIVED FROM THE TOOL'S OWN OUTPUT, NOT FROM MY NOTES. My first draft of this manifest
# carried 22 entries written from a reference map I had built by hand; the stale arm below
# rejected 12 of them as ALREADY INVOKED. An exemption written from memory is the same
# defect as a coverage list written from memory — it just fails silently instead of loudly.
# Every entry here survived a run that would have called it stale.
EXEMPT = {
    # operator diagnostics — running nowhere automatically IS the design. A command
    # documented in CLAUDE.md is deliberately NOT auto-granted reachability: a doc mention
    # is too weak to silence this gate, so a human writes one line here instead.
    "nucleus/fedtest.py":     "manual: federation end-to-end probe; CLAUDE.md documents the human command",
    "nucleus/doorbell.sh":    "manual: operator notify helper, self-declared Usage line",
    "nucleus/wallpane.sh":    "manual: single-pane variant of wall.sh, invoked by an operator",
    "nucleus/refresh.sh":     "manual: operator session refresh",
    "nucleus/deploy.sh":      "manual: operator deploy step",
    # data read by a tool, never executed
    "nucleus/mutants_check_coverage.py":   "data: mutant spec, read by mutation_probe.py when pointed at it",
    "nucleus/mutants_ear_survival.py":     "data: mutant spec, read by mutation_probe.py when pointed at it",
    "nucleus/mutants_pii_sweep_ledger.py": "data: mutant spec, read by mutation_probe.py when pointed at it",
    # FOURTH of its kind, and it arrived within hours of this file landing (8c543a9) —
    # caught by the gate on its first day, which is the fail-closed polarity working. But
    # four one-at-a-time exemptions of ONE class is the churn seed named as the trip
    # condition for the `# Kind:` question, and there is a derivation waiting: every
    # nucleus/mutants_*.py is already the SUBJECT of test_mutants_wellformed.py, the
    # committed ratchet that keeps these specs pointing at something real. This gate has no
    # READ-AS-DATA edge — only invocation — so a file watched by a committed gate still
    # reads as unreached. That edge, not a fifth exemption, is the fix. Proposed, not built.
    "nucleus/mutants_pre_push_contract.py": "data: mutant spec, read by mutation_probe.py when pointed at it",
    # FIFTH, same class, same night, and the last one added by hand: the derivation a4
    # names above (mutants_*.py are READ AS DATA by test_mutants_wellformed.py, a committed
    # gate this file has no edge type for) retires all five at once. Written twice — the
    # first copy was clobbered by a concurrent write to this file from the shared working
    # tree, which is its own small lesson about who else has the file open.
    "nucleus/mutants_check_stamp.py": "data: mutant spec, read by mutation_probe.py when pointed at it",
    "nucleus/__init__.py":    "library: package marker, imported implicitly by `from nucleus import X`",
    # REACHED, but through a construction no line parser can follow — this is the
    # declared residual made concrete, and the reason exemptions carry a file:line.
    "nucleus/identity_commit.py": "service: channel/server.mjs:274 builds the path with new URL(...) and spawns it",
}

INTERP = r"(?:bash|sh|zsh|exec|source|\.|python3?|\$PY|\$\{PY\}|venv/bin/python3?|uv\s+run|/usr/bin/env\s+\S+)"


def _git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=str(cwd or REPO),
                       capture_output=True, text=True)
    return r.stdout.splitlines() if r.returncode == 0 else []


def population():
    """Committed nucleus scripts. Derived from git, not from a naming convention."""
    return sorted(p for p in _git("ls-files", "nucleus/")
                  if p.endswith((".py", ".sh")))


def _is_ignored(path, is_dir=False):
    """Classify an ABSENT surface: gitignored by design, or missing and not ignored?

    The trailing slash is load-bearing. `.gitignore` line 26 is `units/` — a
    DIRECTORY-ONLY pattern — so `git check-ignore units` does not match it and the
    surface got reported as "absent, NOT ignored", inverting the very distinction this
    classification exists to draw (gitignored-by-design vs genuinely-missing).
    """
    cands = [path + "/", path] if is_dir else [path]
    for c in cands:
        r = subprocess.run(["git", "check-ignore", "-q", c], cwd=str(REPO),
                           capture_output=True)
        if r.returncode == 0:
            return True
    return False


def surfaces():
    """-> (texts, missing). Each entry is (label, text). `missing` classifies absence."""
    texts, missing = [], []
    for p in _git("ls-files"):
        f = REPO / p
        try:
            texts.append((p, f.read_text(errors="ignore")))
        except OSError:
            pass
    for label, rel, pattern in (("units", "units", "*.service"),
                                ("units-timers", "units", "*.timer"),
                                ("triggers", "triggers", "*/*.py"),
                                ("workflows", ".github/workflows", "*")):
        d = REPO / rel
        if d.is_dir():
            for f in sorted(d.glob(pattern)):
                try:
                    texts.append((str(f.relative_to(REPO)), f.read_text(errors="ignore")))
                except OSError:
                    pass
        elif not any(m[1] == rel for m in missing):     # units/ is probed twice, absent once
            missing.append((label, rel,
                            "gitignored" if _is_ignored(rel, is_dir=True) else "absent, NOT ignored"))
    runners = REPO / "nucleus/runners.conf"
    if runners.is_file():
        texts.append(("nucleus/runners.conf", runners.read_text(errors="ignore")))
    else:
        missing.append(("runners", "nucleus/runners.conf",
                        "gitignored" if _is_ignored("nucleus/runners.conf") else "absent, NOT ignored"))
    return texts, missing


def _strip_comment(line, is_conf):
    s = line.strip()
    if s.startswith("#"):
        return ""
    if is_conf:                       # runners.conf rows are '|'-separated, '#' comments
        return line
    return re.sub(r"\s#.*$", "", line)


def _command_word(line, cmd_tail):
    """Does the line's FIRST token run this file?

    Command position is a POSITION, not a spelling. `"$REPO/nucleus/x.sh" "$sha"` and
    `./nucleus/x.sh` and `nucleus/x.sh` are the same act; only the first survives a rule
    written as 'the line starts with the path'. So: take the first token, strip the
    quoting and any variable or command-substitution prefix, and ask whether what remains
    ENDS in this path. An occurrence anywhere later on the line is an argument, not a call.
    """
    tokens = line.strip().split()
    if not tokens:
        return False
    t = tokens[0].strip("\"'")
    t = re.sub(r"^(?:\$\{?\w+\}?|\$\([^)]*\)|~|\.)", "", t)   # $REPO/... , $(pwd)/... , ./...
    return bool(cmd_tail.search(t))


def invocations(path, texts):
    """Lines that RUN `path`, as (surface, line). Invocation position, never mention.

    TWO STEPS, not one regex, and the split is the reason the RED arms pass. A single
    pattern has to describe the whole span between the interpreter and the path, which
    in real shell is unbounded — `exec "$(git rev-parse --show-toplevel)/nucleus/x.sh"`
    puts a command substitution WITH SPACES in that span, and my first version's `\\S*/`
    could not cross it, so the org's one real hook invocation read as unreached. So:
    (1) find an execution TOKEN, (2) require the path to appear as a path COMPONENT
    somewhere after it. Position is still what makes it an invocation.
    """
    base = os.path.basename(path)
    tail = re.escape(path) + "|" + re.escape(base)
    # a path component: bounded by start/space/quote/= or a slash, and closed cleanly
    comp = re.compile(rf"(?:^|[\s\"'=(]|/)(?:{tail})(?=[\s\"';)&|]|$)")
    # an execution token: whole-word, and `.` only in its source-shorthand form
    tok = re.compile(rf"(?:^|[;&|(\"'\s])(?:{INTERP})(?=[\s\"'])")
    cmd_tail = re.compile(rf"(?:^|/)(?:{tail})$")
    execs = re.compile(r"ExecStart\s*=")
    subp = re.compile(r"(?:subprocess\.|Popen|check_call|check_output)")
    # A LIBRARY IS REACHED BY BEING IMPORTED. Derived, not exempted: the first run
    # accused okf/tier/tokenwatch/wake_audit/world — six healthy modules whose only
    # caller is an `import`, which is an invocation this parser simply could not see.
    # An exemption for each would have hidden a missing derivation behind a reason,
    # which is how an exemption manifest goes bad.
    stem = os.path.basename(path)[:-3] if path.endswith(".py") else None
    # Three import FORMS, and missing one of them accused three healthy modules
    # (tokenwatch, wake_audit, world) whose callers all write `from nucleus import X`
    # — the package-relative form. One missed spelling, three false accusations: an
    # edge type is not covered until every spelling of it is.
    imp = (re.compile(rf"^\s*(?:from\s+(?:nucleus\.)?{re.escape(stem)}\s+import\b"
                      rf"|import\s+(?:nucleus\.)?{re.escape(stem)}\b"
                      rf"|from\s+nucleus\s+import\s+(?:[\w,\s]*\b){re.escape(stem)}\b)")
           if stem and stem != "__init__" else None)
    hits = []
    for label, text in texts:
        if label == path:
            continue                  # a file does not invoke itself into reachability
        is_conf = label.endswith(".conf")
        for raw in text.splitlines():
            line = _strip_comment(raw, is_conf)
            if not line or (base not in line and not (stem and stem in line)):
                continue
            if is_conf:
                # runner row: name | agent | schedule | script | note
                if line.lstrip().startswith("#"):
                    continue          # runners.example.conf ships its rows commented out
                cells = [c.strip() for c in line.split("|")]
                if any(c.endswith(base) or c == path for c in cells):
                    hits.append((label, line.strip()))
                continue
            hit = False
            if _command_word(line, cmd_tail) or (imp and imp.search(line)):
                hit = True
            else:
                for m in (tok, execs, subp):
                    at = m.search(line)
                    if at and comp.search(line, at.end()):
                        hit = True
                        break
            if hit:
                hits.append((label, line.strip()))
    return hits


def classify(pop, texts):
    reached, unreached = {}, []
    for path in pop:
        hits = invocations(path, texts)
        if hits:
            reached[path] = hits
        else:
            unreached.append(path)
    return reached, unreached


# ── SELF-TEST ARMS (RED and GREEN, on fixtures the parser must separate) ──────────────
FIXTURES = [
    ("invoked by check.sh run-line", True,
     [("nucleus/check.sh", 'run "x" "$PY" nucleus/test_thing.py')], "nucleus/test_thing.py"),
    ("invoked bare as a command", True,
     [("init.sh", "  ./nucleus/backup.sh --now")], "nucleus/backup.sh"),
    ("invoked via ExecStart", True,
     [("units/a.service", "ExecStart=/home/u/astryx/nucleus/canopus_inbound.py")],
     "nucleus/canopus_inbound.py"),
    ("invoked from a subprocess list", True,
     [("nucleus/pulse.py", '    subprocess.run([PY, "nucleus/pulse_run.py", name])')],
     "nucleus/pulse_run.py"),
    ("invoked by exec in a hook", True,
     [("hooks/pre-push", 'exec "$(git rev-parse --show-toplevel)/nucleus/privacy_gate.sh"')],
     "nucleus/privacy_gate.sh"),
    ("runners.conf row", True,
     [("nucleus/runners.conf", "backup | org | *-*-* 04:00:00 | nucleus/backup.sh | dump")],
     "nucleus/backup.sh"),
    # the RED arm: every one of these is a MENTION, and a mention must not count
    ("comment naming it is not an invocation", False,
     [("nucleus/backup.sh", "# in privacy_gate's SURFACES, NEVER pushed.")],
     "nucleus/privacy_gate.sh"),
    # THIS one binds the comment stripping; the fixture above does not, and I only found
    # that out by deleting the strip and watching every negative arm still pass. Prose
    # that merely NAMES a file fails the parser for want of an interpreter token, so it
    # would pass with the stripping gone — a fixture excluded by the wrong clause tests
    # the wrong clause. A commented-out REAL invocation is the only counterexample the
    # two implementations disagree on.
    ("a commented-out invocation is not an invocation", False,
     [("nucleus/x.sh", "#  bash nucleus/backup.sh --now   (disabled, see goal-12)")],
     "nucleus/backup.sh"),
    ("full-line comment with a real command in it", False,
     [("nucleus/runners.example.conf", "#   backup | org | x | nucleus/backup.sh | note")],
     "nucleus/backup.sh"),
    ("homonymous function definition", False,
     [("observatory/api/main.py", "async def privacy_gate(request: Request, call_next):")],
     "nucleus/privacy_gate.sh"),
    ("error-message string naming the script", False,
     [("init.sh", '    bad "pre-push hook missing — privacy_gate.sh will not run"')],
     "nucleus/privacy_gate.sh"),
    ("prose naming the file in a docstring", False,
     [("nucleus/x.py", "  it, and pushed_tree_check.sh is the instrument that answers it")],
     "nucleus/pushed_tree_check.sh"),
    ("a library is reached by an import", True,
     [("nucleus/test_okf.py", "from okf import parse_frontmatter")], "nucleus/okf.py"),
    ("import of the packaged path", True,
     [("bridges/gateway.py", "import nucleus.orgname")], "nucleus/orgname.py"),
    ("the stem appearing in prose is not an import", False,
     [("nucleus/x.py", "    # the tier floor and world layer disagree here")],
     "nucleus/tier.py"),
    ("package-relative import form", True,
     [("hooks/usage.py", "                from nucleus import tokenwatch")],
     "nucleus/tokenwatch.py"),
    ("package-relative, several names on the line", True,
     [("triggers/x.py", "        from nucleus import charter, world")], "nucleus/world.py"),
    # The live miss. steward wired pushed_tree_check.sh into hooks/pre-push and this
    # gate STILL accused it: the line runs a quoted, variable-prefixed path directly, with
    # no interpreter token and no line-initial path. The gate built to find unwired files
    # false-accused the one file it had just been proven on. A command word is the FIRST
    # TOKEN, whatever it is spelled with — not a line that starts with a literal path.
    ("quoted variable-prefixed command word", True,
     [("hooks/pre-push", '  "$REPO/nucleus/pushed_tree_check.sh" "$sha"')],
     "nucleus/pushed_tree_check.sh"),
    ("the same path as an ARGUMENT is not a command word", False,
     [("nucleus/x.sh", '  echo "see $REPO/nucleus/pushed_tree_check.sh for details"')],
     "nucleus/pushed_tree_check.sh"),
]


def self_test():
    bad = []
    for name, want, texts, path in FIXTURES:
        got = bool(invocations(path, texts))
        if got != want:
            bad.append(f"  {'MISSED' if want else 'FALSE POSITIVE'}: {name}")
    return bad


def main():
    report = "--report" in sys.argv
    bad = self_test()
    if bad:
        print("reachability: SELF-TEST FAILED — the edge parser is wrong, so its verdict")
        print("about the live tree means nothing:")
        print("\n".join(bad))
        return 1
    pop = population()
    if not pop:
        print("reachability: no committed nucleus scripts found — VERIFIED NOTHING")
        return 77
    texts, missing = surfaces()
    reached, unreached = classify(pop, texts)
    accused = [p for p in unreached if p not in EXEMPT]
    stale = [p for p in EXEMPT if p not in pop or p in reached]

    if report:
        print(f"population {len(pop)}  reached {len(reached)}  "
              f"exempt {len(EXEMPT)}  accused {len(accused)}")
        for p in unreached:
            print(f"  {'EXEMPT ' if p in EXEMPT else 'ACCUSED'} {p}"
                  + (f"   — {EXEMPT[p]}" if p in EXEMPT else ""))
        for label, rel, why in missing:
            print(f"  surface MISSING: {rel} ({why})")
        return 0

    if stale:
        print("reachability: STALE EXEMPTION(S) — the manifest outlived its subject. An")
        print("exemption that no longer applies is a lie the next reader inherits:")
        for p in stale:
            print(f"  {p} — {'no longer in nucleus/' if p not in pop else 'is now invoked; delete the exemption'}")
        return 1

    # ── INHERITED REACHABILITY FROM A DEAD PARENT (abstractor-2's hypothesis) ──────────
    # This gate asks "does any line RUN this file", not "is the INVOKER itself live", so a
    # script whose only caller is an EXEMPT manual tool inherits reachability from a parent
    # that runs nowhere. a2 measured it as latent-not-live (zero instances across 63 reached)
    # and proposed a line in the header naming the trip condition. A trip condition written
    # in prose is a test with no runner, and it is zero TODAY — which is exactly when a
    # standing assert is free to add. Re-measured on the grown manifest before adding it:
    # 77 scripts, 11 exempt/unreached, still zero. Skipped when blind, like every other
    # accusation here: an absent surface inflates `unreached` and would manufacture parents.
    if not missing:
        dead = set(EXEMPT) | set(unreached)
        inherited = [(f, sorted({lbl for lbl, _ in hits}))
                     for f, hits in reached.items()
                     if {lbl for lbl, _ in hits} <= dead and hits]
        if inherited:
            print("reachability: REACHED ONLY BY A PARENT THAT RUNS NOWHERE —")
            for f, parents in inherited:
                print(f"  {f}  <- {', '.join(parents)}")
            print("Every invoker of these is itself exempt or unreached, so the chain")
            print("bottoms out in nothing automatic. Wire the parent or the child.")
            return 1

    if accused and missing:
        # NEVER ACCUSE WHILE BLIND. A file whose only invoker lives on an absent surface
        # (canopus_inbound.py is invoked solely by a gitignored unit) would be convicted
        # here on the strength of what this run could not see — and in a clean clone or
        # CI, three of the four surfaces are absent by construction. steward made the same
        # call on the hook an hour ago: unknown -> watched, never blocked. A gate that
        # reddens a build for a healthy file teaches people to bypass it, and a bypassed
        # gate is off forever.
        print(f"reachability: {len(accused)} candidate(s) invoked by nothing this run "
              f"could see, but {len(missing)} surface(s) were absent:")
        for p in accused:
            print(f"  ? {p}")
        for label, rel, why in missing:
            print(f"  surface absent: {rel} ({why})")
        print("UNVERIFIED — re-run where every surface is present before believing this.")
        return 77

    if accused:
        print("reachability: COMMITTED AND INVOKED BY NOTHING —")
        for p in accused:
            print(f"  {p}")
        print("Wire it (check.sh, hooks/pre-push, a unit, a runner) or add it to EXEMPT")
        print("with the reason it legitimately runs nowhere. Both are one line.")
        return 1

    if missing:
        print(f"reachability: {len(pop)} script(s) reached or exempted, but "
              f"{len(missing)} invoker surface(s) were absent here:")
        for label, rel, why in missing:
            print(f"  {rel} ({why}) — anything invoked ONLY from there is unproven")
        print("UNVERIFIED — a skip is not a pass.")
        return 77

    print(f"reachability: all {len(pop)} committed nucleus scripts are invoked "
          f"({len(EXEMPT)} exempted with reasons); all surfaces present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
