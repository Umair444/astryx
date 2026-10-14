#!/usr/bin/env python3
"""astryx · upstream_pr — medic sends a FRAMEWORK fix to the upstream astryx repo (goal 10224 S6, owner 10-14: "if face
any problem it create a PR to main astryx github repo and my medic check it and accept or reason through it").

    upstream_pr.py --branch medic/<slug> --title "medic: <diagnosis>" \
                   --symptom TEXT --cause TEXT --remedy TEXT --proof TEXT   (any of the four may be @file)
                   [--base main] [--repo PATH] [--dry-run]
    upstream_pr.py --is-upstream          exit 0 when THIS org is the upstream (init.sh's gate for upstream_prs)

What it does, in order, and refuses at the first failure:
  1. the branch's diff against its merge-base with --base names only tracked FRAMEWORK paths: agents/ (except shipped
     *.example charters), homes/, triggers/, memory/, tier/, local.md, .env, relations.md, owner.md are this org's
     instance data and never go upstream (exit 2);
  2. nucleus/privacy_gate.sh runs over the branch's tree (a throwaway worktree at the branch head: the gate scans the
     tree it lives in), and the gate's own value pattern runs over the PR body (exit 2 on a hit);
  3. gh is present and logged in, else it prints what to run and exits 77;
  4. an open upstream PR with the same title or the same diagnosis gets a COMMENT instead of a duplicate (exit 0);
  5. at most ASTRYX_UPSTREAM_MAX_OPEN (default 3) open upstream PRs by this gh account, else exit 3;
  6. when this checkout can push to upstream itself (origin IS upstream and gh says this account may write), a normal
     PR from a branch on origin; otherwise a fork (`gh repo fork --remote=false`, reused when it exists), the branch
     pushed there, and `gh pr create --repo <upstream>`.
The body carries Symptom, Cause, Remedy, Proof, the astryx version and the OS; the home directory is scrubbed to ~.

"Is this org the upstream?" is origin == ASTRYX_UPSTREAM AND ASTRYX_UPSTREAM_ROLE=upstream (env, then .env). Origin
alone can't say it: every plain clone of the public repo has origin == upstream.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_UPSTREAM = "Umair444/astryx"
DEFAULT_CAP = 3
EXIT_REFUSED, EXIT_CAP, EXIT_NO_GH = 2, 3, 77
WRITE_PERMS = {"ADMIN", "MAINTAIN", "WRITE"}
# instance data: never upstream. Shipped example charters (and seed's) are framework, as privacy_gate.sh (b) allows.
INSTANCE = re.compile(r"^(homes|triggers|memory|tier|backups|media|wacli-data)(/|$)|(^|/)tier/"
                      r"|^(local\.md|\.env(\..*)?|relations\.md|owner\.md)$")
AGENT_OK = re.compile(r"^agents/(seed/|seed\.md$|[^/]*\.example(\.md)?$|[^/]*\.example/)")
PROOF_MAX = 20000


def _env(repo: Path) -> dict:
    """The process env with every GIT_* scrubbed: a hook's GIT_DIR would point git at another repo."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def setting(name: str, default: str = "", repo: Path = REPO) -> str:
    """Env first, then the repo's .env."""
    if os.environ.get(name):
        return os.environ[name]
    f = repo / ".env"
    for line in (f.read_text(errors="replace").splitlines() if f.is_file() else []):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


def upstream(repo: Path = REPO) -> str:
    return setting("ASTRYX_UPSTREAM", DEFAULT_UPSTREAM, repo).strip().strip("/")


