#!/usr/bin/env python3
"""astryx · find globs that match NOTHING and pass anyway — the failure with no symptom.

    venv/bin/python nucleus/glob_vacuity.py            # run the suite, report dormant globs
    venv/bin/python nucleus/glob_vacuity.py --selftest # prove both directions, ~1s

THE CLASS. `forge`'s baseline_keys() globbed `*.json` against an archive of `*.jsonl`. No
error, no red, empty set — the shape-detection it fed was dormant for the life of the org
and was caught only because an integration partner ran it. That is the failure a clone
CANNOT catch and a crash-hunter cannot either: it does not raise, it does not fail, it
verifies nothing while reading green. A glob is the one construct in the estate whose
empty answer is indistinguishable at the callsite from a satisfied one.

WHY THIS IS RUNTIME AND NOT A PARSER. I tried the static version first: AST-walk for glob
calls, resolve the receiver, evaluate the pattern. 42 literal globs, ZERO receivers
resolvable — they are `(REPO / "homes")`, `WIKI`, `Path(td)`, expressions a parser has to
re-implement the program to evaluate. The instrument that works is the one that watches
what actually ran: patch `Path.glob`/`rglob`, record every call with its site, root and
pattern, and let the estate tell you which of them never match anything.

THE DISCRIMINATOR, and it is the whole design. A zero-match glob is NOT a finding — a name
resolver misses constantly and that is its job. `nucleus/charter.py:60` alone produced 339
empty events on the first run, resolving names by `**/<name>.md`. What separates a LOOKUP
from a DORMANT POPULATION is the site's whole history rather than any one call:

    a lookup     varies its pattern (166 distinct at charter.py:60) and sometimes hits
    a dormant    asks ONE constant question of one root and never gets an answer

So a site is reported only when EVERY pattern it used matches nothing today AND it used at
most MAX_PATTERNS of them. Fixture corpora under /tmp are excluded: a temp dir that no
longer exists cannot be interrogated, and dormancy is not the question there anyway.

MEASURED BASELINE, 2026-08-20: 34 glob sites across a full suite run, ZERO dormant. The
known member was already repaired, which is why it does not appear. That number is the
point of running this — a report of "none" is only worth having from an instrument that
has been shown to find one, so `--selftest` plants a dormant glob and requires it found.
"""
import argparse
import collections
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAX_PATTERNS = 2          # more than this and the site is resolving names, not a population
EXIT_FOUND = 1

SHIM = '''\
"""Injected by nucleus/glob_vacuity.py — records every Path.glob/rglob call."""
import os, pathlib, traceback

LOG = os.environ.get("GLOB_VACUITY_LOG")
if LOG:
    _glob, _rglob = pathlib.Path.glob, pathlib.Path.rglob

    def _record(kind, self, pattern):
        st = traceback.extract_stack()[:-2]
        caller = next((f"{f.filename}:{f.lineno}" for f in reversed(st)
                       if "sitecustomize" not in f.filename), "unknown")
        try:
            with open(LOG, "a") as fh:
                fh.write(f"{caller}\\t{kind}\\t{self}\\t{pattern}\\n")
        except OSError:
            pass

    def glob(self, pattern, *a, **k):
        out = list(_glob(self, pattern, *a, **k))
        _record("glob", self, pattern)
        return iter(out)

    def rglob(self, pattern, *a, **k):
        out = list(_rglob(self, pattern, *a, **k))
        _record("rglob", self, pattern)
        return iter(out)

    pathlib.Path.glob, pathlib.Path.rglob = glob, rglob
'''


def observe(cmd, workdir, shim_dir, log):
    """Run `cmd` with the shim on PYTHONPATH. Its exit code is NOT our verdict: this tool
    reports on globs, and a suite that fails for unrelated reasons still produced the
    observations we came for."""
    shim_dir.mkdir(parents=True, exist_ok=True)
    (shim_dir / "sitecustomize.py").write_text(SHIM)
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{shim_dir}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    env["GLOB_VACUITY_LOG"] = str(log)
    return subprocess.run(cmd, cwd=workdir, env=env,
                          capture_output=True, text=True).returncode


