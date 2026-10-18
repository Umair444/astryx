#!/usr/bin/env python3
"""plan-11324 S3b 4/n (#58435; seed #59953/#59954): a systemd unit NAME is host-wide, so on a host that runs several
orgs each org's units are instance FILES `<stem>@<org>.<suffix>`, and the partition of every unit (per-org or
host-scoped, and the port it binds) is declared once in src/astryx/data/org_units.json.

  U0 THE PARTITION IS TOTAL: every stem init.sh units() writes is declared, every declared stem is written, and
     every write goes through _uw (no `cat > "$UD/…"` left). RED control: a planted extra stem is accused
  U1 one org (no registry): plain names, exactly as before (no `@` anywhere)
  U2 several orgs, org B: ONLY B's port-free units, each `@<B>` (pulse+timer, residents, its runner+timer); the
     host-scoped ones (observatory, canvas, gateway) are NOT written, and a port-binding one (whatsapp: B has its
     routes) is NOT written, each with its reason on stderr
  U3 orgs A and B rendered into ONE directory: disjoint file sets, and A's files survive B's run byte for byte
  U4 every timer has its same-named service (systemd activates `<x>.service` for `<x>.timer`)
  U6 systemd-analyze verify accepts every @<B> file (positive control: a broken one is rejected); NOT RUN without it
  U5 the resolver: orgs.unit() is `astryx-pulse.timer` on one org, `astryx-pulse@<A>.timer` under HOME-A, and raises
     with no HOME carried; pulse_witness.timer_unit() follows it

Seams (org_home_fixture.SEAMS): ORG_HOME_INIT_SRC, ORG_HOME_ORGS_SRC, ORG_HOME_UNITS_DATA_SRC. Exit 0 · 1 · 77.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from org_home_fixture import FixtureUnavailable, OrgHomes  # noqa: E402

fails = []
WRITE = re.compile(r"_uw (astryx-[a-z0-9-]+) (service|timer) && cat > \"\$_UF\"")


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def partition_gap(init_text: str, doc: dict) -> tuple[set, set, list]:
    """(written but undeclared, declared but never written, raw writes that bypass _uw). Runner stems (astryx-$stem)
    take the doc's `runners` scope."""
    block = re.search(r"^units\(\) \{.*?^\}$", init_text, re.S | re.M).group(0)
    written = {m.group(1) for m in WRITE.finditer(block)}
    declared = set(doc["units"])
    raw = re.findall(r'cat > "\$UD/[^"]*"', block)
    return written - declared, declared - written, raw


