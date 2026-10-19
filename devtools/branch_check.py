#!/usr/bin/env python3
"""branch_check (plan-4918): run a BRANCH's full check.sh against the live estate, prod-safe, as a DIFFERENTIAL
against main under one identical environment, and remove exactly what the run created.

    venv/bin/python -m devtools.branch_check <branch-ref> [--main <ref>]
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
import warnings
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from devtools import branch_check_prep as prep
from devtools import branch_check_sandbox as sb
from astryx.pg import runscope as rs
from astryx.paths import common_dir  # noqa: E402

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
        text = (repo / "devtools" / "check.sh").read_text()
    except OSError:
        return out
    for label, mod, path in _RUN_RX.findall(text):
        f = repo / (_modfile(mod) if mod else path)
        try:
            tree = ast.parse(f.read_text())
        except (OSError, SyntaxError, ValueError):
            continue
        out[label] = module_refs(tree)
    return out


def _modfile(m: str, package: bool = False) -> str:
    """dotted -> repo-relative file: astryx.* lives under src/, a moved nucleus.* where it went (goal 10224 S4)."""
    try:
        from astryx.paths import module_relpath
        return module_relpath(m, package)
    except ImportError:
        return m.replace(".", "/") + ("/__init__.py" if package else ".py")


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
    mod = mod[len("src."):] if mod.startswith("src.astryx.") else mod
    for g in gates:
        r = refs.get(g, set())
        if mod in r or site_path in r:
            return g
    return None


def admin_dsn() -> str:
    from astryx import config        # the ONE resolver (plan-11324 S3a): the environment, else the live .env
    try:
        return config.dsn(LIVE / ".env")
    except LookupError:
        raise prep.Refuse("no admin DSN (ASTRYX_DSN or the live .env)") from None


_HEAD = {"failed": re.compile(r"^FAILED \(\d+\):$"), "unverified": re.compile(r"^UNVERIFIED \(\d+\) — ")}


def run_suite(argv: list, env: dict, timeout: int = None) -> tuple:
    """(stdout, stderr, rc) of one side's check.sh. A suite past SUITE_TIMEOUT is rc "timeout" with its PARTIAL output,
    never a traceback: the caller still reads that side's sqlguard trace, so its prod writes are counted (a4 #53077)."""
    try:
        p = subprocess.run(argv, env=env, capture_output=True, text=True,
                           timeout=SUITE_TIMEOUT if timeout is None else timeout)
        return p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        dec = lambda b: b.decode(errors="replace") if isinstance(b, bytes) else (b or "")   # bytes even with text=True
        return dec(e.stdout), dec(e.stderr), "timeout"


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


def prod_statements(trace_dir: Path, prod_db: str):
    """The psycopg-path witness (a1 #24435): statements the run's sqlguard trace saw against the PROD database. None
    when the trace can't vouch for the run: no dir, or no run_id (check.sh writes it into the dir it's handed before
    any gate runs). That is UNWITNESSED, never "nothing seen" (a3 #61231, seed #61236): a deleter, a check.sh that
    never reached its sqlguard block, or a path that drifted would otherwise read as a clean zero."""
    if not trace_dir.is_dir() or not (trace_dir / "run_id").is_file():
        return None
    n = 0
    for f in glob.glob(str(trace_dir / "trace-*.jsonl")):
        for line in open(f):
            try:
                if json.loads(line).get("db") == prod_db:
                    n += 1
            except ValueError:
                pass
    return n


