"""own_privacy_repo(): the ONE way an oracle that reaches privacy (a ledger verb, enforce) classifies its sites.

privacy asks `git check-ignore` in privacy.REPO, the subject tree. Off git (a review extract, mutation_probe's fresh copy)
that is rc 128 and privacy rightly fails closed, so an arm measuring something else reads a privacy refusal instead.
That happened three times in plan-11908 (a3 R-4 #62836, R-5 #62849, D5 N4 #62860). Here privacy classifies in a repo
of the arm's own (a fresh `git init`, or the arm's), and privacy.REPO, its cache and ERRORS are restored on exit, so no
arm leaks a classification error into the next."""
import contextlib
import os
import subprocess
import tempfile
from pathlib import Path

from astryx.security.sqlguard import privacy


@contextlib.contextmanager
def own_privacy_repo(root=None):
    with tempfile.TemporaryDirectory() as td:
        r = Path(root) if root else Path(td)
        if root is None:
            subprocess.run(["git", "init", "-q"], cwd=r, check=True, capture_output=True,
                           env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
        real = privacy.REPO
        privacy.REPO = r
        privacy.ignored.cache_clear()
        privacy.ERRORS.clear()
        try:
            yield r
        finally:
            privacy.REPO = real
            privacy.ignored.cache_clear()
            privacy.ERRORS.clear()
