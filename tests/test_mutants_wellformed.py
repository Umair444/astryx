"""Every tests/mutants_*.py still POINTS AT SOMETHING REAL — the interim ratchet.

A MUTANTS FILE MAY POINT AT AN ESTATE THIS REPO DOES NOT CARRY. mutants_wedge_watch's
SUBJECT is triggers/seed/wedge_watch.py, and triggers/ is gitignored — so in a clean
checkout that path is absent for a legitimate reason, not because anything rotted. The
first draft of this file crashed with FileNotFoundError there (reproduced in a real fresh
clone before landing, not reasoned about). An absent path is therefore classified, never
assumed: `git check-ignore` says whether the repo DELIBERATELY does not carry it. Ignored
and absent -> that arm is UNCHECKABLE here and says so by name; absent and tracked -> rot,
FAIL. Git unable to answer -> FAIL, because a detector that cannot classify must not skip.

WHAT THIS IS FOR. nucleus/mutation_probe.py is an authoring-time instrument, deliberately
NOT gated in check.sh (steward's ruling, msg 5934, reaffirmed with numbers on 2026-08-15:
gating the full run costs 100.6s, 94% of it from mutants_ear_survival's real-server arm,
and a gate slow enough to skip gets skipped — taking the fast gates' reader with it). Full
discrimination belongs in CI, where 100s is free.

But "authoring-time only" is exactly the property that lets a mutants file rot unnoticed:
nothing runs it on a schedule, so a rename or a move breaks it silently and you find out at
the worst possible moment — when you are trying to verify a NEW oracle and reach for the
tool. That is check.sh's own founding law ("a test nothing runs only proves its last manual
invocation") applied one artifact-class over.

WHAT IT CHECKS — structural reachability, sub-second, no subprocesses:
  1. the module imports at all;
  2. it declares SUBJECT, ORACLE, ENV, MUTANTS (the probe's documented contract);
  3. SUBJECT and ORACLE exist on disk;
  4. the ORACLE actually reads ENV — without that the probe silently drives the REAL
     subject and every mutant looks like a hole in the oracle rather than a broken wiring;
  5. every mutant's `old` pattern still occurs EXACTLY ONCE in its subject, which is the
     probe's own applicability condition.

WHAT IT MAY NEVER CLAIM, and there is no code path that says otherwise: that the mutants
still DISCRIMINATE. A pattern that applies cleanly can still be a mutation the oracle was
always going to catch for an unrelated reason, or one that no longer represents a real
risk. This asserts the mutant can still be APPLIED, never that it is still WORTH applying.
Discrimination is the probe's job and belongs in CI. (steward was explicit that the cheap
check must not wear the expensive one's claim, and this file's whole reason to exist is
that a residual which over-claims is worse than no residual at all.)

EMPTY IS A SKIP, NOT A PASS. If no mutants file exists — or every file's subject lives in
an estate this checkout does not carry — this verified nothing and says so with exit 77 per
check.sh's protocol. The same polarity every detector here uses, and the reason the skipped
ARMS are printed by name even on a green run: a partial pass may not wear a full one's claim.

Run: venv/bin/python tests/test_mutants_wellformed.py   (also wired into nucleus/check.sh)
"""
import importlib.util
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NUCLEUS = REPO / "nucleus"
EXIT_SKIP = 77
REQUIRED = ("SUBJECT", "ORACLE", "ENV", "MUTANTS")

# (mutants file, arm, why) for every check this run could NOT perform. Printed by name.
UNCHECKABLE = []


def mutants_files():
    """THE authority: the glob, not a hand-kept list. Same derivation as
    test_check_coverage.py — a new mutants file is covered the moment it lands."""
    return sorted(NUCLEUS.glob("mutants_*.py"))