def combine_witness(w1, w2):
    """The branch side's witness over its first run and its rerun. A KNOWN prod write dominates: an unwitnessed rerun
    (None) must never erase statements the first run saw (a4 #61241: 3 + None read None, so a known prod write fell
    to rc 77). Otherwise any unwitnessed part makes the whole None, and two witnessed zeros are 0."""
    known = [n for n in (w1, w2) if n is not None]
    return sum(known) if any(known) or len(known) == 2 else None


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
                   "ASTRYX_SQLGUARD_DIR": str(trace),
                   # a side tree is `git archive` output (no .git): it DECLARES its source, so a linked worktree inside it
                   # reads as another checkout of this repo, not subject code (astryx.paths Checkouts, a4 #53469)
                   "ASTRYX_REPO_COMMON": str(common_dir(LIVE) or "")}
            a = sb.argv(repo[side], tmp[side], ro_extra=[LIVE / p for p in est[side]["linked_private"]], node=node)
            with sb.PgBridge(sock[side]):
                stdout, stderr, rc = run_suite(a + ["bash", "devtools/check.sh"], env)
            if os.environ.get("BRANCH_CHECK_KEEP_LOGS"):
                (scope.base / f"{scope.run_id}-{side}{attempt}.log").write_text(stdout + stderr)
            out = summary(stdout)
            out["rc"] = rc
            out["sqlguard_red"] = sqlguard_red(trace)
            return out, prod_statements(trace, prod_db)
        sums, witness = {}, {}
        for side in ("main", "branch"):
            sums[side], witness[side] = suite(side, 1)
        # FLAKY != REGRESSED (a1 F5): a regression must REPRODUCE on a second branch run before it's named one
        first = set(sums["branch"]["failed"]) - set(sums["main"]["failed"])
        if first:
            again, w2 = suite("branch", 2)
            witness["branch"] = combine_witness(witness["branch"], w2)
            sums["branch"]["flaky"] = sorted(first - set(again["failed"]))
            sums["branch"]["failed"] = sorted(set(sums["branch"]["failed"]) - set(sums["branch"]["flaky"]))
            r1, r2 = sums["branch"]["sqlguard_red"], again["sqlguard_red"]
            # a branch-only sqlguard finding must REPRODUCE too (FLAKY != REGRESSED)
            sums["branch"]["sqlguard_red"] = None if r1 is None or r2 is None else {i: l for i, l in r1.items() if i in r2}
        rc = report(sha, sums, witness, est, refs=gate_refs(repo["branch"]), touched=touched_files(sha, repo["branch"]),
                    oracles=gate_files(repo["branch"]), changed=changed_files(sha), repo=repo["branch"],
                    members=membership_changes(sha))
    except prep.Refuse as e:
        print(f"branch_check: REFUSED (rc 77): {e}")
        rc = 77
    finally:
        leak = scope.close()
        if leak["leaked"] or leak["role_left"] or leak["root_left"] or leak["errors"]:
            print(f"branch_check: LEAK after teardown: {leak}")
            rc = 1
    return rc


def changed_files(sha: dict) -> set:
    """The files the branch changes: main...branch (THREE dots, from the merge-base), from the live repo. Empty if git
    can't say: never a guess."""
    p = subprocess.run(["git", "diff", "--name-only", f"{sha['main']}...{sha['branch']}"], cwd=LIVE, capture_output=True,
                       text=True)
    return set(p.stdout.split()) if p.returncode == 0 else set()


# ── a DARK gate whose oracle references a file the branch changes (a2 night-review 10-12) ───────────────────────────
# 10-11: seed/trigger-name-guard PASSed on a run where "channel ear survives a db blip" and "lost wakes recovered at
# spawn" verified nothing; both stage channel/server.mjs, the file the branch changed, and both broke on main. The
# VERIFIED NOTHING list read as environment. This is a DETECTOR (it tells the reviewer to run a gate directly), so
# its relation is deliberately WIDER than covering_gate's (which EXCUSES, and must be strict): a spurious line costs a
# glance, a missed one costs a regression. Any oracle language (python, node, bash); the oracle file itself changed,
# a touched python module it imports, or the touched file's path or file name (extension included, never a bare stem)
# in its text. devtools/check.sh is left out: nearly every branch touches it to add its own gate.
SCOPE_NOISE = frozenset({"devtools/check.sh"})
# a label may carry \" (the tmux gate's does). A run line may be INDENTED (a gate inside an `if`, check.sh's media
# decode) and may carry run()'s one flag, `--cap=<s>` (check.sh's run(): test_relay's): either form missed was a gate
# no dark list and no census saw (a4, 10-19: the census never reached test_relay.py's probe-then-release)
_GATE_RX = re.compile(r'^[ \t]*run (?:--cap=\S+\s+)?"((?:[^"\\]|\\.)+)"\s+(.*)$', re.M)
_ORACLE_SUFFIXES = (".py", ".sh", ".mjs", ".js", ".ts")