def slug(url: str) -> str | None:
    """owner/name from a GitHub remote URL (https, ssh, scp form), or None."""
    m = re.search(r"(?:github\.com[:/]|^)([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", (url or "").strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def git(repo: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=_env(repo), timeout=120)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip() if r.returncode == 0 else ""


def origin(repo: Path = REPO) -> str | None:
    try:
        return slug(git(repo, "remote", "get-url", "origin"))
    except Exception:                                      # noqa: BLE001: no git, no repo, no origin: not upstream
        return None


def same(a: str | None, b: str | None) -> bool:
    return bool(a and b) and a.lower() == b.lower()


def is_upstream(repo: Path = REPO) -> bool:
    """This org IS the upstream: origin matches AND the owner declared the role (a plain clone matches origin too)."""
    return same(origin(repo), upstream(repo)) and setting("ASTRYX_UPSTREAM_ROLE", "", repo).lower() == "upstream"


def gh(args: list[str], repo: Path = REPO, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, cwd=repo, env=_env(repo), timeout=timeout)


def gh_problem(repo: Path = REPO) -> str | None:
    """None when gh is usable; else what to run, in words a human can paste."""
    if not shutil.which("gh"):
        return "gh (GitHub CLI) is not installed: install it (https://cli.github.com), then run `gh auth login`"
    try:
        r = gh(["auth", "status"], repo, timeout=20)
    except Exception as e:                                 # noqa: BLE001
        return f"`gh auth status` could not run ({e}); run `gh auth login`"
    if r.returncode != 0:
        return "gh is not logged in: run `gh auth login` (then `gh auth setup-git` so git can push to your fork)"
    return None


# ── what may go upstream ──────────────────────────────────────────────────────────────────────────────────────────
def instance_paths(paths: list[str]) -> list[str]:
    return [p for p in paths if INSTANCE.search(p) or (p.startswith("agents/") and not AGENT_OK.match(p))]


def gate_pattern(repo: Path = REPO) -> str:
    """privacy_gate.sh's (c) value regex, read from the gate itself (one writer): the `grep -lEI '<re>'` line."""
    src = (repo / "nucleus" / "privacy_gate.sh").read_text()
    m = re.search(r"grep -lEI '([^']+)'", src)
    if not m:
        raise RuntimeError("nucleus/privacy_gate.sh carries no `grep -lEI '<pattern>'` value scan any more")
    return m.group(1)


def value_hits(text: str, pattern: str) -> bool:
    """The gate's grep -E pattern over text. \\b is the one non-ERE construct it uses, and python reads it the same."""
    return re.search(pattern, text) is not None


def privacy(repo: Path, sha: str, body: str) -> list[str]:
    """The gate over the branch's tree, and its value pattern over the body. [] = clean."""
    out = []
    tmp = Path(tempfile.mkdtemp(prefix="astryx-upstream-gate-"))
    wt = tmp / "tree"
    try:
        git(repo, "worktree", "add", "--detach", "--quiet", str(wt), sha)
        # the gate's (b) asks check-ignore about homes/, memory/, triggers/ ... and a dir-only rule (`homes/`) matches
        # only a path that EXISTS as a dir: a fresh checkout fails (b) on rules that are fine. Mirror this checkout's
        # ignored top-level dirs, EMPTY (nothing of them is copied; they're ignored, so the tracked tree is unchanged).
        for e in repo.iterdir():
            if e.is_dir() and e.name != ".git" and not (wt / e.name).exists() \
                    and subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", e.name],
                                       env=_env(repo)).returncode == 0:
                (wt / e.name).mkdir()
        gate = wt / "nucleus" / "privacy_gate.sh"
        if not gate.is_file():
            out.append("the branch carries no nucleus/privacy_gate.sh to run")
        else:
            r = subprocess.run(["bash", str(gate)], capture_output=True, text=True, cwd=wt, env=_env(repo),
                               timeout=300)
            if r.returncode != 0:
                fails = [ln for ln in r.stdout.splitlines() if ln.startswith(("FAIL", "  "))]
                out.append("nucleus/privacy_gate.sh FAILED on the branch:\n" + "\n".join(fails[:20]))
        if value_hits(body, gate_pattern(wt if gate.is_file() else repo)):
            out.append("the PR body carries a personal-tier value (phone/JID pattern from privacy_gate.sh (c))")
    finally:
        git(repo, "worktree", "remove", "--force", str(wt), check=False)
        shutil.rmtree(tmp, ignore_errors=True)
    return out


# ── the body ──────────────────────────────────────────────────────────────────────────────────────────────────────
def scrub(text: str) -> str:
    """Home paths become ~ (a proof pasted from a terminal carries /home/<user>/)."""
    home = os.path.expanduser("~")
    return text.replace(home, "~") if home and home != "/" else text


