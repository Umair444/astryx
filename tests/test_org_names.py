#!/usr/bin/env python3
"""Oracle: each org of a cog under its OWN federation name (10224 NAMES, a2 #61769 F-1): src/astryx/orgs.py fed_name,
name_clashes and its `dupnames` CLI (init.sh doctor asks it). DB-free, a fixture registry in a temp dir.

  N1 fed_name reads the HOME's .env FILE's first ASTRYX_ORG= line: never the process env (set to another name here),
     None for no file, no line, or an empty value
  N2 distinct names: no clash; `dupnames` exits 0 and prints nothing
  N3 two orgs under one name, in different CASE: one clash naming both keys; `dupnames` exits 1, `<name>\t<a> <b>`
  N4 an org with no name is no clash (absent is not equal); one org: 0
  N5 a refusing registry: `dupnames` exits 2 (never 0, which doctor would read as "each its own name")
Seams: ORG_HOME_ORGS_SRC (a mutant orgs.py, tests/mutants_org_names.py). Exit 0 · 1.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("ORG_HOME_ORGS_SRC") or REPO / "src" / "astryx" / "orgs.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


sys.path.insert(0, str(REPO / "src"))   # fed_name reads through astryx.config (the one .env reader)
spec = importlib.util.spec_from_file_location("orgs_under_test", SRC)
orgs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orgs)
UNITS = REPO / "src" / "astryx" / "data" / "org_units.json"
orgs.UNITS = UNITS                # a copy under test (the probe's seat) reads the checkout's partition data
CLI = r"""
import importlib.util, pathlib, sys
s = importlib.util.spec_from_file_location("orgs_under_test", sys.argv[1]); m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)
m.UNITS = pathlib.Path(sys.argv[2])
sys.exit(m._main(["dupnames"]))
"""


def cli(env):
    # own-env: every caller names its registry (orgs.ENV) in `env`; ASTRYX_* is dropped so no inherited name leaks in
    r = subprocess.run([sys.executable, "-c", CLI, str(SRC), str(UNITS)], capture_output=True, text=True, timeout=60,
                       env={**{k: v for k, v in os.environ.items() if not k.startswith("ASTRYX_")}, **env,
                            "PYTHONPATH": str(REPO / "src")})
    return r.returncode, r.stdout


with tempfile.TemporaryDirectory() as td:
    t = Path(td)

    def home(o, line):
        h = t / f"home-{o}"
        h.mkdir(exist_ok=True)
        if line is not None:
            (h / ".env").write_text(f"ASTRYX_DSN=postgresql://nobody@127.0.0.1:1/fx{o}\n{line}OBS_KEY=x\n")
        return h

    def reg(entries, name="cog.json"):
        f = t / name
        f.write_text(json.dumps({"orgs": {o: {"home": str(h), "db": f"fxnames_{o}"} for o, h in entries.items()}}))
        return {orgs.ENV: str(f)}

    print("N1 fed_name: the FILE's ASTRYX_ORG")
    a = home("a", "ASTRYX_ORG=a.fixture.test\n")
    old = os.environ.get("ASTRYX_ORG")   # org-home: set to ANOTHER name on purpose, to prove the file wins
    os.environ["ASTRYX_ORG"] = "other.fixture.test"
    try:
        check("the .env file's name, never the process env's", orgs.fed_name(a) == "a.fixture.test", str(orgs.fed_name(a)))
    finally:
        os.environ.pop("ASTRYX_ORG") if old is None else os.environ.__setitem__("ASTRYX_ORG", old)
    check("no .env: None", orgs.fed_name(t / "nowhere") is None)
    check("no ASTRYX_ORG line: None", orgs.fed_name(home("n", "")) is None)
    check("an empty value: None", orgs.fed_name(home("e", "ASTRYX_ORG=\n")) is None)

    print("\nN2 DISTINCT NAMES")
    b = home("b", "ASTRYX_ORG=b.fixture.test\n")
    e2 = reg({"fxa": a, "fxb": b})
    check("no clash", orgs.name_clashes(e2) == {}, str(orgs.name_clashes(e2)))
    rc, out = cli(e2)
    check("`dupnames` exits 0, prints nothing", rc == 0 and out == "", f"{rc} {out!r}")

    print("\nN3 ONE NAME, TWO ORGS (different case)")
    c = home("c", "ASTRYX_ORG=A.Fixture.Test\n")
    e3 = reg({"fxa": a, "fxb": b, "fxc": c}, "cog3.json")
    check("one clash naming both keys, case-insensitively", orgs.name_clashes(e3) == {"a.fixture.test": ["fxa", "fxc"]},
          str(orgs.name_clashes(e3)))
    rc, out = cli(e3)
    check("`dupnames` exits 1 with `<name>\\t<a> <b>`", rc == 1 and out == "a.fixture.test\tfxa fxc\n", f"{rc} {out!r}")

    print("\nN4 ABSENT IS NOT EQUAL; ONE ORG")
    e4 = reg({"fxn": t / "home-n", "fxe": t / "home-e", "fxa": a}, "cog4.json")
    check("two orgs with no name are no clash", orgs.name_clashes(e4) == {}, str(orgs.name_clashes(e4)))
    rc, out = cli({orgs.ENV: str(t / "none" / "cog.json")})
    check("one org (no registry): `dupnames` exits 0", rc == 0 and out == "", f"{rc} {out!r}")

    print("\nN5 A REFUSING REGISTRY")
    bad = t / "bad.json"
    bad.write_text("{not json")
    rc, out = cli({orgs.ENV: str(bad)})
    check("`dupnames` exits 2 (never 0)", rc == 2, f"{rc} {out!r}")

print()
print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else
      "ALL PASS: each org of a cog under its own federation name, read from its HOME's .env")
sys.exit(1 if fails else 0)
