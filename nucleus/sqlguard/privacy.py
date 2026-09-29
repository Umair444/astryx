"""The ONE place that decides what sqlguard may WRITE (to the tracked ledger) or PRINT (check.sh stdout, which
run_check can relay to the wire) about a site (a3 #22368, P1).

CLAUDE.md's privacy invariant: gitignored files (triggers/, memory/, tier/, …) are never committed and never
pasted anywhere public. A site key is `relpath::qualname␟<normalised SQL>`, so for a gitignored file the key
IS derived content. So:
  ledger_key(k)  a tracked-file site keeps its readable key (that code is already in git). A gitignored-origin
                 site is stored as "sha256:<hex>" of the full key. The guard derives keys at runtime and
                 compares DIGESTS, so equality, shrink-only and --admit all work unchanged.
  label(k)       for printing. A gitignored-origin site is `path::qualname` only, never its SQL text. A tier/
                 site is "<private-tier site>", with nothing from tier/ at all.
"Ignored" is asked of git (`git check-ignore`, the same patterns in any checkout), never a hand-kept list.
"""
import hashlib
import subprocess
from functools import lru_cache

from nucleus.sqlguard.inventory import REPO

SEP = "\x1f"


@lru_cache(maxsize=None)
def ignored(relpath: str) -> bool:
    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", relpath], cwd=REPO)
    return r.returncode == 0


def _path(site_key: str) -> str:
    return site_key.split("::", 1)[0]


def ledger_key(site_key: str) -> str:
    return "sha256:" + hashlib.sha256(site_key.encode()).hexdigest() if ignored(_path(site_key)) else site_key


def label(site_key: str) -> str:
    path = _path(site_key)
    if path.startswith("tier/"):
        return "<private-tier site>"
    fn = site_key.split(SEP, 1)[0]
    return fn if ignored(path) else site_key.replace(SEP, " :: ")
