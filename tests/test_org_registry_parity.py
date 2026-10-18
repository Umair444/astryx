#!/usr/bin/env python3
"""plan-11324 S3a (a2 #58917 A-1): the host's org registry is judged the SAME by both runtimes that read it.

src/astryx/orgs.py load() (spawn, the units, every python reader, the shell guards' `orgs.py multi`) and
channel/home.mjs registry() (the channel server: a server started outside spawn, a plugin join, has no python stop in
front of it) each classify every case in tests/org_registry_cases.json, and each must reach the case's WRITTEN verdict:
none (no registry), orgs:N, or refused. The verdicts are stated in the cases from orgs.py's rules, never computed from
one reader to judge the other (a verifier that shares code with its emitter proves conformance to itself).

Seams: ORG_HOME_ORGS_SRC (a mutant orgs.py), ORG_HOME_MJS_SRC (a mutant home.mjs). Exit 0 · 1 · 77 (no node).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CASES = json.loads((REPO / "tests" / "org_registry_cases.json").read_text())["cases"]
ORGS_SRC = Path(os.environ.get("ORG_HOME_ORGS_SRC") or REPO / "src" / "astryx" / "orgs.py")
MJS_SRC = Path(os.environ.get("ORG_HOME_MJS_SRC") or REPO / "channel" / "home.mjs")
UNITS = REPO / "src" / "astryx" / "data" / "org_units.json"
fails = []

PY = r"""
import importlib.util, json, sys
s = importlib.util.spec_from_file_location("orgs_under_test", sys.argv[1]); m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)
m.UNITS = __import__("pathlib").Path(sys.argv[3])      # the copy under test reads the checkout's partition data
try:
    r = m.load({"ASTRYX_COG_REGISTRY": sys.argv[2]})
    print("none" if r is None else f"orgs:{len(r)}")
except m.RegistryError:
    print("refused")
"""

JS = r"""
const [src, reg] = process.argv.slice(1)
process.env.ASTRYX_COG_REGISTRY = reg + '.absent-at-import'      // home.mjs resolves its HOME at import: no registry then
const m = await import(src)
try { const r = m.registry({ ASTRYX_COG_REGISTRY: reg }); console.log(r === null ? 'none' : `orgs:${Object.keys(r).length}`) }
catch (e) { console.log('refused') }
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def main():
    if not shutil.which("node"):
        print("SKIP (77): no node")
        return 77
    with tempfile.TemporaryDirectory() as td:
        t = Path(td).resolve()
        for d in ("a", "b"):
            (t / d).mkdir()
        # the module under test is loaded by path from a copy: a mutant and the real file load the same way
        mjs = t / "home_under_test.mjs"
        mjs.write_text(MJS_SRC.read_text())
        for c in CASES:
            reg = t / "orgs.json"
            if reg.exists():
                reg.unlink()
            if not c.get("absent"):
                text = c["text"] if "text" in c else json.dumps(c["registry"]).replace("{T}", str(t))
                reg.write_text(text)
            env = {k: os.environ[k] for k in ("PATH", "HOME") if k in os.environ}
            py = subprocess.run([sys.executable, "-B", "-c", PY, str(ORGS_SRC), str(reg), str(UNITS)], capture_output=True,
                                text=True, timeout=60, env=env).stdout.strip()
            js = subprocess.run(["node", "--input-type=module", "-e", JS, mjs.as_uri(), str(reg)], capture_output=True,
                                text=True, timeout=60, env=env, cwd=t)
            check(f"{c['name']}: orgs.py {py!r}, home.mjs {js.stdout.strip()!r}, expected {c['expect']!r}",
                  py == c["expect"] and js.stdout.strip() == c["expect"], js.stderr.strip()[-200:])
        # home.mjs carries the port partition as LITERALS (it runs from the plugin cache with no src/): they must be
        # org_units.json's, read here from the data file, never from either reader
        u = json.loads(UNITS.read_text())["units"]
        want = {"stems": sorted(k for k, v in u.items() if v["scope"] == "org" and "port" in v),
                "cog": sorted(v["port"] for v in u.values() if v["scope"] == "cog" and "port" in v)}
        lit = subprocess.run(["node", "--input-type=module", "-e", "const m = await import(process.argv[1]); console.log("
                              "JSON.stringify({stems: [...m.ORG_PORT_STEMS].sort(), cog: [...m.COG_PORTS].sort()}))",
                              mjs.as_uri()], capture_output=True, text=True, timeout=60, cwd=t,
                             env={**{k: os.environ[k] for k in ("PATH", "HOME") if k in os.environ},
                                  "ASTRYX_COG_REGISTRY": str(t / "absent.json")})
        try:
            got = json.loads(lit.stdout)
        except ValueError:
            got = None
        check("home.mjs's ORG_PORT_STEMS and COG_PORTS are org_units.json's (per-org port stems; cog ports "
              f"{want['cog']})", got == want, f"{got} != {want} {lit.stderr[-200:]}")
    return 1 if fails else 0


if __name__ == "__main__":
    rc = main()
    print()
    if rc == 1:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    elif rc == 0:
        print(f"org registry parity: orgs.py and home.mjs reach the written verdict on all {len(CASES)} cases")
    sys.exit(rc)
