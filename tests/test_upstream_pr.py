#!/usr/bin/env python3
"""test_upstream_pr — medic's upstream PR tool (goal 10224 S6). Hermetic: a throwaway git repo (the real .gitignore and
devtools/privacy_gate.sh copied in), a FAKE `gh` first on PATH that logs every call and answers from a JSON file, and
`url.<local>.pushInsteadOf https://github.com/` in the fixture so every push lands in a local bare repo. Real GitHub is
never called.

  U1 a diff touching instance data (agents/<real>, homes/, triggers/, local.md, .env, tier/) is refused, exit 2;
     a shipped *.example charter is framework and passes
  U2 a personal-tier value in the branch's tree, or in the PR body, is refused by the privacy gate, exit 2
  U3 an open upstream PR with the same title, or the same diagnosis, gets a COMMENT, never a second PR
  U4 the open-PR cap: at the cap nothing is opened, exit 3
  U5 no gh on PATH, or gh logged out → it says `gh auth login`, exit 77, nothing sent
  U6 the fork path: fork asked with --remote=false, the branch pushed to the fork, the PR opened on upstream with four
     sections, version and platform, the home dir scrubbed
  U7 origin IS upstream with write access → no fork, a normal PR from origin; a plain clone (no write) forks
  U8 --is-upstream needs origin == upstream AND ASTRYX_UPSTREAM_ROLE=upstream
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "src" / "astryx" / "core" / "upstream_pr.py"
sys.path.insert(0, str(REPO))
from astryx.core import upstream_pr as U  # noqa: E402

fails = 0
UP = "acme-up/astryx"                    # a fictional upstream: nothing here names the real one
LOGIN = "outsider-medic"
ROOT = Path(tempfile.mkdtemp(prefix="test-upstream-pr-"))
ENV0 = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "ASTRYX_", "GH_", "GITHUB_"))}
# host-independent: the ASTRYX_* scrub drops check.sh's registry pin, so name an absent registry (a cog host's
# /etc/astryx/cog.json would make the tool's HOME resolution refuse this throwaway repo)
ENV0["ASTRYX_COG_REGISTRY"] = str(ROOT / "no-registry" / "cog.json")


def arm(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({str(detail)[:600]})" if detail and not ok else ""))
    if not ok:
        fails += 1


FAKE_GH = r'''#!{py}
import json, os, sys
cfg = json.load(open(os.environ["FAKE_GH_CFG"]))
a = sys.argv[1:]
rec = {{"argv": a}}
if "--body-file" in a:
    rec["body"] = open(a[a.index("--body-file") + 1]).read()
open(os.environ["FAKE_GH_LOG"], "a").write(json.dumps(rec) + "\n")
def out(s, rc=0, err=""):
    sys.stdout.write(s); sys.stderr.write(err); sys.exit(rc)
if a[:2] == ["auth", "status"]:
    out("", cfg.get("auth_rc", 0), "You are not logged into any GitHub hosts." if cfg.get("auth_rc") else "")
if a[:2] == ["api", "user"]:
    out("" if cfg.get("user_rc") else cfg["login"] + "\n", cfg.get("user_rc", 0), "HTTP 401" if cfg.get("user_rc") else "")
if a[:2] == ["pr", "list"]:
    out(json.dumps(cfg.get("prs", [])), cfg.get("list_rc", 0), cfg.get("list_err", ""))
if a[:2] == ["pr", "comment"]:
    out("https://github.com/x/y/pull/%s#comment\n" % a[2])
if a[:2] == ["repo", "view"]:
    out(json.dumps({{"viewerPermission": cfg.get("perm", "READ")}}))
if a[:2] == ["repo", "fork"]:
    out("", 0, "! %s already exists\n" % cfg["login"] if cfg.get("fork_exists") else "")
if a[:2] == ["pr", "create"]:
    out("https://github.com/%s/pull/101\n" % a[a.index("--repo") + 1])
out("", 1, "fake gh: unhandled " + " ".join(a))
'''


def ghbin() -> Path:
    d = ROOT / "ghbin"
    if not d.exists():
        d.mkdir()
        (d / "gh").write_text(FAKE_GH.format(py=sys.executable))
        (d / "gh").chmod(0o755)
    return d


def nogh_bin() -> Path:
    """Every executable on PATH except gh, as symlinks: the gate's tools stay, gh is gone."""
    d = ROOT / "nogh"
    if not d.exists():
        d.mkdir()
        for p in ENV0.get("PATH", "").split(os.pathsep):
            if not os.path.isdir(p):
                continue
            for e in os.listdir(p):
                if e != "gh" and not (d / e).exists() and os.access(os.path.join(p, e), os.X_OK):
                    (d / e).symlink_to(os.path.join(p, e))
    return d


