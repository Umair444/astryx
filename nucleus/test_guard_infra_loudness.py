#!/usr/bin/env python3
"""Oracle: scout's guards must FAIL LOUD on an infra failure, not silently return None.

THE LAW (steward's refinement of my 08-14 norm, msg 5843): a guard that RAISES is not blind.
The pulse catches an evaluator error and turns it into a wire message to the owning agent
(nucleus/pulse.py:181-182), so a propagated exception is OBSERVABLE. Blindness is CREATED by
the `except: return None` pattern, which converts a loud failure into a silent all-clear.

THE DECISION RULE this file encodes, because "delete all 18 handlers" is the wrong reading —
some swallows are correct:

    INFRA FAILURE (something is broken and will stay broken until someone acts:
    .env unreadable, a required local artifact gone) -> LET IT RAISE. The pulse
    records it once, coalesced, and the owner learns.

    EXPECTED TRANSIENT (a network flake, a rate-limit, a peer down) -> SWALLOW,
    but record positive evidence of the last SUCCESSFUL observation so the
    silence stays interpretable.

    The test: would you want a wire message every tick while this condition holds?
    No -> transient, swallow and record. Yes -> infra, raise.

WHY THIS IS A CLASS ORACLE AND NOT TWO ASSERTIONS. On 08-14 I fixed card_address_drift's
observability and then swept my own directory for the fix's signature (`last_ok|blind_since`)
rather than for the DEFECT's signature. That is conformance-to-self one more time: I searched
for the property I had just implemented instead of the shape that was wrong, and steward's
independent AST sweep found nine flagged handlers in my directory that my own sweep had not
surfaced. So this asserts the class, over the live directory, and a new guard of mine that
swallows an unreadable .env fails here.

Run by nucleus/check.sh. Exits 77 (SKIP) where the gitignored bodies are absent.
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRIGGERS = REPO / "triggers/scout"   # the .env-loudness arm below is behavioural and scout-scoped;
                                     # the STATIC arm sweeps ALL of triggers/ (steward, msg 6027)
EXIT_SKIP = 77

# (module, callable) pairs whose .env read is an INFRA dependency, not a transient.
INFRA_ENV_GUARDS = ["card_address_drift", "key_arrival"]

missing = [n for n in INFRA_ENV_GUARDS if not (TRIGGERS / f"{n}.py").exists()]
if missing:
    print(f"SKIP: gitignored trigger bodies absent ({', '.join(missing)}) — nothing verified.")
    sys.exit(EXIT_SKIP)

sys.path.insert(0, str(REPO))
fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        got:  {got!r}\n        want: {want!r}")
        fails.append(label)


def load(name):
    spec = importlib.util.spec_from_file_location(name, TRIGGERS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Ctx:
    def __init__(self):
        self.state = {}

    def http(self, url, **kw):
        raise AssertionError("must not reach the network — the .env read fails first")

    def sql(self, q, params=()):
        raise AssertionError("must not reach the DB — the .env read fails first")


BOOM = PermissionError("Permission denied: .env")

print("INFRA FAILURE MUST PROPAGATE — the pulse records an evaluator error, silence records")
print("nothing. Each guard below reads .env; an unreadable .env is broken, not transient.\n")

for name in INFRA_ENV_GUARDS:
    mod = load(name)
    fn = getattr(mod, name)
    print(f"{name}:")

    # Break the .env read at its source, whatever accessor the guard happens to use.
    if hasattr(mod, "_env"):
        mod._env = lambda k, _b=BOOM: (_ for _ in ()).throw(_b)
    if hasattr(mod, "ENV"):
        class DeadEnv:
            def read_text(self, *a, **k):
                raise BOOM
        mod.ENV = DeadEnv()

    raised = None
    try:
        got = fn(Ctx())
    except Exception as e:                                   # noqa: BLE001
        raised = e
        got = "<raised>"
    check("an unreadable .env RAISES rather than returning a silent all-clear",
          got, "<raised>")
    check("...and the error names the cause, so the pulse's message is actionable",
          isinstance(raised, PermissionError), True)

print("\nSTATIC — polarity INVERTED (steward, msg 6027), and he was right that my first")
print("version could not hold. It was a DENYLIST OF TWO PHRASINGS: it flagged a swallow whose")
print("comment said 'never a false' or 'no signal', so a future handler commented 'safe to")
print("ignore' walked straight through. That is the free-text-column defect in my own gate,")
print("filed by me, eleven hours after I filed it. So: EVERY bare `except -> return None` is")
print("suspect, and the only way out is an explicit positive marker `# TRANSIENT: <reason>`.")
print("An unmarked swallow is RED by default and no novel phrasing can defeat it.\n")

ALL_TRIGGERS = REPO / "triggers"


def swallows(root):
    """Bare `return None` directly under an `except`, with no TRANSIENT marker.

    `return None, <diagnostic>` is deliberately NOT a swallow — gemini/ear_dark and
    seed/agent_dark both return a reason alongside the None, which is the loud form in a
    two-value contract. My first draft would have flagged both as defects; measuring before
    enforcing is what caught it.
    """
    out = []
    for f in sorted(root.glob("*/*.py") if root.name == "triggers" else root.glob("*.py")):
        lines = f.read_text().splitlines()
        for i, ln in enumerate(lines):
            if not i:
                continue
            code = ln.split("#", 1)[0].strip()
            if code != "return None":
                continue
            if not lines[i - 1].strip().lower().startswith("except"):
                continue
            if "TRANSIENT:" in ln:
                continue
            out.append(f"{f.parent.name}/{f.name}:{i + 1}")
    return out


mine = [s for s in swallows(ALL_TRIGGERS) if s.startswith("scout/")]
check("every swallow in MY estate carries an explicit TRANSIENT reason", mine, [])

# ENFORCING for scout, REPORTING for everyone else. The marker convention touches four other
# agents' files, and steward declined to rule it for exactly that reason — so this demonstrates
# the convention on its author's estate and makes the rest a NAMED, COUNTED debt rather than
# either a silent blind spot or an unagreed mandate. Flipping the last line to a check() is the
# one-line change if the other agents adopt it.
others = [s for s in swallows(ALL_TRIGGERS) if not s.startswith("scout/")]
print(f"  --   {len(others)} unmarked swallow(s) outside scout/ — REPORTED, not enforced "
      f"(the convention is not mine to impose):")
for s in others:
    print(f"       {s}")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