def version(repo: Path = REPO) -> str:
    try:
        return git(repo, "describe", "--tags", "--always") or "unknown"
    except Exception:                                      # noqa: BLE001
        return "unknown"


def platform_line() -> str:
    return f"{platform.system()} {platform.release()} ({platform.machine()}), python {platform.python_version()}"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def diagnosis_key(cause: str) -> str:
    return hashlib.sha256(norm(scrub(cause)).encode()).hexdigest()[:16]


def make_body(symptom, cause, remedy, proof, ver, plat, org="") -> str:
    proof = scrub(proof)
    if len(proof) > PROOF_MAX:
        proof = proof[:PROOF_MAX] + "\n… (truncated)"
    return (f"## Symptom\n{scrub(symptom).strip()}\n\n## Cause\n{scrub(cause).strip()}\n\n"
            f"## Remedy\n{scrub(remedy).strip()}\n\n## Proof\n{proof.strip()}\n\n"
            f"---\nastryx version: `{ver}` · platform: {plat}\n"
            f"Opened by an astryx org's medic with nucleus/upstream_pr.py.\n"
            f"<!-- astryx-diagnosis: {diagnosis_key(cause)} -->\n" + (f"<!-- astryx-org: {org} -->\n" if org else ""))


def find_dup(prs: list[dict], title: str, cause: str) -> dict | None:
    key = f"astryx-diagnosis: {diagnosis_key(cause)}"
    for p in prs:
        if norm(p.get("title", "")) == norm(title) or key in (p.get("body") or ""):
            return p
    return None


def _text(v: str) -> str:
    return Path(v[1:]).read_text() if v.startswith("@") else v


