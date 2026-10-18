"""Authored mutants for channel/home.mjs (plan-11324 S3a, the org is its HOME), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_mjs.py

Each is a plausible wrong JS twin: the checkout default kept in a cog of several orgs, the pair never checked,
another org's database accepted.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "channel/home.mjs"
ORACLE = REPO / "tests" / "test_org_home.py"
ENV = "ORG_HOME_MJS_SRC"

MUTANTS = {
    'J1 no HOME refusal: the channel server falls back to its checkout':
        ("      throw new Error('this cog runs several orgs and ASTRYX_HOME names no registered HOME: refusing the checkout')",
         '      void 0'),
    'J2 the pair is never checked':
        ('  if (multi(env)) checkPair(v, src, base, env)',
         '  if (false) checkPair(v, src, base, env)'),
    'J3 correction 2 lost in JS':
        ('  if (owner && owner !== mine)',
         '  if (false)'),
}
