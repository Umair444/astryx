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
"""
import argparse
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
            continue
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
            secrets_ = prep.secret_set(LIVE)
            repo, tmp = {}, {}
            for side in ("main", "branch"):
                repo[side] = prep.private_repo(LIVE, sha[side], scope.root / side / "repo")
                hits = prep.tracked_secret_hits(repo[side], secrets_)
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
            tpl = {side: prep.ensure_ext_template(adm, shas[side], keep=set(shas.values())) for side in repo}
            clone = {side: scope.create_db(f"{scope.role}_{side}", template=base) for side in repo}
            # the sandbox's ONLY route to postgres: a unix socket in each side's run tmp, bridged to the server
            sock = {side: tmp[side] / "pg" for side in repo}
            for side in repo:
                prep.write_env(repo[side], scope.dsn(clone[side], socket_dir=sock[side]))
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
            a = sb.argv(repo["branch"], tmp["branch"], ro_extra=ro, probe_src=probe_src)
            with sb.PgBridge(sock["branch"]):
                pr = subprocess.run(a + [str(LIVE / "venv/bin/python"), sb.PROBE_AT], input=json.dumps(cfg),
                                    env=sb.env(cfg["own_dsn"]), capture_output=True, text=True, timeout=300)
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
            env = {**sb.env(scope.dsn(clone[side], socket_dir=sock[side])), "ASTRYX_FIXTURE_TEMPLATE": tpl[side],
                   "ASTRYX_SQLGUARD_DIR": str(trace)}
            a = sb.argv(repo[side], tmp[side], ro_extra=[LIVE / p for p in est[side]["linked_private"]])
            with sb.PgBridge(sock[side]):
                p = subprocess.run(a + ["bash", "nucleus/check.sh"], env=env, capture_output=True, text=True,
                                   timeout=SUITE_TIMEOUT)
            if os.environ.get("BRANCH_CHECK_KEEP_LOGS"):
                (scope.base / f"{scope.run_id}-{side}{attempt}.log").write_text(p.stdout + p.stderr)
            return summary(p.stdout), prod_statements(trace, prod_db)
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
        rc = report(sha, sums, witness, est)
    except prep.Refuse as e:
        print(f"branch_check: REFUSED (rc 77): {e}")
        rc = 77
    finally:
        leak = scope.close()
        if leak["leaked"] or leak["role_left"] or leak["root_left"] or leak["errors"]:
            print(f"branch_check: LEAK after teardown: {leak}")
            rc = 1
    return rc


def report(sha: dict, sums: dict, witness: dict, est: dict) -> int:
    m, b = sums["main"], sums["branch"]
    print(f"branch_check {sha['branch'][:7]} vs main {sha['main'][:7]}")
    for side in ("main", "branch"):
        print(f"  {side:6s} {sums[side]['line']}")                  # check.sh's own verdict line, verbatim
    regressed = sorted(set(b["failed"]) - set(m["failed"]))
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
    dead = sorted(set(m["failed"]) & set(b["failed"]))
    print(f"  FAILED ON BOTH SIDES (verified nothing about the branch; the environment, or main itself): {len(dead)}")
    for x in dead:
        print(f"    ✗ {x}")
    both = sorted(set(m["unverified"]) & set(b["unverified"]))
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