def gate_files(repo: Path) -> dict:
    """{check.sh label: the repo-relative oracle files its run line names} (`-m pkg.mod` → pkg/mod.py; any argument that
    is a file in the repo with an oracle suffix). Read from the branch's own check.sh."""
    try:
        text = (repo / "devtools" / "check.sh").read_text()
    except OSError:
        return {}
    out = {}
    for label, rest in _GATE_RX.findall(text):
        label = label.replace('\\"', '"')                  # bash prints the label unescaped; match what it prints
        toks = rest.replace('"', " ").split()
        files = {_modfile(toks[i + 1]) for i, t in enumerate(toks[:-1]) if t == "-m"}
        files |= {t for t in toks if t.endswith(_ORACLE_SUFFIXES)}
        out[label] = {f for f in files if (repo / f).is_file()}
    return out


_NAMED_RX = re.compile(r"(?<![\w-])([\w.-]+\.(?:py|mjs|js|ts|sh))(?![\w-])")     # a file name WITH its extension
_JS_IMPORT_RX = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)['"](\.{1,2}/[^'"]+)['"]""")
_WALK_SKIP = frozenset({".git", "node_modules", "venv", "__pycache__", "dist"})


def _file_index(repo: Path) -> dict:
    """{file name: {repo-relative paths}} over the repo's oracle-suffixed files (node_modules, venv, dist skipped)."""
    idx = {}
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in _WALK_SKIP]
        for n in files:
            if n.endswith(_ORACLE_SUFFIXES):
                idx.setdefault(n, set()).add(os.path.relpath(os.path.join(root, n), repo))
    return idx


def _imports(repo: Path, f: str, text: str) -> set:
    """The repo files `f` imports statically: python via module_refs, js/mjs/ts relative specifiers (static `from`,
    bare `import '…'`, dynamic `import('…')`) resolved against f's directory."""
    out = set()
    if f.endswith(".py"):
        try:
            with warnings.catch_warnings():             # a repo file's own invalid escapes are its business, not ours
                warnings.simplefilter("ignore")
                mods = module_refs(ast.parse(text))
        except (SyntaxError, ValueError):
            return out
        for m in mods:
            for c in (_modfile(m), _modfile(m, package=True)):
                if (repo / c).is_file():
                    out.add(c)
    elif f.endswith((".mjs", ".js", ".ts")):
        for spec in _JS_IMPORT_RX.findall(text):
            c = os.path.normpath(os.path.join(os.path.dirname(f), spec))
            if (repo / c).is_file():
                out.add(c)
    return out


def membership_changes(sha: dict) -> set:
    """The paths the branch ADDS, DELETES, RENAMES or COPIES (both sides of a rename), main...branch from the live
    repo: the changes a CENSUS gate (one that judges a set's membership) is about. Empty if git can't say."""
    p = subprocess.run(["git", "diff", "--name-status", "-M", f"{sha['main']}...{sha['branch']}"], cwd=LIVE,
                       capture_output=True, text=True)
    if p.returncode != 0:
        return set()
    out = set()
    for line in p.stdout.splitlines():
        parts = line.split("\t")
        if parts and parts[0][:1] in "ADRC":
            out |= set(parts[1:])
    return out


# A CENSUS oracle judges membership by ENUMERATING, not by naming (a2 night-review 10-14: test_reachability reads
# `git ls-files` and was dark when a4's review_range.sh was ADDED invoked-by-nothing; no name or import reached it).
# Repo-wide: it lists every tracked file. Directory: it globs or lists one constant dir under the repo root. A
# MODIFIED file doesn't change any census's set, so only membership changes reach these (no noise on edit-only
# branches).
_REPO_WIDE_RX = re.compile(r"""["']ls-files["']|\bgit ls-files\b|\b(?:REPO|ROOT)\s*\)?\s*\.rglob\(|os\.walk\(\s*(?:REPO|ROOT)\b""")
_DIR_CENSUS_RX = re.compile(r"""\b(?:REPO|ROOT)\s*/\s*["']([\w./-]+)["']\s*\)?\s*\.(?:r?glob|iterdir)\(""")


