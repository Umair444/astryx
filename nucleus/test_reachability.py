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
import ast
import textwrap
import warnings
import importlib.util
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
    # The pulse-runner class (owner ruling 2026-08-21: one timer, the pulse; scheduled jobs
    # are triggers). Their invokers live in triggers/steward/org_runners.py, which is
    # GITIGNORED — a git-derived reachability scan is blind exactly there (the oracle-split
    # class), so the edge is declared here by hand, with its location.
    "nucleus/check_watch.sh":    "invoked by triggers/steward/org_runners.py (gitignored estate; pulse trigger, daily 05:20)",
    "nucleus/restore_verify.sh": "invoked by triggers/steward/org_runners.py (gitignored estate; pulse trigger, weekly Sun 03:00)",
    "nucleus/station.py":     "on-demand: the stationed-agent runtime — a backend or operator invokes it per request (claude -p API); nothing schedules it by design",
    "nucleus/fedtest.py":     "manual: federation end-to-end probe; CLAUDE.md documents the human command",
    "nucleus/esc_latency.py":  "manual: MIN_QUIET_H calibration measurement, run on demand; reports and never recommends, so a timer would only manufacture noise",
    "nucleus/doorbell.sh":    "manual: operator notify helper, self-declared Usage line",
    "nucleus/wallpane.sh":    "manual: single-pane variant of wall.sh, invoked by an operator",
    "nucleus/refresh.sh":     "manual: operator session refresh",
    "nucleus/deploy.sh":      "manual: operator deploy step",
    # Landed 6efc7f2 and red on the FIRST live-tree run after it — the gate working, not
    # failing. Its ORACLE is wired into check.sh; the TOOL is typed by an agent at a
    # prompt, which is the whole point of it (the standing rule it serves is about
    # what a human TYPES; the shell wrapper that lies is not present in scripts).
    "nucleus/estate_grep.sh": "manual: the estate search an agent TYPES — org-news #12934 names it as the rule's implementation; its oracle test_estate_grep.py is what check.sh runs",
    # SIX EXEMPTIONS USED TO LIVE HERE — one per nucleus/mutants_*.py, added one at a
    # time over eight days by three different authors, each correctly reasoned and each
    # a symptom of the same missing edge. DATA_READERS retires all of them: the specs are
    # reached by test_mutants_wellformed.py, which reads them, and this file's own STALE
    # arm named all six as "is now invoked; delete the exemption" before they were cut.
    # A seventh, mutants_wedge_watch.py, never needed an exemption at all — it was being
    # granted reachability by a docstring, which is the hole the Python-surface rule closes.
    #
    # NEWLY VISIBLE, NOT NEWLY TRUE. Both entries below were unreached all along and were
    # hidden by that same docstring hole: mutation_probe.py's `Run:` line reached every
    # spec, and their `Run:` lines reached it back — a mutual-citation ring. Making them
    # visible is the fix working; whether they should instead be WIRED is a call for
    # whoever owns them, and the exemption is what forces that call to be made out loud.
    "nucleus/mutation_probe.py":
        "manual: authoring-time instrument, deliberately NOT gated in check.sh (steward's "
        "ruling, msg 5934 — the full run is 100.6s and a slow gate gets skipped). "
        "nucleus/probe_all.sh invokes it but is UNTRACKED; when it lands, this goes stale.",
    "nucleus/smoke.sh":
        "manual: doctor-class post-deploy probe, self-declared (`# Usage: nucleus/smoke.sh "
        "[observatory-port]`) and already classified as manual by test_check_coverage.py:56",
    "nucleus/__init__.py":    "library: package marker, imported implicitly by `from nucleus import X`",
    # REACHED, but through a construction no line parser can follow — this is the
    # declared residual made concrete, and the reason exemptions carry a file:line.
    "nucleus/identity_commit.py": "service: channel/server.mjs:274 builds the path with new URL(...) and spawns it",
}