def sh(*args, cwd):
    r = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, env=ENV0)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


N = [0]


def fixture(origin=f"https://github.com/{LOGIN}/astryx.git"):
    """A repo with framework code on main; push URLs to github.com land in ROOT/host-N/ (bare repos)."""
    N[0] += 1
    r, host = ROOT / f"repo-{N[0]}", ROOT / f"host-{N[0]}"
    (r / "nucleus").mkdir(parents=True)
    for _d in ("devtools", "scripts", "src/astryx/contrib", "src/astryx/core", "src/astryx/data", "src/astryx/econ", "src/astryx/federation", "src/astryx/hands", "src/astryx/hearing", "src/astryx/memory", "src/astryx/people", "src/astryx/pg", "src/astryx/pulse", "src/astryx/pulse/shipped_triggers", "src/astryx/security", "src/astryx/security/sqlguard", "src/astryx/security/sqlguard/shim", "src/astryx/sql"):  # goal 10224 S4: the moved tree's dirs
        (r / _d).mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / ".gitignore", r / ".gitignore")
    shutil.copy(REPO / "devtools" / "privacy_gate.sh", r / "devtools" / "privacy_gate.sh")
    (r / "nucleus" / "thing.py").write_text("def f():\n    return 1\n")
    (r / "agents").mkdir()
    (r / "agents" / "medic.example.md").write_text("# medic\n")
    sh("git", "init", "-q", "-b", "main", cwd=r)
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t"), ("commit.gpgsign", "false"),
                 (f"url.file://{host}/.pushInsteadOf", "https://github.com/")):
        sh("git", "config", k, v, cwd=r)
    sh("git", "remote", "add", "origin", origin, cwd=r)
    sh("git", "add", "-A", cwd=r)
    sh("git", "commit", "-q", "-m", "base", cwd=r)
    for d in ("homes/seed", "memory", "triggers/seed", "media"):    # an installed org's instance dirs (ignored)
        (r / d).mkdir(parents=True, exist_ok=True)
    (r / "homes" / "seed" / "notes.md").write_text("instance data: must never reach the gate's tree\n")
    for o in (LOGIN, UP.split("/")[0]):
        sh("git", "init", "-q", "--bare", str(host / o / "astryx.git"), cwd=ROOT)
    return r, host


def branch(r, name, files: dict, force=()):
    sh("git", "checkout", "-q", "-b", name, cwd=r)
    for rel, text in files.items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        sh("git", "add", "-f", rel, cwd=r)
    sh("git", "commit", "-q", "-m", name, cwd=r)
    sh("git", "checkout", "-q", "main", cwd=r)


def run(r, *extra, cfg=None, path=None, env=None, title="medic: thing returns 1", cause="f() is off by one"):
    cfgf, logf = ROOT / f"cfg-{N[0]}.json", ROOT / f"log-{N[0]}.jsonl"
    cfgf.write_text(json.dumps({"login": LOGIN, **(cfg or {})}))
    logf.write_text("")
    e = dict(ENV0, PATH=str(path or ghbin()) + os.pathsep + ENV0.get("PATH", "") if path is None else str(path),
             FAKE_GH_CFG=str(cfgf), FAKE_GH_LOG=str(logf), ASTRYX_UPSTREAM=UP, HOME=str(ROOT / "home"),
             **(env or {}))
    args = [sys.executable, str(TOOL), "--repo", str(r), "--branch", "fix", "--title", title,
            "--symptom", "thing() returns 1 when 2 was expected", "--cause", cause,
            "--remedy", "return 2", "--proof", f"{ROOT / 'home'}/astryx$ tests pass", *extra]
    p = subprocess.run(args, capture_output=True, text=True, env=e, timeout=300)
    calls = [json.loads(ln) for ln in logf.read_text().splitlines() if ln.strip()]
    return p.returncode, p.stdout + p.stderr, calls


def did(calls, *prefix):
    return [c for c in calls if c["argv"][:len(prefix)] == list(prefix)]


FIX = {"nucleus/thing.py": "def f():\n    return 2\n"}

# U1 instance paths
for rel in ("agents/sales.md", "homes/seed/notes.md", "triggers/seed/x.py", "local.md", ".env", "nucleus/tier/a.md"):
    r, _ = fixture()
    branch(r, "fix", {**FIX, rel: "x\n"})
    rc, out, calls = run(r)
    arm(f"U1 a diff touching {rel} is REFUSED (exit 2), named, nothing reaches gh",
        rc == 2 and rel in out and "instance data" in out and not calls, (rc, out))