def dark_scope(dark_gates, oracles: dict, changed: set, repo: Path, members: set = None) -> list:
    """[(gate, changed file, via)] for each dark gate whose oracle REACHES a file the branch changes: the oracle file
    itself, a file it names (path or file name with extension; never a bare stem), or anything those import,
    TRANSITIVELY (a4 #49641: since #46291 the ear/wake/doorbell oracles name only server.mjs, which imports its
    sibling modules; a branch touching only a sibling must still put them in scope). `via` is the file the oracle
    named or imported first on the way (None when it's the changed file itself)."""
    changed = {f for f in changed if f not in SCOPE_NOISE and not f.endswith("__init__.py")}
    if not changed:
        return []
    idx = _file_index(repo)
    texts = {}

    def read(f):
        if f not in texts:
            try:
                texts[f] = (repo / f).read_text(errors="replace")
            except OSError:
                texts[f] = ""
        return texts[f]

    out = []
    for g in dark_gates:
        seeds = {}                                  # reached file → the seed it came through
        for o in sorted(oracles.get(g, ())):
            seeds.setdefault(o, None)
            t = read(o)
            for name in _NAMED_RX.findall(t):
                for q in idx.get(name, ()):
                    seeds.setdefault(q, q)
            for q in _imports(repo, o, t):
                seeds.setdefault(q, q)
        reached, todo = dict(seeds), list(seeds)
        while todo:
            f = todo.pop()
            for q in _imports(repo, f, read(f)):
                if q not in reached:
                    reached[q] = reached[f] or q
                    todo.append(q)
        hit = next((f for f in sorted(changed) if f in reached), None)
        if hit:
            via = reached[hit]
            out.append((g, hit, None if via == hit else via))
            continue
        census = _census_hit(g, oracles, read, members or set())
        if census:
            out.append((g, *census))
    return out


def _census_hit(g, oracles: dict, read, members: set):
    """(member, why) when gate g's oracle is a CENSUS whose domain holds a path the branch adds, deletes or renames."""
    members = {m for m in members if m not in SCOPE_NOISE}
    if not members:
        return None
    for o in sorted(oracles.get(g, ())):
        t = read(o)
        if _REPO_WIDE_RX.search(t):
            return sorted(members)[0], "a REPO-WIDE census, and the branch adds/deletes/renames files"
        for d in sorted(set(_DIR_CENSUS_RX.findall(t))):
            d = d.strip("/")
            m = next((m for m in sorted(members) if m.startswith(d + "/")), None)
            if m:
                return m, f"a census of {d}/, and the branch adds/deletes/renames a file there"
    return None


def touched_files(sha: dict, repo: Path = None) -> set:
    """The branch's scope: the files it changes (main...branch, from the live repo), plus every module a CHANGED .py
    file imports (module_refs), so a red left in a module the branch's own new oracle drives is in scope too.
    THREE dots: the diff from the merge-base, so once main moves past the fork, main's own changes never read as the
    branch's (a4 #45033: two-dot gave 6 files on 5f230fc, 3 of them seed's). Empty if git can't say: never a guess."""
    files = changed_files(sha)
    out = set(files)
    for f in files:
        if not f.endswith(".py") or repo is None:
            continue
        try:
            tree = ast.parse((repo / f).read_text())
        except (OSError, SyntaxError, ValueError):
            continue
        out |= {_modfile(m) for m in module_refs(tree)}
    return out


def sqlguard_module(line: str):
    """'R-NEW nucleus/x.py::f :: …' → 'nucleus/x.py' (None if the line names no module). An extractor red names its
    FILE with no '::' ('R-EXTRACT tests/t.py: listed…', 'R-EXTRACT tests/t.py builds…', enforce.py): a4 #45033."""
    mt = re.match(r"R-[A-Z]+ (\S+?)::", line) or re.match(r"R-EXTRACT (\S+?):?(?:\s|$)", line)
    return mt.group(1) if mt else None