def _json(r: subprocess.CompletedProcess, what: str):
    if r.returncode != 0:
        raise RuntimeError(f"{what}: {(r.stderr or r.stdout).strip()[:300]}")
    return json.loads(r.stdout or "null")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=os.environ.get("ASTRYX_REPO") or str(REPO))
    ap.add_argument("--is-upstream", action="store_true")
    ap.add_argument("--branch")
    ap.add_argument("--title")
    for s in ("symptom", "cause", "remedy", "proof"):
        ap.add_argument(f"--{s}", default="")
    ap.add_argument("--base", default=os.environ.get("ASTRYX_UPSTREAM_BASE", "main"))
    ap.add_argument("--dry-run", action="store_true", help="check and print the body; touch nothing on GitHub")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()

    if a.is_upstream:
        up = is_upstream(repo)
        print(f"{'this org IS' if up else 'this org is NOT'} the upstream ({upstream(repo)}; origin "
              f"{origin(repo) or 'none'}; ASTRYX_UPSTREAM_ROLE={setting('ASTRYX_UPSTREAM_ROLE', '', repo) or 'unset'})")
        return 0 if up else 1

    missing = [s for s in ("branch", "title", "symptom", "cause", "remedy", "proof") if not getattr(a, s)]
    if missing:
        print(f"upstream_pr: missing --{', --'.join(missing)}: a PR body without all four sections is not ready")
        return EXIT_REFUSED
    symptom, cause, remedy, proof = (_text(getattr(a, s)) for s in ("symptom", "cause", "remedy", "proof"))

    try:
        sha = git(repo, "rev-parse", "--verify", f"{a.branch}^{{commit}}")
        base = git(repo, "merge-base", a.base, sha)
        paths = [p for p in git(repo, "diff", "--name-only", f"{base}..{sha}").splitlines() if p]
    except RuntimeError as e:
        print(f"upstream_pr: {e}")
        return 1
    if not paths:
        print(f"upstream_pr: {a.branch} changes nothing against {a.base}: nothing to send")
        return EXIT_REFUSED
    bad = instance_paths(paths)
    if bad:
        print("upstream_pr: REFUSED: the diff touches this org's instance data, which never goes upstream:\n  "
              + "\n  ".join(bad) + "\nSplit the framework fix onto its own branch.")
        return EXIT_REFUSED

    body = make_body(symptom, cause, remedy, proof, version(repo), platform_line(), setting("ASTRYX_ORG", "", repo))
    hits = privacy(repo, sha, body)
    if hits:
        print("upstream_pr: REFUSED by the privacy gate:\n" + "\n".join(hits))
        return EXIT_REFUSED
    if a.dry_run:
        print(f"upstream_pr: dry run, {len(paths)} framework file(s) clean:\n  " + "\n  ".join(paths)
              + f"\n--- title ---\n{a.title}\n--- body ---\n{body}")
        return 0

    why = gh_problem(repo)
    if why:
        print(f"upstream_pr: cannot reach GitHub: {why}. Nothing was sent; the fix stays on {a.branch}.")
        return EXIT_NO_GH

    up = upstream(repo)
    bodyf = Path(tempfile.mkdtemp(prefix="astryx-upstream-body-")) / "body.md"
    try:
        login = gh(["api", "user", "--jq", ".login"], repo).stdout.strip()
        prs = _json(gh(["pr", "list", "--repo", up, "--state", "open", "--limit", "200",
                        "--json", "number,title,body,url,author"], repo), "gh pr list") or []
        dup = find_dup(prs, a.title, cause)
        if dup:
            bodyf.write_text(f"Another astryx org hit this too ({a.title}).\n\n{body}")
            r = gh(["pr", "comment", str(dup["number"]), "--repo", up, "--body-file", str(bodyf)], repo)
            if r.returncode != 0:
                raise RuntimeError(f"gh pr comment: {(r.stderr or r.stdout).strip()[:300]}")
            print(f"upstream_pr: #{dup['number']} already carries this diagnosis ({dup.get('url', '')}); "
                  "commented there instead of opening a duplicate")
            return 0
        cap = int(setting("ASTRYX_UPSTREAM_MAX_OPEN", str(DEFAULT_CAP), repo) or DEFAULT_CAP)
        mine = [p for p in prs if login and (p.get("author") or {}).get("login", "").lower() == login.lower()]
        if len(mine) >= cap:
            print(f"upstream_pr: CAP: {len(mine)} open upstream PR(s) by {login} already (cap {cap}, "
                  f"ASTRYX_UPSTREAM_MAX_OPEN): " + ", ".join(f"#{p['number']}" for p in mine)
                  + f". Nothing opened; the fix stays on {a.branch}.")
            return EXIT_CAP
        bodyf.write_text(body)
        perm = (_json(gh(["repo", "view", up, "--json", "viewerPermission"], repo), "gh repo view") or {}) \
            .get("viewerPermission", "")
        if same(origin(repo), up) and perm in WRITE_PERMS:
            print(f"upstream_pr: this checkout's origin IS the upstream ({up}) and {login} may write to it: "
                  "a normal PR from a branch on origin, no fork")
            git(repo, "push", "origin", f"{sha}:refs/heads/{a.branch}")
            head = a.branch
        else:
            r = gh(["repo", "fork", up, "--remote=false", "--clone=false"], repo)
            if r.returncode != 0 and "already exists" not in (r.stdout + r.stderr):
                raise RuntimeError(f"gh repo fork: {(r.stderr or r.stdout).strip()[:300]}")
            fork = f"{login}/{up.split('/', 1)[1]}"
            try:
                git(repo, "push", f"https://github.com/{fork}.git", f"{sha}:refs/heads/{a.branch}")
            except RuntimeError as e:
                print(f"upstream_pr: push to your fork {fork} failed: {e}\nRun `gh auth setup-git` (git then pushes "
                      "with gh's login) and try again.")
                return 1
            head = f"{login}:{a.branch}"
        r = gh(["pr", "create", "--repo", up, "--base", a.base, "--head", head, "--title", a.title,
                "--body-file", str(bodyf)], repo)
        if r.returncode != 0:
            raise RuntimeError(f"gh pr create: {(r.stderr or r.stdout).strip()[:300]}")
        print(f"upstream_pr: opened {r.stdout.strip()}")
        return 0
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"upstream_pr: {e}")
        return 1
    finally:
        shutil.rmtree(bodyf.parent, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