def load(path):
    spec = importlib.util.spec_from_file_location(f"_m_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- validators, pure so they can be proven against synthetic bad input ----------


def missing_declarations(mod):
    return [n for n in REQUIRED if not hasattr(mod, n)]


def path_is_ignored(p):
    """Does this repo DELIBERATELY not carry this path? True / False / None when git cannot
    answer. None is not False: the caller must fail rather than skip on an unclassified
    absence, or the estate exemption becomes a hole any missing file can fall through."""
    try:
        r = subprocess.run(["git", "check-ignore", "-q", str(p)], cwd=REPO,
                           capture_output=True, timeout=10)
    except Exception:
        return None
    return {0: True, 1: False}.get(r.returncode)  # 128 = not a git repo -> None


def missing_paths(mod):
    """SUBJECT/ORACLE that are not on disk, split by WHY. Returns (rot, uncheckable):
    rot is the rename-and-move decay this file exists for; uncheckable is an estate path a
    clean checkout legitimately lacks (triggers/ is gitignored) — absent, not rotted, and
    unknowable from here either way."""
    rot, uncheckable = [], []
    for name in ("SUBJECT", "ORACLE"):
        p = Path(getattr(mod, name))
        if p.is_file():
            continue
        ignored = path_is_ignored(p)
        if ignored is True:
            uncheckable.append((name, f"{name}={p} is gitignored — absent in a clean "
                                      f"checkout, so nothing about it is knowable here"))
        elif ignored is False:
            rot.append(f"{name}={p} does not exist and is TRACKED territory — renamed?")
        else:
            rot.append(f"{name}={p} does not exist and git could not classify it; "
                       f"refusing to skip on an unclassified absence")
    return rot, uncheckable


def env_not_read_by_oracle(mod):
    """The probe→oracle channel. If the oracle never mentions ENV it cannot honour the
    override, so the probe drives the REAL subject and every mutant reads as a hole in the
    oracle instead of as broken wiring — a false finding pointed at innocent assertions."""
    oracle_src = Path(mod.ORACLE).read_text(errors="ignore")
    return mod.ENV not in oracle_src


def inapplicable_mutants(mod):
    """A mutant whose `old` no longer occurs exactly once can never be applied. The probe
    scores that NOT PROBED (correctly — it is not a pass), but nothing tells the author it
    has been silently unprobed since some rename. This does."""
    src = Path(mod.SUBJECT).read_text(errors="ignore")
    out = []
    for label, pair in mod.MUTANTS.items():
        old = pair[0]
        n = src.count(old)
        if n != 1:
            out.append(f"{label!r}: pattern occurs {n}x (needs exactly 1)")
    return out


def malformed_mutants(mod):
    out = []
    if not isinstance(mod.MUTANTS, dict) or not mod.MUTANTS:
        return ["MUTANTS is not a non-empty dict"]
    for label, pair in mod.MUTANTS.items():
        if not isinstance(label, str) or not label:
            out.append(f"non-string label {label!r}")
        if not (isinstance(pair, tuple) and len(pair) == 2
                and all(isinstance(x, str) for x in pair)):
            out.append(f"{label!r}: value is not a (old:str, new:str) 2-tuple")
    return out


# ---------------------------------------------------------------------------


class _Fake:
    """Synthetic module for proving each validator in its FAILING direction. Without these
    the validators below would only ever be exercised on files that pass, which proves they
    run and not that they can fail."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_validators_fail_on_synthetic_bad_input():
    """RED first, on inputs constructed to be wrong, so each assert below is known to have
    a failing direction before it is trusted on the real files."""
    assert missing_declarations(_Fake(SUBJECT="x")) == ["ORACLE", "ENV", "MUTANTS"]
    assert missing_declarations(_Fake(SUBJECT=1, ORACLE=1, ENV=1, MUTANTS=1)) == []

    # The classifier, against the REAL git in this repo — both directions. An absent path
    # under gitignored triggers/ must read as estate; an absent path in tracked nucleus/
    # must read as rot. Neither file exists, so this proves the CLASSIFICATION, not the
    # existence check that precedes it.
    assert path_is_ignored(REPO / "triggers" / "seed" / "_no_such_trigger.py") is True
    assert path_is_ignored(NUCLEUS / "_no_such_oracle_xyz.py") is False

    rot, unch = missing_paths(_Fake(SUBJECT=str(NUCLEUS / "_gone_xyz.py"), ORACLE=__file__))
    assert len(rot) == 1 and "renamed?" in rot[0] and not unch, (rot, unch)
    rot, unch = missing_paths(
        _Fake(SUBJECT=str(REPO / "triggers" / "seed" / "_gone.py"), ORACLE=__file__))
    assert not rot and [a for a, _ in unch] == ["SUBJECT"], (rot, unch)
    rot, unch = missing_paths(_Fake(SUBJECT=__file__, ORACLE=__file__))
    assert not rot and not unch, (rot, unch)

    # A REAL temp file, not __file__. First attempt used __file__ with a literal absent-name
    # and failed: the literal was IN this file because I had just typed it there, so the
    # validator correctly found it. A fixture drawn from the file that contains the fixture
    # is self-referential — the same conformance-to-self trap this whole family is about.
    with tempfile.TemporaryDirectory() as d:
        probe = Path(d) / "fake_oracle.py"
        probe.write_text('SUBJECT = os.environ.get("REAL_ENV_NAME", "x")\n')
        assert env_not_read_by_oracle(_Fake(ORACLE=str(probe), ENV="ABSENT_ENV_NAME"))
        assert not env_not_read_by_oracle(_Fake(ORACLE=str(probe), ENV="REAL_ENV_NAME"))

        subj = Path(d) / "subject.py"
        subj.write_text("alpha\nbeta\nbeta\n")
        assert inapplicable_mutants(_Fake(SUBJECT=str(subj), MUTANTS={"m": ("alpha", "x")})) == []
        twice = inapplicable_mutants(_Fake(SUBJECT=str(subj), MUTANTS={"m": ("beta", "x")}))
        assert len(twice) == 1 and "2x" in twice[0], twice
        gone = inapplicable_mutants(_Fake(SUBJECT=str(subj), MUTANTS={"m": ("gamma", "x")}))
        assert len(gone) == 1 and "0x" in gone[0], gone

    assert malformed_mutants(_Fake(MUTANTS={})) == ["MUTANTS is not a non-empty dict"]
    assert malformed_mutants(_Fake(MUTANTS={"m": ("a",)}))


def test_every_mutants_file_is_structurally_sound():
    """The real files, through the validators just proven to have a failing direction."""
    problems = []
    for path in mutants_files():
        try:
            mod = load(path)
        except Exception as e:
            problems.append(f"{path.name}: does not import — {type(e).__name__}: {e}")
            continue
        miss = missing_declarations(mod)
        if miss:
            problems.append(f"{path.name}: missing {', '.join(miss)}")
            continue

        rot, uncheckable = missing_paths(mod)
        absent = {arm for arm, _ in uncheckable}
        for bad in rot:
            problems.append(f"{path.name}: {bad}")
        for arm, why in uncheckable:
            UNCHECKABLE.append((path.name, arm, why))

        # MUTANTS shape needs no file at all, so it is checked even for an absent estate.
        # The two arms that READ a file are skipped by name rather than crashed through.
        for bad in malformed_mutants(mod):
            problems.append(f"{path.name}: {bad}")
        if "SUBJECT" not in absent and not rot:
            for bad in inapplicable_mutants(mod):
                problems.append(f"{path.name}: {bad}")
        if "ORACLE" not in absent and not rot and env_not_read_by_oracle(mod):
            problems.append(
                f"{path.name}: ORACLE {Path(mod.ORACLE).name} never mentions ENV "
                f"{mod.ENV!r} — the probe cannot redirect it, so it would drive the REAL "
                f"subject and report every mutant as a hole in the oracle")
    assert not problems, "mutants file(s) no longer point at something real:\n  " + \
        "\n  ".join(problems)


if __name__ == "__main__":
    files = mutants_files()
    if not files:
        print("SKIP: no tests/mutants_*.py present — nothing was verified here.")
        sys.exit(EXIT_SKIP)
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  ✗ {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed over {len(files)} mutants file(s): "
          + ", ".join(f.name for f in files))
    for name, arm, why in UNCHECKABLE:
        print(f"  NOT CHECKED  {name} [{arm}]: {why}")
    print("APPLICABILITY only — this does NOT claim the mutants still discriminate.")

    if failed:
        sys.exit(1)
    # A run where every file's subject lives in an estate this checkout lacks verified
    # nothing about applicability, however green the two test names above look.
    if files and len({n for n, _, _ in UNCHECKABLE}) == len(files):
        print("SKIP: every mutants file points at an estate this checkout does not carry. "
              "Nothing was verified here.")
        sys.exit(EXIT_SKIP)
    sys.exit(0)