def report(sha: dict, sums: dict, witness: dict, est: dict, refs: dict = None, touched: set = None,
           oracles: dict = None, changed: set = None, repo: Path = None, members: set = None) -> int:
    m, b = sums["main"], sums["branch"]
    print(f"branch_check {sha['branch'][:7]} vs main {sha['main'][:7]}")
    for side in ("main", "branch"):
        print(f"  {side:6s} {sums[side]['line']}")                  # check.sh's own verdict line, verbatim
    # A side whose suite never printed check.sh's verdict (killed, timed out, crashed before summary()) has EMPTY sets,
    # and an empty set is not "nothing failed": an empty BRANCH side reads as no regression (rc 0, main's failures
    # "fixed by the branch"), an empty MAIN side as every branch failure regressed. Neither compares anything (steward
    # 10-15: 26ededb's main side came back with no line, and the report ran as a differential anyway).
    dead = [s for s in ("main", "branch") if not sums[s].get("line")]
    if dead:
        for s in dead:
            print(f"  NO VERDICT from the {s} suite (check.sh rc {sums[s].get('rc', '?')}): it never printed its "
                  f"summary, so its sets are empty, not clean. No differential was judged; rerun with "
                  f"BRANCH_CHECK_KEEP_LOGS=1 to keep <run>-<side>N.log.")
        # the WITNESS is read from the sqlguard trace, not the verdict line: a suite that wrote to prod and then died
        # is still RED (a4 #53077), and NO VERDICT must never hide it
        _unwitnessed(witness)
        return 1 if _estate_and_witness(est, witness) else 77
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
        print("    decide it LIVE: run that oracle under the shim (PYTHONPATH=src/astryx/security/sqlguard/shim, ASTRYX_SQLGUARD_DIR, "
              "ASTRYX_SQLGUARD_GATE) and `python -m astryx.security.sqlguard.judge <dir>`; seed's merge-time check.sh enforces "
              "it either way")
        for x, g in dark:
            print(f"    ? {x}\n      ← dark gate: {g}")
    print(f"  VERIFIED NOTHING under branch_check (both sides; coverage this run did not provide): {len(both)}")
    for x in both:
        print(f"    ○ {x}")
    if oracles and changed and repo is not None:
        ds = dark_scope(dark_gates, oracles, changed, repo, members=members)
        if ds:
            print(f"  VERIFIED NOTHING and IN SCOPE (its oracle references a file the branch changes): run it DIRECTLY "
                  f"in a worktree before a PASS: {len(ds)}")
            for g, f, via in ds:
                print(f"    ○ {g}\n      ← {f}" + (f" ({via})" if via and " " in via else f" (via {via})" if via else ""))
    unwitnessed = _unwitnessed(witness)
    if _estate_and_witness(est, witness):
        return 1
    if regressed:
        return 1
    return 77 if unwitnessed else 0                  # a clean differential over an unwitnessed side is not a PASS


def _unwitnessed(witness: dict) -> bool:
    """A side whose prod witness is None (no trace dir, or no run_id in it) proves nothing about PROD. Named, and
    never read as zero. True if any side is unwitnessed."""
    gone = [side for side, n in witness.items() if n is None]
    for side in gone:
        print(f"  UNWITNESSED: the {side} run's sqlguard trace dir is missing or has no run_id, so whether it reached "
              f"the PROD database is UNKNOWN (never 'nothing seen'). Not a PASS: rc 77 unless something is RED.")
    return bool(gone)


def _estate_and_witness(est: dict, witness: dict) -> bool:
    """The lines that hold with or without a verdict: estate files not copied, and statements that reached PROD. True
    if any did (the run is RED)."""
    skipped = est["branch"]["skipped_credential"]
    if skipped:
        print(f"  VERIFIED NOTHING: {len(skipped)} estate file(s) carry a credential and weren't copied: {skipped}")
    for side, n in witness.items():
        if n:
            print(f"  WITNESS: {n} statement(s) reached the PROD database from the {side} run")
    return any(witness.values())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("branch")
    ap.add_argument("--main", default="main")
    a = ap.parse_args()
    sys.exit(run(a.branch, a.main))
