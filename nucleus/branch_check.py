#!/usr/bin/env python3
"""branch_check (plan-4918): run a BRANCH's full check.sh against the live estate, prod-safe, as a DIFFERENTIAL
against main under one identical environment, and remove exactly what the run created.

    venv/bin/python -m nucleus.branch_check <branch-ref> [--main <ref>]
    rc 0: no gate regressed · 1: regressed (named) · 77: refused or couldn't run (reason named)

The order is the design's (#26043 + #26057), each step fail-closed:
  sweep       reap scopes whose process is gone (runscope; (pid, starttime))
  P0-b        refuse unless every database the run doesn't own is hardened (seed's one-time P0-a)
  repos       private repos of main and the branch (git archive); a credential in either TRACKED tree refuses
  estate      the derived estate copied into both (a credential-bearing file skipped, the private tier linked ro)
  E           one pg_dump of prod → a run-owned BASE → two fresh clones (identical start state per side)
  template    the extension template per side's schema.sql sha, KEEPING both (so the sides can't evict each other)
  env         a generated .env per side: the run role's DSN to its clone, allowlisted keys only
  R5 probes   inside the sandbox (the TOOL's own probe, never the branch's), each against an OUTSIDE control
  suites      check.sh per side, in the allowlist sandbox
  report      each side's own FAILED/UNVERIFIED summary quoted verbatim; the difference computed from those two
              check.sh-authored sets, never a verdict of this tool's own; the zero-prod-statements witness
  teardown    always, by ownership; a LEAK makes the run rc 1
Prevention grade (stated in the design): against accidents and env-following tests. An adversarial same-uid actor
is out of scope; it can reach prod without this tool.
AGE (a3 C1a): the run role's session preload makes AGE's C code reachable from the run role, and every cypher() call
parses branch-authored text inside it. An AGE privilege escalation would be an escape to superuser, and so to prod.
That is attack surface prod doesn't have (prod runs AGE as a superuser already), and it is out of scope at this grade.
"""
import argparse
import ast
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from nucleus import branch_check_prep as prep
from nucleus import branch_check_sandbox as sb
from nucleus import runscope as rs

LIVE = prep.LIVE
SUITE_TIMEOUT = int(os.environ.get("BRANCH_CHECK_SUITE_TIMEOUT", "3600"))
# check.sh's label for the sqlguard gate (check.sh:594; the orchestrator oracle pins it against check.sh itself).
# Its ledger is kept against LIVE, so under E it reads RED on both sides; it's judged DIFFERENTIALLY instead,
# by each side's red.json identities (plan-4918 D4, a3 C4).
SQLGUARD_GATE = "sqlguard: every SQL site is observed, or listed debt"


def sqlguard_red(trace: Path):
    """{identity: rendered line} from enforce's red.json in this side's trace dir, or None if enforce didn't write it."""
    try:
        return {r["id"]: r["line"] for r in json.loads((trace / "red.json").read_text())}
    except (OSError, ValueError, KeyError, TypeError):
        return None


# ── which dark gate could have run a site (a2 #37119): a RELATION, never co-occurrence ───────────────────────────
# 17 gates are dark on every run, so "some gate was dark" is always true; keyed on that, a site NO oracle runs (the
# founding class sqlguard exists for) would read UNVERIFIABLE forever. A site is excused only when a dark gate's
# ORACLE references the site's module, read statically from the branch's own check.sh and oracle files.
# A string names a module the oracle RUNS only as an argument of one of these loaders (a3 #38259, measured: 72 of
# the gate→module relations a bare string constant made were DATA, tuples of names, path dicts, a module read as
# text, even this oracle's own test literal). A closed set: a new loader shape reads REGRESSED until it's added.
LOADERS = frozenset({"import_module", "spec_from_file_location", "run_module", "run_path", "find_spec"})
_RUN_RX = re.compile(r'^run "([^"]+)"\s+"\$PY"\s+(?:-m\s+(\S+)|(\S+\.py))', re.M)