INTERP = r"(?:bash|sh|zsh|exec|source|\.|python3?|\$PY|\$\{PY\}|venv/bin/python3?|uv\s+run|/usr/bin/env\s+\S+)"


# .py surfaces that would not parse this run; blind, never empty. See _py_invocations.
UNPARSEABLE = set()


def _git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=str(cwd or REPO),
                       capture_output=True, text=True)
    return r.stdout.splitlines() if r.returncode == 0 else []


def population():
    """COMMITTED nucleus scripts. Derived from git, not from a naming convention.

    `ls-tree -r HEAD`, NOT `ls-files`. ls-files lists the INDEX, so a file between
    `git add` and `git commit` is in it — and this gate then prints "all N COMMITTED
    nucleus scripts" about files that are not committed. a2 did not deduce this, they
    HIT it: at 03:04 the gate returned rc 1 with "STALE EXEMPTION — mutants_check_stamp.py
    no longer in nucleus/", because the exemption was in the file while its subject was
    mid-`git add`; at 03:05 the identical command returned 0. Proven deterministically
    after the live window healed: stage one file in a clone and ls-files says 81 while
    ls-tree HEAD says 80.

    It is urgent rather than tidy because it COMPOSES with the remedy this gate is headed
    for. A scheduled run belongs on the live host — the one machine where someone is
    always mid-edit — so an index-authored population makes the first thing the org learns
    about this gate be that it reddens for no reason. A flaky red is how a gate gets
    bypassed, and a bypassed gate is off forever.
    """
    return sorted(p for p in _git("ls-tree", "-r", "--name-only", "HEAD", "nucleus/")
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


# ── A SURFACE IS PARSED IN ITS OWN LANGUAGE ──────────────────────────────────────────
# Shell grammar inside a .py file is not an invocation, it is prose. That is not a
# heuristic — Python has no syntax under which `venv/bin/python nucleus/x.py` executes
# anything, so a line-oriented shell parser reading a .py surface is answering with a
# grammar the file cannot speak. Measured cost of getting this wrong, on the live tree:
#
#   mutants_wedge_watch.py   reached ONLY by mutation_probe.py's `Run:` docstring line
#   mutation_probe.py        reached ONLY by the seven mutants files' `Run:` docstrings
#
# — a mutual-citation ring of USAGE EXAMPLES that granted a whole subsystem reachability
# it did not have. It is the same rule this file's own EXEMPT header already states ("a
# doc mention is too weak to silence this gate"), silently not applied to a second doc
# surface. A docstring is documentation wherever it lives.
#
# The first draft of this fix was line-based (skip shell tokens on .py surfaces) and it
# FALSE-ACCUSED social_age.py, whose real caller is
#     subprocess.run(
#         [str(REPO / "venv" / "bin" / "python"), str(REPO / "nucleus" / "social_age.py")],
# — a genuine invocation whose call and whose path sit on different LINES. A line is the
# wrong unit for Python; the statement is. So: parse it. ast.walk finds the Call whatever
# it is spelled with and however it wraps, and finds no Call at all inside a docstring.
#
# UNPARSEABLE IS BLIND, NOT EMPTY. A .py surface that will not parse contributes no edges,
# which would silently convict whatever it alone invokes — so it is reported as an absent
# surface and routes into the never-accuse-while-blind branch, exactly like a missing unit
# directory. Residual, declared: a call whose path is built entirely from variables has no
# string constant to match and reads as unreached. Loud and fail-closed, which is the side
# to be wrong on.
_EXEC_ATTRS = {"run", "Popen", "call", "check_call", "check_output", "system", "popen",
               "execv", "execvp", "spawnv", "create_subprocess_exec", "create_subprocess_shell"}


def _is_exec_call(func):
    if isinstance(func, ast.Attribute):
        return func.attr in _EXEC_ATTRS
    if isinstance(func, ast.Name):
        return func.id in _EXEC_ATTRS
    return False


# PARSE ONCE PER SURFACE, NOT ONCE PER QUESTION. The first working version parsed every
# .py surface afresh for each of the 83 candidate paths — ~16,000 whole-file parses, and
# the gate went from under a second to not finishing inside two minutes. The line-based
# parser got away with it because `base not in line` rejected 99% of lines before any work;
# an AST has no such prefilter, so the index has to be built once and then queried.
_PY_INDEX = {}


# THE PROBE CHANNEL IS AN INVOCATION EDGE. An oracle here deliberately does NOT write
# `from nucleus import X`: a bare import makes mutation_probe mutate a copy while the oracle
# loads the REAL module, and every mutant reports NOT PROBED — ten did on escalation.py in one
# morning (the canary in 43b6277 exists because of it). The org's standard shape is a subject
# path bound to a name and loaded dynamically:
#
#     SUBJECT = Path(os.environ.get("ESCALATION_SRC", REPO / "nucleus" / "escalation.py"))
#     _spec = importlib.util.spec_from_file_location("under_test", SUBJECT)
#
# This parser could not see it, so escalation.py read as reached only by an EXEMPT manual tool
# and the ROOTED assert fired — correct by its own rule, false about the world. It is the case
# I flagged as latent with a trip condition when I built the gate; it fired eight days later,
# and it fires MORE often as MORE oracles adopt the correct shape.
#
# THE COST OF LEAVING IT: a false red is not neutral, because the cheapest way to silence one is
# to change the SUBJECT. test_escalation.py now carries `from nucleus import escalation as esc
# # noqa: E402 — the invoker the gate reads` — a line whose stated purpose is to be seen by this
# gate, in the file whose own comment explains that a bare import is the wiring fault that let
# ten mutants survive. It was written carefully (guarded by `if not _override`, so the mutation
# path never imports) and it is still the instrument shaping the subject. WHEN A GUARD CANNOT SEE
# A CORRECT IDIOM, THE CHEAPEST FIX IS ALWAYS TO CHANGE THE CODE, AND THAT IS THE WRONG DIRECTION.
#
# THE RULE: a name bound to a path and later handed to a dynamic loader is an invocation of that
# path. Two passes — collect the Names any loader call receives, then collect string constants
# from the assignments that bind them. Not a file-level "there is a loader somewhere" heuristic:
# my first attempt was, and it silently required the default to sit INSIDE an `os.environ.get`
# call, so it missed the spelling where the override is read in a separate statement — which is
# exactly the shape test_escalation.py has today. The fixture for that spelling is what caught it.
_LOADER_ATTRS = {"spec_from_file_location", "run_path", "load_source", "SourceFileLoader"}


def _is_loader_call(func):
    if isinstance(func, ast.Attribute):
        return func.attr in _LOADER_ATTRS
    if isinstance(func, ast.Name):
        return func.id in _LOADER_ATTRS
    return False


def _py_index(label, text):
    """-> ({imported dotted names}, [(lineno, (string constants,))]) for one .py surface.

    Raises SyntaxError if the surface will not parse; the caller records that as BLIND.
    """
    if label not in _PY_INDEX:
        with warnings.catch_warnings():      # other people's escapes are not our finding
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(textwrap.dedent(text))
        imports, calls = set(), []
        # pass 1: every Name a dynamic loader is handed, plus constants inside the call itself
        loader_names, loader_consts = set(), []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_loader_call(node.func):
                consts = tuple(c.value for c in ast.walk(node)
                               if isinstance(c, ast.Constant) and isinstance(c.value, str))
                if consts:
                    loader_consts.append((node.lineno, consts, "dynamic load"))
                for a in ast.walk(node):
                    if isinstance(a, ast.Name):
                        loader_names.add(a.id)
        calls.extend(loader_consts)
        # pass 2: the assignments that bind those names carry the subject path
        if loader_names:
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id in loader_names for t in node.targets):
                    consts = tuple(c.value for c in ast.walk(node)
                                   if isinstance(c, ast.Constant) and isinstance(c.value, str))
                    if consts:
                        calls.append((node.lineno, consts, "dynamic load: subject bound here"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imports.add(a.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                imports.add(mod)
                for a in node.names:
                    imports.add(f"{mod}.{a.name}")
            elif isinstance(node, ast.Call) and _is_exec_call(node.func):
                consts = tuple(s.value for s in ast.walk(node)
                               if isinstance(s, ast.Constant) and isinstance(s.value, str))
                if consts:
                    calls.append((node.lineno, consts, "subprocess"))
        _PY_INDEX[label] = (imports, calls)
    return _PY_INDEX[label]


def _py_invocations(text, comp, stem, label="<fixture>"):
    """-> list of (lineno, why). Raises SyntaxError if the surface is unparseable."""
    imports, calls = _py_index(label, text)
    out = []
    if stem:
        for form, name in (("import", stem), ("import", f"nucleus.{stem}"),
                           ("package-relative import", f"nucleus.{stem}")):
            if name in imports:
                out.append((1, form))
                break
    for lineno, consts, why in calls:
        if any(comp.search(c) for c in consts):
            out.append((lineno, why))
    return out


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
        if label.endswith(".py"):
            try:
                rows = text.splitlines()
                for lineno, why in _py_invocations(text, comp, stem, label):
                    line = rows[lineno - 1].strip() if lineno <= len(rows) else ""
                    hits.append((label, f"{line[:120]}   [{why}]"))
            except SyntaxError:
                UNPARSEABLE.add(label)
            continue
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


# ── READ-AS-DATA: an edge type, derived from the READER's own domain expression ───────
# A file can be REACHED without ever being executed: nucleus/mutants_*.py are read,
# imported and validated by test_mutants_wellformed.py, a gate check.sh runs (line 133).
# This parser saw only invocation, so six healthy specs read as unreached and cost six
# hand-written exemptions in eight days — one per authored oracle, from three different
# authors. Six exemptions of ONE class is not a manifest doing its job, it is a missing
# derivation wearing a manifest's clothes.
#
# THE SET IS THE READER'S, NOT MINE. a2's condition, and it is the whole design: this
# calls the reader's own mutants_files() rather than re-globbing "mutants_*.py" here.
# Re-globbing would make two writers of one set — the drift this gate exists to catch,
# committed inside the gate itself. It also means there is no glob literal to mis-parse.
#
# The edge is attributed to the READER, so it inherits every property an invocation edge
# has: if test_mutants_wellformed.py is ever unwired from check.sh, all six specs become
# reached-only-by-a-parent-that-runs-nowhere and inherited_from_dead() reddens. That
# safety came free from spelling the edge as a normal parent, and is the reason not to
# special-case it into a second exemption list.
#
# An unknown data class still defaults to ACCUSED: nothing here grants blanket coverage
# to "files something reads." One row per reader, and the reader must declare its domain.
DATA_READERS = [
    ("nucleus/test_mutants_wellformed.py", "mutants_files",
     "read as data: the committed ratchet imports and validates every mutants spec"),
]


def data_edges():
    """-> ({path: [(reader, why)]}, [problems]). The reader names its own domain.

    A reader that is GONE simply stops granting the edge and its data files fall to
    ACCUSED — loud, correct, no special case. A reader that is PRESENT but unimportable
    is a different thing: the edge is unverifiable, so it is reported and fails rather
    than silently withdrawing coverage.
    """
    edges, problems = {}, []
    for rel, fn_name, why in DATA_READERS:
        f = REPO / rel
        if not f.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"_dr_{f.stem}", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            domain = getattr(mod, fn_name)()
        except Exception as e:
            problems.append(f"{rel}.{fn_name}() — {type(e).__name__}: {e}")
            continue
        for d in domain:
            try:
                key = str(Path(d).resolve().relative_to(REPO))
            except ValueError:
                continue                       # outside the repo: not our population
            edges.setdefault(key, []).append((rel, why))
    return edges, problems


def classify(pop, texts, data=None):
    reached, unreached = {}, []
    data = data or {}
    for path in pop:
        hits = invocations(path, texts) + data.get(path, [])
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
    # These three were VALID-PYTHON'd when .py surfaces started being parsed. As raw
    # fragments they were unparseable, so they passed by falling into the blind bucket
    # instead of by the discrimination they name — a fixture excluded by the wrong clause
    # tests the wrong clause, which is a lesson this file already carries one arm below.
    ("homonymous function definition", False,
     [("observatory/api/main.py", "async def privacy_gate(request):\n    return 1\n")],
     "nucleus/privacy_gate.sh"),
    ("error-message string naming the script", False,
     [("init.sh", '    bad "pre-push hook missing — privacy_gate.sh will not run"')],
     "nucleus/privacy_gate.sh"),
    ("prose naming the file in a docstring", False,
     [("nucleus/x.py", '"""it, and pushed_tree_check.sh is the instrument that answers it"""')],
     "nucleus/pushed_tree_check.sh"),
    # THE HOLE THIS RULE CLOSES, and it was live: mutation_probe.py's own `Run:` line
    # granted every mutants spec reachability, and their `Run:` lines granted it back.
    ("a Run: usage example in a docstring is not an invocation", False,
     [("nucleus/mutation_probe.py",
       '"""probe.\n\nRun:\n    venv/bin/python nucleus/mutation_probe.py nucleus/mutants_x.py\n"""')],
     "nucleus/mutants_x.py"),
    # smoke.sh's live edge: a prose line whose FIRST TOKEN is a basename satisfied
    # _command_word, the rule written for real shell. In a .py surface there is no
    # command position at all.
    ("a bare basename first on a line is prose in python", False,
     [("nucleus/test_check_coverage.py",
       '"""x\n\n   smoke.sh / fedtest.py / doctor-class tools, self-declared MANUAL\n"""')],
     "nucleus/smoke.sh"),
    # ...and the true call the line-based draft of this rule false-accused. The Call and
    # the path are on different LINES, which is why the unit had to become the statement.
    ("a subprocess call whose path is on a later line", True,
     [("triggers/seed/people_sweep.py",
       'subprocess.run(\n    [str(REPO / "venv" / "bin" / "python"),\n'
       '     str(REPO / "nucleus" / "social_age.py")],\n    check=True)')],
     "nucleus/social_age.py"),
    ("a library is reached by an import", True,
     [("nucleus/test_okf.py", "from okf import parse_frontmatter")], "nucleus/okf.py"),
    ("import of the packaged path", True,
     [("bridges/gateway.py", "import nucleus.orgname")], "nucleus/orgname.py"),
    ("the stem appearing in prose is not an import", False,
     [("nucleus/x.py", "# the tier floor and world layer disagree here")],
     "nucleus/tier.py"),
    ("package-relative import form", True,
     [("hooks/usage.py", "                from nucleus import wake_audit")],
     "nucleus/wake_audit.py"),
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
    # THE PROBE CHANNEL — one arm per SPELLING, because an edge type is not covered until
    # every spelling of it is, and the third arm is the one that caught my first attempt.
    ("subject bound with a two-arg env default, loaded dynamically", True,
     [("nucleus/test_escalation.py",
       'SUBJECT = Path(os.environ.get("ESCALATION_SRC", REPO / "nucleus" / "escalation.py"))\n'
       '_spec = importlib.util.spec_from_file_location("under_test", SUBJECT)\n')],
     "nucleus/escalation.py"),
    ("subject bound with an or-form default, runpy loader", True,
     [("nucleus/test_stale_goals.py",
       'SUBJECT = Path(os.environ.get("STALE_GOALS_SRC") or (REPO / "nucleus" / "stale_goals.py"))\n'
       'runpy.run_path(str(SUBJECT))\n')],
     "nucleus/stale_goals.py"),
    # THE SPELLING THAT BROKE MY FIRST RULE: the override is read in a SEPARATE statement, so
    # the binding assignment contains no `os.environ.get` at all. A file-level "does this module
    # load anything" heuristic passed the other two arms and missed this one.
    ("subject bound in a branch, override read separately", True,
     [("nucleus/test_escalation.py",
       '_override = os.environ.get("ESCALATION_SRC")\n'
       'if not _override:\n'
       '    SUBJECT = Path(REPO / "nucleus" / "escalation.py")\n'
       'else:\n'
       '    SUBJECT = Path(_override)\n'
       '_spec = importlib.util.spec_from_file_location("under_test", SUBJECT)\n')],
     "nucleus/escalation.py"),
    # THE GUARD: same binding, nothing loads it. Delete the loader_names condition and this fails.
    ("a path bound to a name nothing loads is not an invocation", False,
     [("nucleus/x.py",
       'DOC = Path(REPO / "nucleus" / "escalation.py")\n'
       'print(DOC)\n')],
     "nucleus/escalation.py"),
    ("a loader fed some OTHER subject does not reach this one", False,
     [("nucleus/test_other.py",
       'SUBJECT = Path(REPO / "nucleus" / "other.py")\n'
       '_spec = importlib.util.spec_from_file_location("u", SUBJECT)\n')],
     "nucleus/escalation.py"),
    ("the same path as an ARGUMENT is not a command word", False,
     [("nucleus/x.sh", '  echo "see $REPO/nucleus/pushed_tree_check.sh for details"')],
     "nucleus/pushed_tree_check.sh"),
]


def inherited_from_dead(reached, dead):
    """Files whose ENTIRE invoker set is exempt-or-unreached. Pure, so it is testable.

    It was NOT testable when it landed, and a2 found that out by trying to fire it from
    outside: the STALE arm preempts every attempt, because any parent you can add to
    EXEMPT is by definition reached, so the run fails as stale before reaching this check.
    An arm whose RED path cannot be driven is the exact defect this whole thread is about
    — "never fired" and "cannot fire" are indistinguishable from the outside. Lifting the
    logic out of main() into a pure function over (reached, dead) is what makes the
    counterexample expressible at all.
    """
    out = []
    for f, hits in reached.items():
        invokers = {lbl for lbl, _ in hits}
        if invokers and invokers <= dead:
            out.append((f, sorted(invokers)))
    return sorted(out)


# (name, reached, dead, expect_flagged) — the RED arm a2 could not reach from outside.
INHERITED_FIXTURES = [
    ("child invoked only by an exempt parent",
     {"nucleus/child.sh": [("nucleus/deploy.sh", "bash nucleus/child.sh")]},
     {"nucleus/deploy.sh"}, True),
    ("one live parent among dead ones is enough",
     {"nucleus/child.sh": [("nucleus/deploy.sh", "x"), ("nucleus/check.sh", "y")]},
     {"nucleus/deploy.sh"}, False),
    ("a live parent alone",
     {"nucleus/child.sh": [("nucleus/check.sh", "bash nucleus/child.sh")]},
     {"nucleus/deploy.sh"}, False),
    ("a chain two deep still bottoms out in nothing",
     {"nucleus/child.sh": [("nucleus/mid.sh", "bash nucleus/child.sh")]},
     {"nucleus/mid.sh", "nucleus/deploy.sh"}, True),
]


# (name, data, expect_reached) — the FOLD is pure, so the read-as-data edge is provable
# without touching disk. That the live domain is non-empty is asserted separately, in
# main(), against the substrate: a fold that works over a set nobody fills is decoration.
DATA_FOLD_FIXTURES = [
    ("a data edge reaches a file no line invokes",
     {"nucleus/m.py": [("nucleus/reader.py", "read as data")]}, True),
    ("no data edge leaves it unreached", {}, False),
    ("a data edge for some OTHER file does not reach this one",
     {"nucleus/other.py": [("nucleus/reader.py", "read as data")]}, False),
]


def self_test():
    bad = []
    seen_blind = set(UNPARSEABLE)
    _PY_INDEX.clear()             # fixtures reuse labels with DIFFERENT text; see below
    for name, want, texts, path in FIXTURES:
        got = bool(invocations(path, texts))
        if got != want:
            bad.append(f"  {'MISSED' if want else 'FALSE POSITIVE'}: {name}")
    for name, data, want in DATA_FOLD_FIXTURES:
        r, _ = classify(["nucleus/m.py"], [], data)
        if bool(r) != want:
            bad.append(f"  {'MISSED' if want else 'FALSE POSITIVE'}: data edge — {name}")
    # A .py surface that will not parse must land in the blind bucket, not be silently
    # read as "invokes nothing" — that difference is the whole never-accuse-while-blind
    # branch, and nothing else in this suite drives it.
    probe = set(UNPARSEABLE)
    invocations("nucleus/x.py", [("nucleus/broken.py", "def f(:\n")])
    if "nucleus/broken.py" not in UNPARSEABLE - probe:
        bad.append("  MISSED: an unparseable .py surface must be recorded as blind")
    # The cache is keyed by LABEL, which is unique per surface in a real run but reused
    # across fixtures ("nucleus/x.py" appears in four of them with different bodies). Both
    # ends of the self-test clear it, so a fixture can neither read nor leave a stale parse.
    _PY_INDEX.clear()
    UNPARSEABLE.clear()
    UNPARSEABLE.update(seen_blind)     # fixtures must not pollute the live verdict
    for name, reached, dead, want in INHERITED_FIXTURES:
        got = bool(inherited_from_dead(reached, dead))
        if got != want:
            bad.append(f"  {'MISSED' if want else 'FALSE POSITIVE'}: inherited — {name}")
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
    data, dproblems = data_edges()
    if dproblems:
        print("reachability: A READ-AS-DATA READER WOULD NOT ANSWER — the edge it grants")
        print("is unverifiable, so files it covers cannot be judged this run:")
        for pr in dproblems:
            print(f"  {pr}")
        return 1
    # The fold is fixtured; that the DOMAIN is non-empty is a fact about the live tree and
    # is asserted here. A reader declaring an empty domain grants nothing while looking
    # exactly like one that works — the same silent-zero this gate was built to refuse.
    declared = [r for r, _, _ in DATA_READERS if (REPO / r).is_file()]
    if declared and not data:
        print("reachability: every declared read-as-data reader returned an EMPTY domain —")
        for r in declared:
            print(f"  {r}")
        print("Either the reader's domain expression broke, or its data files are gone.")
        return 1
    reached, unreached = classify(pop, texts, data)
    for label in sorted(UNPARSEABLE):
        missing.append(("py-unparseable", label,
                        "will not parse, so the edges it declares could not be read"))
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
        # THREE absence states, named apart (memory, msg 11674): since the population is
        # HEAD, "not in pop" covers both gone-from-disk and present-but-uncommitted, and
        # the old single sentence lied about the second — it told memory a file sitting
        # right there, untracked, was "no longer in nucleus/", the same misdirection a2
        # paid for at 03:04. A fix that removes a diagnostic's trigger leaves its WORDING
        # behind, and the wording is the part the next reader inherits.
        for p in stale:
            if p in pop:
                why = "is now invoked; delete the exemption"
            elif (REPO / p).exists():
                why = "present on disk but not in HEAD — uncommitted, not gone; the exemption lands WITH its subject"
            else:
                why = "no longer in nucleus/"
            print(f"  {p} — {why}")
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
        inherited = inherited_from_dead(reached, set(EXEMPT) | set(unreached))
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