def main():
    try:
        fx = OrgHomes().__enter__()
    except FixtureUnavailable as e:
        print(f"SKIP (77): {e}")
        return 77
    try:
        co, A, B = fx.co, fx.home["a"], fx.home["b"]
        doc = json.loads((co / "src/astryx/data/org_units.json").read_text())

        print("U0 THE PARTITION IS TOTAL")
        extra, missing, raw = partition_gap((co / "init.sh").read_text(), doc)
        check("every stem units() writes is declared in org_units.json", not extra, str(sorted(extra)))
        check("every declared stem is written by units()", not missing, str(sorted(missing)))
        check("every unit write goes through _uw (no raw `cat > \"$UD/…\"`)", not raw, str(raw))
        planted = (co / "init.sh").read_text().replace(
            '  _uw astryx-pulse timer && cat > "$_UF" <<EOF',
            '  _uw astryx-fxnew service && cat > "$_UF" <<EOF\nEOF\n  _uw astryx-pulse timer && cat > "$_UF" <<EOF', 1)
        e2, _, _ = partition_gap(planted, doc)
        check("RED control: a planted undeclared stem is accused", e2 == {"astryx-fxnew"}, str(e2))

        block = re.search(r"^units\(\) \{.*?^\}$", (co / "init.sh").read_text(), re.S | re.M).group(0)
        (co / "units_fx.sh").write_text("die() { echo \"$*\" >&2; exit 1; }\n_docker_host_ip() { echo 172.17.0.1; }\n"
                                        + block + "\nUNITS_DIR=\"$1\" units\n")
        # B carries a chat route (a port-binding unit it would get) and a runner (a per-org port-free one)
        (B / "bridges").mkdir(exist_ok=True)
        (B / "bridges" / "routes-whatsapp.json").write_text("{}\n")
        (B / "nucleus").mkdir(exist_ok=True)
        (B / "nucleus" / "runners.conf").write_text("fxjob | org | *-*-* 03:00:00 | scripts/backup.sh | a fixture job\n")

        def render(env, out):
            return subprocess.run(["bash", "-euo", "pipefail", "units_fx.sh", str(out)], env=env, cwd=co,
                                  capture_output=True, text=True, timeout=60)

        def files(d):
            return {p.name: p.read_bytes() for p in Path(d).glob("*")} if Path(d).is_dir() else {}

        print("\nU1 ONE ORG: PLAIN NAMES, AS BEFORE")
        one = fx.env(ASTRYX_ORG_REGISTRY=str(fx.t / "no-registry.json"))
        r = render(one, fx.t / "u_one")
        names = sorted(files(fx.t / "u_one"))
        check("units() renders (rc 0) with the shipped set", r.returncode == 0 and "astryx-pulse.timer" in names
              and "astryx-observatory.service" in names, f"rc {r.returncode} {names} {r.stderr[-300:]}")
        check("no instance name anywhere (no `@`)", names and not any("@" in n for n in names), str(names))

        print("\nU2 SEVERAL ORGS: B'S OWN PORT-FREE UNITS, NOTHING ELSE")
        ob = fx.org["b"]
        r = render(fx.env(ASTRYX_HOME=str(B)), fx.t / "u_b")
        got = set(files(fx.t / "u_b"))
        want = {f"astryx-pulse@{ob}.service", f"astryx-pulse@{ob}.timer", f"astryx-residents@{ob}.service",
                f"astryx-fxjob@{ob}.service", f"astryx-fxjob@{ob}.timer"}
        check("rc 0, and exactly B's port-free units, each @<B>", r.returncode == 0 and got == want,
              f"rc {r.returncode} got {sorted(got)} {r.stderr[-300:]}")
        for stem in ("astryx-observatory", "astryx-canvas", "astryx-gateway"):
            check(f"{stem}: not written, HOST-scoped (said on stderr)", f"{stem} is HOST-scoped" in r.stderr
                  and not any(n.startswith(stem) for n in got), r.stderr[-300:])
        check("astryx-whatsapp (B has its routes): not written, it needs its registry port (said on stderr)",
              "astryx-whatsapp binds a port" in r.stderr and not any(n.startswith("astryx-whatsapp") for n in got),
              r.stderr[-300:])

        print("\nU3 TWO ORGS, ONE DIRECTORY: DISJOINT")
        both = fx.t / "u_ab"
        ra = render(fx.env(ASTRYX_HOME=str(A)), both)
        a_files = files(both)
        rb = render(fx.env(ASTRYX_HOME=str(B)), both)
        ab = files(both)
        b_only = {n for n in ab if n not in a_files}
        check("A's render, then B's: both rc 0", ra.returncode == 0 and rb.returncode == 0,
              (ra.stderr + rb.stderr)[-300:])
        check("A's files survive B's run byte for byte (two orgs never write one file)",
              a_files and all(ab.get(n) == v for n, v in a_files.items()), str(sorted(a_files)))
        check("B added only its own @<B> files", b_only and all(f"@{ob}." in n for n in b_only), str(sorted(b_only)))

        print("\nU4 EVERY TIMER HAS ITS SERVICE")
        for d in ("u_one", "u_b"):
            fs = set(files(fx.t / d))
            orphans = sorted(t for t in fs if t.endswith(".timer") and t[:-6] + ".service" not in fs)
            check(f"{d}: every <x>.timer has <x>.service", not orphans, str(orphans))

        print("\nU6 SYSTEMD ACCEPTS THE INSTANCE FILES")
        import shutil
        if not shutil.which("systemd-analyze"):
            print("  ·  NOT RUN: no systemd-analyze here (U2's names are unverified by systemd itself)")
        else:
            def verify(paths):
                return subprocess.run(["systemd-analyze", "verify", "--man=no", *map(str, paths)],
                                      capture_output=True, text=True, timeout=60)
            r = verify(sorted((fx.t / "u_b").glob("*")))
            check("systemd-analyze verify: every @<B> file is a valid unit", r.returncode == 0, (r.stdout + r.stderr)[-400:])
            bad = fx.t / "sv-bad" / f"astryx-fxbad@{ob}.service"
            bad.parent.mkdir()
            bad.write_text("[Service]\nExecStart=relative/path\n")
            check("positive control: it rejects a broken instance file", verify([bad]).returncode != 0)

        print("\nU5 THE RESOLVER")
        probe = ("import sys; sys.path.insert(0, sys.argv[1] + '/src'); sys.path.insert(0, sys.argv[1] + '/bridges')\n"
                 "from astryx import orgs; import pulse_witness as pw\n"
                 "print(orgs.unit('astryx-pulse', 'timer'), pw.timer_unit(), orgs.unit('astryx-residents'))")
        py = str(co / "venv" / "bin" / "python")

        def ask(env):
            return subprocess.run([py, "-c", probe, str(co)], env=env, cwd="/", capture_output=True, text=True,
                                  timeout=30)
        r = ask(one)
        check("one org: astryx-pulse.timer (pulse_witness the same), astryx-residents.service",
              r.stdout.split() == ["astryx-pulse.timer", "astryx-pulse.timer", "astryx-residents.service"],
              r.stdout + r.stderr[-200:])
        oa = fx.org["a"]
        r = ask(fx.env(ASTRYX_HOME=str(A)))
        check(f"HOME-A: astryx-pulse@{oa}.timer, and pulse_witness follows it",
              r.stdout.split() == [f"astryx-pulse@{oa}.timer"] * 2 + [f"astryx-residents@{oa}.service"],
              r.stdout + r.stderr[-200:])
        r = ask(fx.env())
        check("no HOME carried: it raises (NoHome), never a plain name as a guess",
              r.returncode != 0 and "NoHome" in r.stderr, r.stderr[-200:])
        return 1 if fails else 0
    finally:
        fx.__exit__(None, None, None)


if __name__ == "__main__":
    rc = main()
    print()
    if rc == 1:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    elif rc == 0:
        print("org home units: each org's units are its own instance files; the partition is total; one org is plain")
    sys.exit(rc)
