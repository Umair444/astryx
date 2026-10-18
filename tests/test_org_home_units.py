#!/usr/bin/env python3
"""plan-11324 S3b 4/n (#58435; seed #59953/#59954): a systemd unit NAME is host-wide, so on a host that runs several
orgs each org's units are instance FILES `<stem>@<org>.<suffix>`, and the partition of every unit (per-org or
cog-scoped, and the port it binds) is declared once in src/astryx/data/org_units.json.

  U0 THE PARTITION IS TOTAL: every stem init.sh units() writes is declared, every declared stem is written, and
     every write goes through _uw (no `cat > "$UD/…"` left). RED control: a planted extra stem is accused
  U1 one org (no registry): plain names, exactly as before (no `@` anywhere)
  U2 several orgs, org B: ONLY B's own units, each `@<B>` (pulse+timer, residents, its runner+timer, and the
     port-binding ones whose presence signal fires: whatsapp, B has its routes; senses, B has a sensor); the
     cog-scoped ones (observatory, canvas, gateway) are NOT written, each with its reason on stderr
  U3 orgs A and B rendered into ONE directory: disjoint file sets, and A's files survive B's run byte for byte
  U4 every timer has its same-named service (systemd activates `<x>.service` for `<x>.timer`)
  U6 systemd-analyze verify accepts every @<B> file (positive control: a broken one is rejected); NOT RUN without it
  U7 PORTS (S3b 5/n, seed #59954 ruling 3): B's port units bind B's REGISTRY ports (never the fixed literal); A's
     and B's differ in one directory; an org whose wanted unit has no registry port REFUSES (rc != 0, the stem named,
     no file of it written); a port it doesn't want needs no declaration. Every `${_UP:-<n>}` default in units() is
     org_units.json's port for that stem, and no per-org port unit binds a bare literal
  U8 SERVE-TIME PORTS: senses and the growbot body serve on 8460/8470 on one org and on the org's registry port under
     HOME-A (uvicorn.run captured, nothing bound; the growbot's serial a missing fixture path, a virtual body); a
     GROWBOT_PORT naming another port refuses; the growbot MCP reaches A's body host on A's port
  U9 PORT LITERALS ARE DECLARED (tests/org_port_literals.json): every tracked file whose executable text names a
     per-org fixed port is declared with its reason, and every declared file still has one; RED control: a planted
     file is accused. The `s3c` entries are the S3c trip (the observatory's ear/growbot proxies)
  U10 a runners.conf stem that is a declared unit's (`gateway` -> astryx-gateway) refuses (a2 #60394 A-2)
  U5 the resolver: orgs.port() is None on one org, the registry's under HOME-A, NoHome with none; orgs.unit() is `astryx-pulse.timer` on one org, `astryx-pulse@<A>.timer` under HOME-A, and raises
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


def defaults_gap(init_text: str, doc: dict) -> list:
    """Each per-org port unit's block in units(): every `${_UP:-<n>}` names the stem's declared port, at least one is
    there, and no `--port <digits>` or `:<port>` literal of it is left bare (a bare one is the fixed port in a cog)."""
    block = re.search(r"^units\(\) \{.*?^\}$", init_text, re.S | re.M).group(0)
    out = []
    for m in WRITE.finditer(block):
        stem = m.group(1)
        u = doc["units"].get(stem, {})
        if u.get("scope") != "org" or "port" not in u:
            continue
        body = block[m.end():block.index("\nEOF\n", m.end())]
        got = [int(n) for n in re.findall(r"\$\{_UP:-(\d+)\}", body)]
        if not got:
            out.append(f"{stem}: no ${{_UP:-…}} in its unit")
        out += [f"{stem}: default {n} is not its declared {u['port']}" for n in got if n != u["port"]]
        bare = re.findall(r"(?:--port\s+|:)" + str(u["port"]) + r"\b", body)
        out += [f"{stem}: a bare {b!r}" for b in bare]
    return out


def port_literal_files(co: Path, ports: list) -> dict:
    """{tracked file: [line numbers]} whose EXECUTABLE text (devtools/org_census.code_lines: comments and docstrings
    out) names one of `ports` as a number (not inside a longer number, a hex colour or a word). tests/ excluded."""
    sys.path.insert(0, str(co / "devtools"))
    from org_census import code_lines
    pat = re.compile(r"(?<![\w.#])(?:" + "|".join(ports) + r")(?![\w.])")
    ls = subprocess.run(["git", "-C", str(co), "ls-files"], capture_output=True, text=True).stdout.split()
    out = {}
    for f in ls:
        p = co / f
        if f.startswith("tests/") or p.suffix not in (".py", ".sh", ".mjs", ".js", ".ts", ".cjs") or not p.is_file():
            continue
        hits = [n for n, code, _ in code_lines(p) if pat.search(code)]
        if hits:
            out[f] = hits
    return out


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
                                        + block + "\nUNITS_DIR=\"$1\" units\necho \"UED=[$UNITS_EXPECT_DISABLED]\"\n")
        # B carries a chat route (a port-binding unit it would get) and a runner (a per-org port-free one)
        (B / "bridges").mkdir(exist_ok=True)
        (B / "bridges" / "routes-whatsapp.json").write_text("{}\n")
        (B / "sensors" / "fxagent").mkdir(parents=True, exist_ok=True)   # a sensor: senses' presence signal
        (B / "sensors" / "fxagent" / "fxsense.py").write_text("def read():\n    return {}\n")
        # a growbot grant with a REMOTE body: the unit is written and declared installed-but-NOT-enabled, by its FILE name
        (B / "agents" / "fxbot.md").write_text("# fxbot\nGrants: growbot\n")
        with open(B / ".env", "a") as f:
            f.write("GROWBOT_BODY_URL=http://192.0.2.7\n")
        (B / "nucleus").mkdir(exist_ok=True)
        # a comment with an apostrophe first: units() must skip it before xargs (which refuses an unmatched quote)
        (B / "nucleus" / "runners.conf").write_text("# the org's fixture runners\n  # an indented one's too\n"
                                                    "fxjob | org | *-*-* 03:00:00 | scripts/backup.sh | a fixture job\n")

        def render(env, out):
            return subprocess.run(["bash", "-euo", "pipefail", "units_fx.sh", str(out)], env=env, cwd=co,
                                  capture_output=True, text=True, timeout=60)

        def files(d):
            return {p.name: p.read_bytes() for p in Path(d).glob("*")} if Path(d).is_dir() else {}

        print("\nU1 ONE ORG: PLAIN NAMES, AS BEFORE")
        one = fx.env(ASTRYX_COG_REGISTRY=str(fx.t / "no-registry.json"))
        r = render(one, fx.t / "u_one")
        names = sorted(files(fx.t / "u_one"))
        check("units() renders (rc 0) with the shipped set", r.returncode == 0 and "astryx-pulse.timer" in names
              and "astryx-observatory.service" in names, f"rc {r.returncode} {names} {r.stderr[-300:]}")
        check("no instance name anywhere (no `@`)", names and not any("@" in n for n in names), str(names))

        print("\nU2 SEVERAL ORGS: B'S OWN UNITS, NOTHING ELSE (its runners.conf opens with a comment that has an apostrophe)")
        ob = fx.org["b"]
        r = render(fx.env(ASTRYX_HOME=str(B)), fx.t / "u_b")
        got = set(files(fx.t / "u_b"))
        want = {f"astryx-pulse@{ob}.service", f"astryx-pulse@{ob}.timer", f"astryx-residents@{ob}.service",
                f"astryx-fxjob@{ob}.service", f"astryx-fxjob@{ob}.timer", f"astryx-whatsapp@{ob}.service",
                f"astryx-senses@{ob}.service", f"astryx-growbot@{ob}.service"}
        check("rc 0, and exactly B's own units, each @<B>", r.returncode == 0 and got == want,
              f"rc {r.returncode} got {sorted(got)} {r.stderr[-300:]}")
        check(f"the remote body's growbot is declared off by its FILE name astryx-growbot@{ob}.service",
              f"UED=[ astryx-growbot@{ob}.service]" in r.stdout, r.stdout[-200:])
        for stem in ("astryx-observatory", "astryx-canvas", "astryx-gateway"):
            check(f"{stem}: not written, COG-scoped (said on stderr)", f"{stem} is COG-scoped" in r.stderr
                  and not any(n.startswith(stem) for n in got), r.stderr[-300:])

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

        print("\nU7 PORTS: EACH ORG'S OWN, FROM THE REGISTRY")
        bf = files(fx.t / "u_b")
        wa = bf.get(f"astryx-whatsapp@{ob}.service", b"").decode()
        pb = fx.ports["b"]
        check(f"whatsapp@B binds B's registry port --port {pb['astryx-whatsapp']}",
              f"--port {pb['astryx-whatsapp']}\n" in wa and "--port 8477" not in wa, wa[-300:])
        se = bf.get(f"astryx-senses@{ob}.service", b"").decode()
        check(f"senses@B's description names B's port :{pb['astryx-senses']}", f":{pb['astryx-senses']})" in se, se[:200])
        pa = fx.ports["a"]
        (A / "bridges").mkdir(exist_ok=True)
        (A / "bridges" / "routes-whatsapp.json").write_text("{}\n")
        both2 = fx.t / "u_ab2"
        ra, rb = render(fx.env(ASTRYX_HOME=str(A)), both2), render(fx.env(ASTRYX_HOME=str(B)), both2)
        ab2 = files(both2)
        wa_a = ab2.get(f"astryx-whatsapp@{fx.org['a']}.service", b"").decode()
        wa_b = ab2.get(f"astryx-whatsapp@{ob}.service", b"").decode()
        check("one directory: A's whatsapp on A's port, B's on B's, never one port",
              f"--port {pa['astryx-whatsapp']}\n" in wa_a and f"--port {pb['astryx-whatsapp']}\n" in wa_b,
              (wa_a[-120:] + " | " + wa_b[-120:] + (ra.stderr + rb.stderr)[-200:]))
        (A / "bridges" / "routes-whatsapp.json").unlink()
        # B's entry without its whatsapp port: B wants whatsapp (its routes), so units() REFUSES
        reg = json.loads(fx.reg.read_text())
        reg["orgs"][ob]["ports"].pop("astryx-whatsapp")
        reg["orgs"][fx.org["a"]]["ports"] = {}          # A wants none of these: an org declares only what it runs
        noport = fx.t / "noport.json"
        noport.write_text(json.dumps(reg))
        r = render(fx.env(ASTRYX_HOME=str(B), ASTRYX_COG_REGISTRY=str(noport)), fx.t / "u_np")
        np_files = files(fx.t / "u_np")
        check("B wants whatsapp and declares no port: REFUSED (rc != 0, the stem named), no whatsapp file",
              r.returncode != 0 and "astryx-whatsapp is wanted" in r.stderr
              and not any(n.startswith("astryx-whatsapp") for n in np_files), f"rc {r.returncode} {r.stderr[-300:]}")
        r = render(fx.env(ASTRYX_HOME=str(A), ASTRYX_COG_REGISTRY=str(noport)), fx.t / "u_na")
        check("A wants no port unit and declares no ports: rc 0 (only what it runs needs a port)",
              r.returncode == 0 and not any(n.startswith(("astryx-whatsapp", "astryx-senses")) for n in files(fx.t / "u_na")),
              f"rc {r.returncode} {r.stderr[-300:]}")
        dflt = defaults_gap((co / "init.sh").read_text(), doc)
        check("every ${_UP:-<n>} default is org_units.json's port, and no per-org port unit binds a bare literal",
              not dflt, str(dflt))
        planted = (co / "init.sh").read_text().replace("--port ${_UP:-8478}", "--port 8478", 1)
        check("RED control: a planted bare --port 8478 in telegram's unit is accused",
              any("astryx-telegram" in d for d in defaults_gap(planted, doc)), str(defaults_gap(planted, doc)))

        print("\nU8 SERVE-TIME PORTS (uvicorn.run captured, nothing bound)")
        serve = ("import runpy, sys, types; sys.path.insert(0, sys.argv[1] + '/src')\n"
                 "u = types.ModuleType('uvicorn'); u.run = lambda app, **kw: print('PORT', kw['port']); "
                 "sys.modules['uvicorn'] = u\n"
                 "runpy.run_module(sys.argv[2], run_name='__main__')")
        py5 = str(co / "venv" / "bin" / "python")
        nodev = str(fx.t / "no-such-serial-device")

        def served(mod, env):
            return subprocess.run([py5, "-c", serve, str(co), mod], env={**env, "GROWBOT_SERIAL": nodev}, cwd=co,
                                  capture_output=True, text=True, timeout=60)
        for mod, stem, fixed in (("astryx.pulse.senses", "astryx-senses", 8460),
                                 ("astryx.contrib.growbot_body", "astryx-growbot", 8470)):
            r = served(mod, one)
            check(f"{mod}, one org: serves on {fixed}", f"PORT {fixed}" in r.stdout, (r.stdout + r.stderr)[-300:])
            r = served(mod, fx.env(ASTRYX_HOME=str(A)))
            check(f"{mod}, HOME-A: serves on A's registry port {pa[stem]}", f"PORT {pa[stem]}" in r.stdout,
                  (r.stdout + r.stderr)[-300:])
        r = served("astryx.contrib.growbot_body", fx.env(ASTRYX_HOME=str(A), GROWBOT_PORT="8470"))
        check("growbot body, HOME-A with GROWBOT_PORT=8470 (not A's): refuses, binds nothing",
              r.returncode != 0 and "PORT" not in r.stdout and "not this org's registry port" in r.stderr,
              (r.stdout + r.stderr)[-300:])
        r = served("astryx.pulse.senses", fx.env(ASTRYX_HOME=str(A), ASTRYX_COG_REGISTRY=str(noport)))
        check("senses, HOME-A whose entry declares no senses port: refuses, never the fixed 8460",
              r.returncode != 0 and "PORT" not in r.stdout and "declares no port for astryx-senses" in r.stderr,
              (r.stdout + r.stderr)[-300:])
        mcp_probe = ("import sys; sys.argv[1:1] = []; import importlib.util as u\n"
                     "s = u.spec_from_file_location('gb_mcp', sys.argv[1] + '/mcp/growbot/server.py'); "
                     "m = u.module_from_spec(s); s.loader.exec_module(m); print(m._body_url())")
        r = subprocess.run([py5, "-c", mcp_probe, str(co)], env={**fx.env(ASTRYX_HOME=str(A))}, cwd="/",
                           capture_output=True, text=True, timeout=60)
        if "ModuleNotFoundError: No module named 'mcp'" in r.stderr:
            print("  ·  NOT RUN: no `mcp` package in this venv (the growbot MCP's URL is unverified)")
        else:
            check(f"growbot MCP, HOME-A: http://127.0.0.1:{pa['astryx-growbot']}",
                  r.stdout.strip() == f"http://127.0.0.1:{pa['astryx-growbot']}", (r.stdout + r.stderr)[-300:])

        print("\nU10 A RUNNER CAN'T TAKE A DECLARED UNIT'S NAME (a2 #60394 A-2)")
        keep = (B / "nucleus" / "runners.conf").read_text()
        (B / "nucleus" / "runners.conf").write_text("gateway | org | *-*-* 03:00:00 | scripts/backup.sh | collides\n")
        r = render(fx.env(ASTRYX_HOME=str(B)), fx.t / "u_rc")
        check("a runner named `gateway` (astryx-gateway): REFUSED, nothing written under that name",
              r.returncode != 0 and "runner 'gateway'" in r.stderr
              and not any("gateway" in n for n in files(fx.t / "u_rc")), f"rc {r.returncode} {r.stderr[-300:]}")
        (B / "nucleus" / "runners.conf").write_text(keep)

        print("\nU9 PORT LITERALS ARE DECLARED")
        decl = json.loads((co / "tests" / "org_port_literals.json").read_text())["files"]
        fixed = sorted({str(u["port"]) for u in doc["units"].values() if u["scope"] == "org" and "port" in u})
        found = port_literal_files(co, fixed)
        check("every file with a per-org port literal is declared", not set(found) - set(decl),
              str({f: found[f] for f in set(found) - set(decl)}))
        check("every declared file still has one (no stale declaration)", not set(decl) - set(found),
              str(sorted(set(decl) - set(found))))
        (co / "bridges" / "fxport.py").write_text("PORT = 8478\n")
        subprocess.run(["git", "-C", str(co), "add", "-N", "bridges/fxport.py"], capture_output=True)
        check("RED control: a planted bridges/fxport.py (PORT = 8478) is found",
              "bridges/fxport.py" in port_literal_files(co, fixed), "")
        (co / "bridges" / "fxport.py").unlink()
        subprocess.run(["git", "-C", str(co), "rm", "-q", "--cached", "bridges/fxport.py"], capture_output=True)
        print("  ·  the S3c trip: " + ", ".join(sorted(f for f, d in decl.items() if d.get("s3c"))))

        print("\nU5 THE RESOLVER")
        probe = ("import sys; sys.path.insert(0, sys.argv[1] + '/src'); sys.path.insert(0, sys.argv[1] + '/bridges')\n"
                 "from astryx import orgs; import pulse_witness as pw\n"
                 "print(orgs.unit('astryx-pulse', 'timer'), pw.timer_unit(), orgs.unit('astryx-residents'), "
                 "orgs.port('astryx-growbot'))")
        py = str(co / "venv" / "bin" / "python")

        def ask(env):
            return subprocess.run([py, "-c", probe, str(co)], env=env, cwd="/", capture_output=True, text=True,
                                  timeout=30)
        r = ask(one)
        check("one org: astryx-pulse.timer (pulse_witness the same), astryx-residents.service, port None",
              r.stdout.split() == ["astryx-pulse.timer", "astryx-pulse.timer", "astryx-residents.service", "None"],
              r.stdout + r.stderr[-200:])
        oa = fx.org["a"]
        r = ask(fx.env(ASTRYX_HOME=str(A)))
        check(f"HOME-A: astryx-pulse@{oa}.timer, pulse_witness follows it, growbot on A's {pa['astryx-growbot']}",
              r.stdout.split() == [f"astryx-pulse@{oa}.timer"] * 2 + [f"astryx-residents@{oa}.service",
                                                                      str(pa["astryx-growbot"])],
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
