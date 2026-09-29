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


ERRORS = []                                   # classification failures this run (a3 D-P)


@lru_cache(maxsize=None)
def ignored(relpath: str) -> bool:
    """FAILS CLOSED (a3 D-P). git check-ignore: 0 = ignored, 1 = not ignored, 128 = fatal (not a repo, a broken
    index). Only an explicit 1 means "safe to print and store in plaintext". Anything else, including git being
    absent from a minimal PATH, is treated as IGNORED (digest the key, print path::qualname only) and RECORDED.
    The ledger writer refuses to write and enforce reports NOT SEARCHED whenever ERRORS is non-empty. An
    authority that can't answer must never read as "not private"."""
    try:
        r = subprocess.run(["git", "check-ignore", "-q", "--no-index", relpath], cwd=REPO, capture_output=True)
    except Exception as e:
        ERRORS.append(f"{relpath}: git unavailable ({type(e).__name__})")
        return True
    if r.returncode in (0, 1):
        return r.returncode == 0
    ERRORS.append(f"{relpath}: git check-ignore rc={r.returncode}")
    return True


def _path(site_key: str) -> str:
    return site_key.split("::", 1)[0]


def text_key(site_key: str) -> str:
    """The site WITHOUT its qualname: sha256(path + SEP + normalized text). A function rename keeps it (a3 #22780),
    so the NOT-SEARCHED clock and ledger rows follow a moved site instead of resetting. It's a digest for every
    origin, so it leaks no more than ledger_key's digest does."""
    return "sha256t:" + hashlib.sha256(f"{_path(site_key)}{SEP}{site_key.split(SEP, 1)[-1]}".encode()).hexdigest()


def ledger_key(site_key: str) -> str:
    return "sha256:" + hashlib.sha256(site_key.encode()).hexdigest() if ignored(_path(site_key)) else site_key


def label(site_key: str) -> str:
    path = _path(site_key)
    if path.startswith("tier/"):
        return "<private-tier site>"
    fn = site_key.split(SEP, 1)[0]
    return fn if ignored(path) else site_key.replace(SEP, " :: ")


def handle(site_key: str) -> str:
    """What a human passes to `ledger admit`: the digest for a gitignored origin (it reveals nothing), else the
    readable key with the separator shown as ' :: '. ledger.admit() accepts either form."""
    k = ledger_key(site_key)
    return k if k.startswith("sha256:") else repr(label(site_key))