def analyse(log, skip_temp=True):
    """(site, kind) -> the patterns and roots it used. Returns (all_sites, dormant).

    `skip_temp` is a POLICY OF THE ESTATE RUN, not a property of the analysis, which is why
    it is a parameter: fixture corpora under /tmp are not populations anyone can be dormant
    against, but the selftest plants its own corpus in exactly that place. Hard-coding the
    exclusion made the tool structurally unable to find its own planted defect — the
    selftest caught that on its first run, which is the entire argument for having one."""
    sites = collections.defaultdict(lambda: {"pats": set(), "roots": set()})
    for line in log.read_text().splitlines() if log.exists() else []:
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        caller, kind, root, pat = parts
        if skip_temp and root.startswith(tempfile.gettempdir()):
            continue                      # fixture corpus, not an estate population
        sites[(caller, kind)]["pats"].add(pat)
        sites[(caller, kind)]["roots"].add(root)

    dormant = []
    for (caller, kind), d in sorted(sites.items()):
        if len(d["pats"]) > MAX_PATTERNS:
            continue                      # a name resolver; missing is its normal answer
        hit = False
        for r in d["roots"]:
            for p in d["pats"]:
                try:
                    if any(True for _ in getattr(Path(r), kind)(p)):
                        hit = True
                except OSError:
                    pass
        if not hit:
            dormant.append((caller, kind, sorted(d["roots"]), sorted(d["pats"])))
    return sites, dormant


def report(sites, dormant):
    print(f"glob-vacuity: {len(sites)} glob site(s) observed outside temp dirs")
    if not dormant:
        print("  none dormant — every site matched something on this host.")
        print("  NOT a claim about globs this run never reached: a site nothing executed")
        print("  cannot be observed, and is invisible here rather than clean.")
        return 0
    print(f"\n  DORMANT — matched NOTHING and nothing noticed ({len(dormant)}):")
    for caller, kind, roots, pats in dormant:
        print(f"    {caller.replace(str(REPO) + '/', '')}")
        print(f"        {kind}({', '.join(pats)}) over {', '.join(roots)}")
    print("\n  Each of these verifies nothing while reading green. Either the pattern is")
    print("  wrong for the corpus (*.json against a *.jsonl archive is the known member),")
    print("  or the corpus moved. Assert the result non-empty, or classify it UNVERIFIED.")
    return EXIT_FOUND


def selftest():
    """PROVE BOTH DIRECTIONS. A tool that reports 'none' is worth nothing until it has been
    shown to find one — the report and the failure to observe look identical from outside."""
    ok = True
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        corpus = d / "corpus"
        (corpus / "sub").mkdir(parents=True)
        (corpus / "sub" / "real.jsonl").write_text("{}\n")
        script = d / "subject.py"
        script.write_text(
            "from pathlib import Path\n"
            f"C = Path({str(corpus)!r})\n"
            "list(C.glob('sub/*.json'))     # DORMANT: the archive holds .jsonl\n"
            "list(C.glob('sub/*.jsonl'))    # live\n")
        log = d / "log.tsv"
        observe([sys.executable, str(script)], d, d / "shim", log)
        sites, dormant = analyse(log, skip_temp=False)
        found = {p for _, _, _, pats in dormant for p in pats}
        ok &= _check("the planted *.json-against-.jsonl glob is reported",
                     "sub/*.json" in found, f"dormant={dormant}")
        ok &= _check("...and the sibling glob that DOES match is not accused",
                     "sub/*.jsonl" not in found, f"dormant={dormant}")

        # A lookup site: many patterns, mostly missing. Must not be reported.
        script.write_text(
            "from pathlib import Path\n"
            f"C = Path({str(corpus)!r})\n"
            "for n in ('a','b','c','d','real'):\n"
            "    list(C.glob(f'sub/{n}.jsonl'))\n")
        log2 = d / "log2.tsv"
        observe([sys.executable, str(script)], d, d / "shim", log2)
        _, dormant2 = analyse(log2, skip_temp=False)
        ok &= _check("a name-resolver site (many patterns) is never accused",
                     not dormant2, f"dormant={dormant2}")
    print("\n" + ("SELFTEST PASS" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


def _check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond and detail:
        print(f"        {detail}")
    return cond


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true",
                    help="plant a dormant glob and require this tool to find it")
    ap.add_argument("--cmd", default="bash nucleus/check.sh",
                    help="what to observe (default: the full gate suite)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        shim = d / "shim"
        shim.mkdir()
        log = d / "log.tsv"
        print(f"glob-vacuity: observing `{args.cmd}` — the suite's own verdict is not this "
              f"tool's verdict")
        observe(args.cmd.split(), REPO, shim, log)
        return report(*analyse(log))


if __name__ == "__main__":
    sys.exit(main())