def gate_refs(repo: Path) -> dict:
    """{check.sh label: the modules its python oracle RUNS}: imports at any depth (`import a.b`, `from a import b`
    as a, a.b), and a string constant ONLY as a positional argument of a LOADERS call (`importlib.import_module(
    "bridges.common")`). A string anywhere else is data, never a reference. Unparseable or absent oracles are
    omitted, so their sites stay REGRESSED (fail-closed)."""
    out = {}
    try:
        text = (repo / "nucleus" / "check.sh").read_text()
    except OSError:
        return out
    for label, mod, path in _RUN_RX.findall(text):
        f = repo / (mod.replace(".", "/") + ".py" if mod else path)
        try:
            tree = ast.parse(f.read_text())
        except (OSError, SyntaxError, ValueError):
            continue
        out[label] = module_refs(tree)
    return out


def module_refs(tree) -> set:
    """The modules a parsed oracle RUNS (gate_refs' reading, shared): imports at any depth, and a string constant
    only as a positional argument of a LOADERS call."""
    refs = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            refs |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            refs |= {n.module} | {f"{n.module}.{a.name}" for a in n.names}
        elif isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) in LOADERS:
            refs |= {a.value for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
    return refs


def covering_gate(site_path: str, gates, refs: dict):
    """The first of `gates` whose oracle references `site_path` (a repo-relative .py) by its dotted module or its
    path. Never by a bare stem: "canvas" is an ordinary word in an econ oracle (measured), and a word match would
    excuse exactly the unreferenced site this exists to keep RED. None if no dark gate could have run it."""
    if not site_path.endswith(".py"):
        return None
    mod = site_path[:-3].replace("/", ".")
    for g in gates:
        r = refs.get(g, set())
        if mod in r or site_path in r:
            return g
    return None


def admin_dsn() -> str:
    dsn = os.environ.get("ASTRYX_DSN") or prep.read_env(LIVE / ".env").get("ASTRYX_DSN")
    if not dsn:
        raise prep.Refuse("no admin DSN (ASTRYX_DSN or the live .env)")
    return dsn


_HEAD = {"failed": re.compile(r"^FAILED \(\d+\):$"), "unverified": re.compile(r"^UNVERIFIED \(\d+\) — ")}


def summary(log: str) -> dict:
    """check.sh's OWN verdict sets, parsed from the block it prints LAST (check.sh:109-124): {failed, unverified, line}.
    Only that trailing block counts. A gate's own output can print a "FAILED (3): …" line and "  ✗ …" items (the
    econ provenance oracle does, first end-to-end run #33638), and reading those would let a gate inject or mask a
    name. So: the LAST `check: ` line, and walking UP from it, only its headers (their exact shape) and their items."""
    lines = re.sub(r"\x1b\[[0-9;]*m", "", log).splitlines()
    out = {"failed": [], "unverified": [], "line": ""}
    end = max((i for i, ln in enumerate(lines) if ln.startswith("check: ")), default=None)
    if end is None:
        return out
    out["line"] = lines[end]
    items = []
    for ln in reversed(lines[:end]):
        if not ln.strip():
            if out["failed"] or out["unverified"]:
                break                                      # verdict()'s leading `echo` (check.sh:104): the TOP edge
            continue                                       # its trailing `echo` (check.sh:115), below the block
        if ln.startswith("  ") and ln.strip()[:1] in ("✗", "○"):
            items.append(ln.strip()[1:].strip())
            continue
        kind = next((k for k, rx in _HEAD.items() if rx.match(ln)), None)
        if kind is None:
            break                                          # above the summary block: gate output, never read
        out[kind] = list(reversed(items)) + out[kind]
        items = []
    return out


def prod_statements(trace_dir: Path, prod_db: str) -> int:
    """The psycopg-path witness (a1 #24435): statements the run's sqlguard trace saw against the PROD database."""
    n = 0
    for f in glob.glob(str(trace_dir / "trace-*.jsonl")):
        for line in open(f):
            try:
                if json.loads(line).get("db") == prod_db:
                    n += 1
            except ValueError:
                pass
    return n


def run(branch: str, main_ref: str = "main") -> int:
    dsn = admin_dsn()
    prod_db = conninfo_to_dict(dsn).get("dbname", "astryx")
    for r in rs.sweep(dsn):
        print(f"  reaped stale scope {r['scope']}: {r}")
    sha = {side: subprocess.run(["git", "rev-parse", ref], cwd=LIVE, capture_output=True, text=True,
                                check=True).stdout.strip() for side, ref in (("main", main_ref), ("branch", branch))}
    scope = rs.RunScope(dsn).open()
    rc, leak = 77, None
    try:
        with psycopg.connect(dsn, autocommit=True) as adm:
            prep.require_hardened(adm, scope.role)                                  # P0-b
            try:
                node = sb.node_bin()                                                # D3: resolved OUTSIDE
            except sb.NodeUnresolved as e:
                raise prep.Refuse(f"no usable node for the suites: {e}")
            secrets_ = prep.secret_set(LIVE)
            repo, tmp = {}, {}
            for side in ("main", "branch"):
                repo[side] = prep.private_repo(LIVE, sha[side], scope.root / side / "repo", main_sha=sha["main"])
                hits = prep.tracked_secret_hits(repo[side], secrets_) + prep.history_secret_hits(repo[side], secrets_)
                if hits:
                    raise prep.Refuse(f"a credential is committed in {side} ({sha[side][:7]}): {hits} "
                                      f"(values not printed)")
                tmp[side] = scope.root / side / "tmp"
                tmp[side].mkdir(parents=True)
            est = {side: prep.copy_estate(LIVE, repo[side], secrets_) for side in repo}
            base, _, errs = prep.build_base(scope, dsn, prod_db)
            if errs:
                raise prep.Refuse(f"the prod restore into the base reported {errs} error(s)")
            shas = {side: prep.schema_sha(repo[side]) for side in repo}
            # evict stale templates only when no OTHER run is alive: it may be cloning from its own (seed #34141)
            alone = rs.live(scope.base) == [scope.run_id]
            tpl = {side: prep.ensure_ext_template(adm, shas[side], keep=set(shas.values()), evict=alone)
                   for side in repo}
            clone = {side: scope.create_db(f"{scope.role}_{side}", template=base) for side in repo}
            # the sandbox's ONLY route to postgres: a unix socket in each side's run tmp, bridged to the server
            sock = {side: tmp[side] / "pg" for side in repo}
            for side in repo:
                prep.write_env(repo[side], scope.dsn(clone[side], socket_dir=sock[side]), node=node)
                (repo[side] / "venv").symlink_to(LIVE / "venv")
            # R5, the boundary, probed from inside with outside controls (the branch side is the untrusted one)
            cfg = {"targets": sb.reach_targets(), "live_env": str(LIVE / ".env"), "live_repo": str(LIVE),
                   "own_dsn": scope.dsn(clone["branch"], socket_dir=sock["branch"]),
                   "run_conn": {"user": scope.role, "password": scope._password, "host": str(sock["branch"]),
                                "port": 5432},
                   "listeners": sb.host_listeners(), "socket_dirs": [str(sock["branch"])],
                   "foreign_dbs": [d for (d,) in adm.execute(
                       "SELECT d.datname FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba "
                       "WHERE d.datallowconn AND r.rolname <> %s", (scope.role,)) if prep.transient(d) is not True]}
            probe_src = Path(sb.__file__).resolve()                                 # the TOOL's copy, never the branch's
            ro = [LIVE / p for p in est["branch"]["linked_private"]]
            a = sb.argv(repo["branch"], tmp["branch"], ro_extra=ro, probe_src=probe_src, node=node)
            with sb.PgBridge(sock["branch"]):
                pr = subprocess.run(a + [str(LIVE / "venv/bin/python"), sb.PROBE_AT], input=json.dumps(cfg),
                                    env=sb.env(cfg["own_dsn"], node), capture_output=True, text=True, timeout=300)
            inside = json.loads(pr.stdout.strip().splitlines()[-1]) if pr.stdout.strip() else None
            if inside is None:
                raise prep.Refuse(f"the R5 probe didn't run inside the sandbox: {pr.stderr[-300:]}")
            out_cfg = {**cfg, "socket_dirs": [], "run_conn": {**cfg["run_conn"], "host": "127.0.0.1"},
                       "own_dsn": scope.dsn(clone["branch"])}                 # OUTSIDE: the same probes over TCP
            bad = sb.verdict(inside, sb.probe(out_cfg))
            if bad:
                raise prep.Refuse("R5: " + "; ".join(bad))
        # the suites, one per side, identical sandboxes
        def suite(side, attempt):
            trace = tmp[side] / f"sqlguard{attempt}"
            trace.mkdir()
            env = {**sb.env(scope.dsn(clone[side], socket_dir=sock[side]), node), "ASTRYX_FIXTURE_TEMPLATE": tpl[side],
                   "ASTRYX_SQLGUARD_DIR": str(trace)}
            a = sb.argv(repo[side], tmp[side], ro_extra=[LIVE / p for p in est[side]["linked_private"]], node=node)
            with sb.PgBridge(sock[side]):
                p = subprocess.run(a + ["bash", "nucleus/check.sh"], env=env, capture_output=True, text=True,
                                   timeout=SUITE_TIMEOUT)
            if os.environ.get("BRANCH_CHECK_KEEP_LOGS"):
                (scope.base / f"{scope.run_id}-{side}{attempt}.log").write_text(p.stdout + p.stderr)
            out = summary(p.stdout)
            out["sqlguard_red"] = sqlguard_red(trace)
            return out, prod_statements(trace, prod_db)
        sums, witness = {}, {}
        for side in ("main", "branch"):
            sums[side], witness[side] = suite(side, 1)
        # FLAKY != REGRESSED (a1 F5): a regression must REPRODUCE on a second branch run before it's named one
        first = set(sums["branch"]["failed"]) - set(sums["main"]["failed"])
        if first:
            again, w2 = suite("branch", 2)
            witness["branch"] += w2
            sums["branch"]["flaky"] = sorted(first - set(again["failed"]))
            sums["branch"]["failed"] = sorted(set(sums["branch"]["failed"]) - set(sums["branch"]["flaky"]))
            r1, r2 = sums["branch"]["sqlguard_red"], again["sqlguard_red"]
            # a branch-only sqlguard finding must REPRODUCE too (FLAKY != REGRESSED)
            sums["branch"]["sqlguard_red"] = None if r1 is None or r2 is None else {i: l for i, l in r1.items() if i in r2}
        rc = report(sha, sums, witness, est, refs=gate_refs(repo["branch"]), touched=touched_files(sha, repo["branch"]))
    except prep.Refuse as e:
        print(f"branch_check: REFUSED (rc 77): {e}")
        rc = 77
    finally:
        leak = scope.close()
        if leak["leaked"] or leak["role_left"] or leak["root_left"] or leak["errors"]:
            print(f"branch_check: LEAK after teardown: {leak}")
            rc = 1
    return rc


def touched_files(sha: dict, repo: Path = None) -> set:
    """The branch's scope: the files it changes (main..branch, from the live repo), plus every module a CHANGED .py
    file imports (module_refs), so a red left in a module the branch's own new oracle drives is in scope too.
    Empty if git can't say: never a guess."""
    p = subprocess.run(["git", "diff", "--name-only", sha["main"], sha["branch"]], cwd=LIVE, capture_output=True, text=True)
    if p.returncode != 0:
        return set()
    files = set(p.stdout.split())
    out = set(files)
    for f in files:
        if not f.endswith(".py") or repo is None:
            continue
        try:
            tree = ast.parse((repo / f).read_text())
        except (OSError, SyntaxError, ValueError):
            continue
        out |= {m.replace(".", "/") + ".py" for m in module_refs(tree)}
    return out


def sqlguard_module(line: str):
    """'R-NEW nucleus/x.py::f :: …' → 'nucleus/x.py' (None if the line names no module)."""
    mt = re.match(r"R-[A-Z]+ (\S+?)::", line)
    return mt.group(1) if mt else None


def report(sha: dict, sums: dict, witness: dict, est: dict, refs: dict = None, touched: set = None) -> int:
    m, b = sums["main"], sums["branch"]
    print(f"branch_check {sha['branch'][:7]} vs main {sha['main'][:7]}")
    for side in ("main", "branch"):
        print(f"  {side:6s} {sums[side]['line']}")                  # check.sh's own verdict line, verbatim
    regressed = sorted(set(b["failed"]) - set(m["failed"]))
    mr, br = m.get("sqlguard_red"), b.get("sqlguard_red")
    judged = mr is not None and br is not None
    both = sorted(set(m["unverified"]) & set(b["unverified"]))
    dark_gates = sorted(set(both) | (set(b["unverified"]) - set(m["unverified"])))
    dark = []
    if judged:                                      # D4: the gate's findings, by identity, not the gate's rc
        sg_new = sorted(l for i, l in br.items() if i not in mr)
        # A NEW site no oracle EXECUTED here is excused ONLY if a gate that verified nothing (on both sides, or newly
        # on the branch) has an oracle referencing its module: that oracle may be its only runner, sandbox-dark (a4
        # #36860: prep's names-mode `unhardened` read was RESPONSIVE live; a2 #37112: test_people_gate needs
        # CREATEROLE). Named with that gate, never REGRESSED. A site no dark oracle references, or one EXECUTED
        # but unlisted (its oracle ran), stays REGRESSED (a2 #37119).
        for l in sg_new:
            mt = re.match(r"R-NEW (\S+?)::", l)
            g = covering_gate(mt.group(1), dark_gates, refs or {}) if mt and "UNEXECUTED" in l else None
            if g:
                dark.append((l, g))
        excused = {l for l, _ in dark}
        regressed += [f"{SQLGUARD_GATE} → {l}" for l in sg_new if l not in excused]
        print(f"  sqlguard judged DIFFERENTIALLY: {len(br)} RED on the branch, {len(mr)} on main, "
              f"{len(sg_new)} only on the branch")
        # the per-site differential a reviewer otherwise rebuilds by hand from KEEP_LOGS (a2 night-review 10-11):
        # which of main's reds the branch clears, and which reds it leaves standing in the very files it touches
        cleared = sorted(l for i, l in mr.items() if i not in br)
        standing = sorted(l for i, l in br.items() if i in mr and sqlguard_module(l) in (touched or set()))
        for label, xs in (("sqlguard sites the branch CLEARS", cleared),
                          ("sqlguard sites still RED in the branch's scope (files it changes, modules they import)", standing)):
            if xs:
                print(f"  {label}: {len(xs)}")
                for x in xs:
                    print(f"    {x}")
    fixed = sorted(set(m["failed"]) - set(b["failed"]))
    newly_unverified = sorted(set(b["unverified"]) - set(m["unverified"]))
    for label, xs in (("REGRESSED (fails on the branch, not on main, and again on a rerun)", regressed),
                      ("FLAKY (failed once on the branch, passed on its rerun: not counted, but named)",
                       b.get("flaky", [])),
                      ("fixed by the branch", fixed),
                      ("newly UNVERIFIED on the branch", newly_unverified)):
        if xs:
            print(f"  {label}:")
            for x in xs:
                print(f"    {x}")
    dead = sorted((set(m["failed"]) & set(b["failed"])) - ({SQLGUARD_GATE} if judged else set()))
    print(f"  FAILED ON BOTH SIDES (verified nothing about the branch; the environment, or main itself): {len(dead)}")
    for x in dead:
        print(f"    ✗ {x}")
    if dark:
        print(f"  UNVERIFIABLE HERE (a branch-only R-NEW no oracle EXECUTED under branch_check; the named gate's oracle "
              f"references its module and verified nothing this run): {len(dark)}")
        print("    decide it LIVE: run that oracle under the shim (PYTHONPATH=nucleus/sqlguard/shim, ASTRYX_SQLGUARD_DIR, "
              "ASTRYX_SQLGUARD_GATE) and `python -m nucleus.sqlguard.judge <dir>`; seed's merge-time check.sh enforces "
              "it either way")
        for x, g in dark:
            print(f"    ? {x}\n      ← dark gate: {g}")
    print(f"  VERIFIED NOTHING under branch_check (both sides; coverage this run did not provide): {len(both)}")
    for x in both:
        print(f"    ○ {x}")
    skipped = est["branch"]["skipped_credential"]
    if skipped:
        print(f"  VERIFIED NOTHING: {len(skipped)} estate file(s) carry a credential and weren't copied: {skipped}")
    for side, n in witness.items():
        if n:
            print(f"  WITNESS: {n} statement(s) reached the PROD database from the {side} run")
    if any(witness.values()):
        return 1
    return 1 if regressed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("branch")
    ap.add_argument("--main", default="main")
    a = ap.parse_args()
    sys.exit(run(a.branch, a.main))
