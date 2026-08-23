#!/usr/bin/env python3
"""Oracle for nucleus/estate_grep.sh — the three properties, both directions.

Hermetic: builds its own corpus in a tmpdir, never reads the repo or any agent's
estate. Exits 77 (SKIP, not PASS) if the subject is absent.

THE PROPERTY UNDER TEST is not "grep works". It is that the tool's ANSWER SHAPE
distinguishes three states that a bare grep collapses into two:
    0  searched, hits found
    1  searched, genuinely nothing
    2  NOT SEARCHED  <- the state a bare `0` hides
and that every answer carries the corpus size, so an empty result is self-describing
evidence rather than an assertion.

FIXTURE DISCIPLINE (canopus, 2026-08-20, learned by a mutant surviving): the expected
corpus size is stated in WORLD UNITS — this file creates exactly N_TEXT text files and
asserts the literal number — never read back from the tool's own output. A test whose
fixtures are derived from the subject proves only that the subject agrees with itself.
"""
import os, subprocess, sys, tempfile, pathlib

HERE = pathlib.Path(__file__).resolve().parent
SUBJECT = HERE.parent / "nucleus" / "estate_grep.sh"   # oracle moved to tests/; subject stayed an organ
if not SUBJECT.is_file():
    print(f"SKIP: {SUBJECT} absent"); sys.exit(77)

fails = []
def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond: fails.append(name)

def run(*args, env=None, cwd=None):
    e = dict(os.environ); e.pop("EG_EXCLUDE_DIRS", None)
    if env: e.update(env)
    p = subprocess.run([str(SUBJECT), *args], capture_output=True, text=True, env=e, cwd=cwd)
    return p.returncode, p.stdout, p.stderr

# ---------------------------------------------------------------- the corpus
# EXACTLY 5 text files, one of them inside a directory a .gitignore excludes,
# plus one binary (which -I must drop) and one excludable dir.
N_TEXT = 5
TOKEN_IGNORED = "sentinel_only_in_ignored_dir"
TOKEN_ABSENT  = "sentinel_present_in_no_file_at_all"
TOKEN_PLAIN   = "sentinel_in_a_plain_file"

tmp = tempfile.TemporaryDirectory()
root = pathlib.Path(tmp.name) / "estate"
(root / "ignored_by_git").mkdir(parents=True)
(root / "skipme").mkdir()
(root / ".gitignore").write_text("ignored_by_git/\nskipme/\n")            # 1
(root / "a.md").write_text(f"a line with {TOKEN_PLAIN} in it\n")          # 2
(root / "b.json").write_text('{"k": "v"}\n')                              # 3
(root / "ignored_by_git" / "verdict.md").write_text(
    f"2026-01-01 SKIP — {TOKEN_IGNORED}\n")                               # 4
(root / "skipme" / "noise.md").write_text("noise\n")                      # 5
(root / "blob.bin").write_bytes(bytes(range(256)))                        # binary, not text

print("== the defect: a token that lives ONLY in a gitignore'd dir ==")
rc, out, err = run(str(root), TOKEN_IGNORED)
check("found despite .gitignore (this is the whole point)", rc == 0)
check("the hit names the ignored file", "ignored_by_git/verdict.md" in out, f"rc={rc}")

print("\n== property 2: every answer carries its corpus size, and the size is TRUE ==")
rc, out, err = run(str(root), TOKEN_ABSENT)
check("genuine miss exits 1, not 0 and not 2", rc == 1, f"rc={rc}")
check("the empty answer states the corpus size", "no occurrence — searched" in out)
check(f"and the size is the literal {N_TEXT} files built here, not the tool's own count",
      f"searched {N_TEXT} files" in out, f"(binary excluded by -I)")

print("\n== property 3: NOT SEARCHED is a THIRD state, never conflated with 'nothing found' ==")
rc, out, err = run(str(root / "does_not_exist"), TOKEN_PLAIN)
check("missing root exits 2", rc == 2, f"rc={rc}")
check("...and says so on stderr", "NOT SEARCHED" in err)

empty = pathlib.Path(tmp.name) / "empty"; empty.mkdir()
rc, out, err = run(str(empty), TOKEN_PLAIN)
check("empty corpus exits 2 — an unsearched corpus is NOT a clean one", rc == 2, f"rc={rc}")
check("...and says so on stderr", "NOT SEARCHED" in err)

rc, out, err = run(str(root))
check("no token exits 2, never a silent success", rc == 2, f"rc={rc}")

# the discriminator itself, stated as its own assertion
rc_miss = run(str(root), TOKEN_ABSENT)[0]
rc_unsearched = run(str(empty), TOKEN_PLAIN)[0]
check("'searched, nothing' and 'not searched' have DIFFERENT codes",
      rc_miss != rc_unsearched, f"({rc_miss} vs {rc_unsearched})")

print("\n== exclusions shrink the corpus AND the reported count ==")
rc, out, err = run(str(root), TOKEN_ABSENT, env={"EG_EXCLUDE_DIRS": "skipme"})
check("excluding one dir reports one fewer file",
      f"searched {N_TEXT - 1} files" in out, f"(expected {N_TEXT-1})")

print("\n== a mixed run still reports coverage for the token that missed ==")
rc, out, err = run(str(root), TOKEN_PLAIN, TOKEN_ABSENT)
check("any hit means exit 0", rc == 0, f"rc={rc}")
check("the missing token still carries the corpus size",
      f"no occurrence — searched {N_TEXT} files" in out)

print("\n== the tool must not depend on the caller's cwd or shell functions ==")
rc, out, err = run(str(root), TOKEN_IGNORED, cwd="/")
check("works from an unrelated cwd", rc == 0, f"rc={rc}")

tmp.cleanup()
print()
if fails:
    print(f"FAILED {len(fails)}: " + "; ".join(fails)); sys.exit(1)
print("estate_grep: all properties hold"); sys.exit(0)