r, _ = fixture()
branch(r, "fix", {**FIX, "agents/medic.example.md": "# medic, sharper\n"})
rc, out, _ = run(r, "--dry-run")
arm("U1 a shipped *.example charter is framework: the dry run passes", rc == 0 and "agents/medic.example.md" in out,
    (rc, out))
arm("U1 the instance-path rule itself", U.instance_paths(["nucleus/a.py", "agents/seed.md", "agents/x.example.md",
                                                          "agents/dept/x.md", "memory/m.md", "tier/a"])
    == ["agents/dept/x.md", "memory/m.md", "tier/a"])

# U2 the privacy gate
value = "9" + "2" + "300" + "1234567"                  # assembled here: the literal would trip the real gate on THIS file
r, _ = fixture()
branch(r, "fix", {"nucleus/thing.py": f"def f():\n    return 2  # call {value}\n"})
rc, out, calls = run(r)
arm("U2 a personal-tier value in the branch's tree → REFUSED by privacy_gate.sh (exit 2), nothing reaches gh",
    rc == 2 and "privacy_gate.sh FAILED" in out and "nucleus/thing.py" in out and not calls, (rc, out))
arm("U2 ...and the gate never echoes the value", value not in out, out)
r, _ = fixture()
branch(r, "fix", FIX)
rc, out, calls = run(r, cause=f"the owner's number {value} was hardcoded")
arm("U2 a personal-tier value in the PR BODY → REFUSED (exit 2), nothing reaches gh",
    rc == 2 and "PR body" in out and not calls, (rc, out))
arm("U2 the gate's value pattern is read from privacy_gate.sh, and it bites", bool(U.gate_pattern(REPO))
    and U.value_hits(value, U.gate_pattern(REPO)) and not U.value_hits("epoch 1760000000", U.gate_pattern(REPO)))
wts = sh("git", "worktree", "list", cwd=r).splitlines()
arm("U2 the gate's throwaway worktree is removed afterwards", len(wts) == 1, wts)

# U3 dedup
r, _ = fixture()
branch(r, "fix", FIX)
rc, out, calls = run(r, cfg={"prs": [{"number": 7, "title": "Medic: thing  returns 1", "body": "x",
                                      "url": "u7", "author": {"login": "someone"}}]})
arm("U3 an open PR with the same title (case/space-insensitive) → a COMMENT on it, no PR created",
    rc == 0 and did(calls, "pr", "comment", "7") and not did(calls, "pr", "create") and not did(calls, "repo", "fork"),
    (rc, out, calls))
arm("U3 ...the comment carries the four sections", all(f"## {s}" in did(calls, "pr", "comment")[0]["body"]
                                                       for s in ("Symptom", "Cause", "Remedy", "Proof")))
r, _ = fixture()
branch(r, "fix", FIX)
key = U.diagnosis_key("F()   is OFF by one")
rc, out, calls = run(r, title="medic: a different title", cfg={"prs": [
    {"number": 9, "title": "unrelated", "body": f"...\n<!-- astryx-diagnosis: {key} -->", "url": "u9",
     "author": {"login": "someone"}}]})
arm("U3 an open PR with the same DIAGNOSIS (another title) → a comment, no duplicate",
    rc == 0 and did(calls, "pr", "comment", "9") and not did(calls, "pr", "create"), (rc, out, calls))

# U4 the cap
mine = [{"number": i, "title": f"t{i}", "body": "", "url": f"u{i}", "author": {"login": LOGIN}} for i in range(3)]
r, _ = fixture()
branch(r, "fix", FIX)
rc, out, calls = run(r, cfg={"prs": mine})
arm("U4 at the default cap (3 open by this account) → nothing opened, exit 3, named",
    rc == 3 and "CAP" in out and not did(calls, "pr", "create") and not did(calls, "repo", "fork"), (rc, out))
rc, out, calls = run(r, cfg={"prs": mine}, env={"ASTRYX_UPSTREAM_MAX_OPEN": "4"})
arm("U4 the cap is env-configurable (4 → the PR opens)", rc == 0 and did(calls, "pr", "create"), (rc, out))
others = [dict(p, author={"login": "someone-else"}) for p in mine]
rc, out, calls = run(r, cfg={"prs": others})
arm("U4 other authors' PRs don't count against this org's cap", rc == 0 and did(calls, "pr", "create"), (rc, out))

# U5 no gh / logged out
r, _ = fixture()
branch(r, "fix", FIX)
rc, out, calls = run(r, path=nogh_bin())
arm("U5 no gh on PATH → exit 77, says to install it and `gh auth login`",
    rc == 77 and "gh auth login" in out and "not installed" in out, (rc, out))
rc, out, calls = run(r, cfg={"auth_rc": 1})
arm("U5 gh logged out → exit 77, says `gh auth login`, nothing beyond auth status was called",
    rc == 77 and "gh auth login" in out and [c["argv"][:2] for c in calls] == [["auth", "status"]], (rc, out, calls))

rc, out, calls = run(r, cfg={"user_rc": 1})
arm("U5 gh can't say who it is → exit 1, named; no fork, push or PR (an empty login would break cap and head)",
    rc == 1 and "gave no login" in out and not did(calls, "repo", "fork") and not did(calls, "pr", "create"),
    (rc, out, calls))

# U6 the fork path
r, host = fixture()
branch(r, "fix", FIX)
sha = sh("git", "rev-parse", "fix", cwd=r)
rc, out, calls = run(r, cfg={"fork_exists": True, "perm": "READ"})
fork = did(calls, "repo", "fork")
create = did(calls, "pr", "create")
arm("U6 a fork is asked for with --remote=false (an existing fork is reused)",
    rc == 0 and fork and fork[0]["argv"][2] == UP and "--remote=false" in fork[0]["argv"], (rc, out, calls))
pushed = subprocess.run(["git", "--git-dir", str(host / LOGIN / "astryx.git"), "rev-parse", "refs/heads/fix"],
                        capture_output=True, text=True, env=ENV0).stdout.strip()
arm("U6 the branch is pushed to the FORK", pushed == sha, (pushed, sha))
a = create[0]["argv"] if create else []
arm("U6 the PR is opened on upstream from login:branch",
    a and a[a.index("--repo") + 1] == UP and a[a.index("--head") + 1] == f"{LOGIN}:fix", a)
b = create[0].get("body", "") if create else ""
arm("U6 the body has Symptom, Cause, Remedy, Proof, the version and the platform",
    all(f"## {s}" in b for s in ("Symptom", "Cause", "Remedy", "Proof")) and "astryx version:" in b
    and "platform:" in b, b)
arm("U6 the home directory is scrubbed to ~", str(ROOT / "home") not in b and "~/astryx$" in b, b)

# U7 origin IS upstream
r, host = fixture(origin=f"https://github.com/{UP}.git")
branch(r, "fix", FIX)
rc, out, calls = run(r, cfg={"perm": "WRITE"})
a = did(calls, "pr", "create")[0]["argv"] if did(calls, "pr", "create") else []
on_origin = subprocess.run(["git", "--git-dir", str(host / UP.split("/")[0] / "astryx.git"), "rev-parse", "refs/heads/fix"],
                           capture_output=True, text=True, env=ENV0).stdout.strip()
arm("U7 origin IS upstream with write access → says so, no fork, a normal PR with the bare branch as head",
    rc == 0 and "IS the upstream" in out and not did(calls, "repo", "fork") and a and a[a.index("--head") + 1] == "fix"
    and on_origin == sh("git", "rev-parse", "fix", cwd=r), (rc, out, a))
rc, out, calls = run(r, cfg={"perm": "READ"})
arm("U7 a plain clone (origin == upstream, no write) forks instead", rc == 0 and did(calls, "repo", "fork"), (rc, out))

# U8 --is-upstream
r, _ = fixture(origin=f"git@github.com:{UP}.git")


def isup(env):
    return subprocess.run([sys.executable, str(TOOL), "--repo", str(r), "--is-upstream"], capture_output=True,
                          text=True, env={**ENV0, "ASTRYX_UPSTREAM": UP, **env}).returncode


arm("U8 origin == upstream but no declared role → NOT upstream (every clone has that origin)", isup({}) == 1)
arm("U8 origin == upstream and ASTRYX_UPSTREAM_ROLE=upstream → upstream", isup({"ASTRYX_UPSTREAM_ROLE": "upstream"}) == 0)
(r / ".env").write_text("ASTRYX_UPSTREAM_ROLE=upstream\n")
arm("U8 ...the role is read from .env too", isup({}) == 0)
arm("U8 the role with another origin → NOT upstream",
    isup({"ASTRYX_UPSTREAM_ROLE": "upstream", "ASTRYX_UPSTREAM": "someone/else"}) == 1)
arm("U8 slug() reads https, scp and ssh remotes", U.slug("https://github.com/a/b.git") == "a/b"
    and U.slug("git@github.com:a/b.git") == "a/b" and U.slug("ssh://git@github.com/a/b") == "a/b")

shutil.rmtree(ROOT, ignore_errors=True)
if fails:
    print(f"FAIL: {fails} arm(s)")
    sys.exit(1)
print("ALL PASS: upstream_pr refuses instance data and privacy hits, comments instead of duplicating, holds its cap, "
      "degrades to 77 without gh, forks or not as it should")
