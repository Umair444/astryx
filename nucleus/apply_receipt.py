#!/usr/bin/env python3
"""apply_receipt — apply a reviewed body to a gitignored live path and EMIT its receipt (plan-5791).

    venv/bin/python nucleus/apply_receipt.py <staged> <live path> --expect <sha256> --pass <msg id>
        [--snapshot <dir>]

A receipt with hand-typed shas is a promise: a typo either breaks the chain (a false TAIL-MISMATCH)
or forges a link, and the five plan_consensus receipts of 09-29 named the before only, or none
(a3 #28076 BC-3). So ONE writer computes both sides: this script hashes the live file, byte-verifies
the staged body against the sha256 the reviewer PASSed, replaces the live file atomically (same
directory, mode kept), re-reads it, and prints the one line the merge_ready watch reads:

    applied: <repo-relative path> <sha256 before> → <sha256 after> (PASS #<id>)

`absent` is the before of a NEW file — the chain's genesis, not a gap. Paste the printed line into
the apply receipt on the wire verbatim. Nothing is written if the staged body does not match
--expect, or the live path is outside the repo. Exit 0 applied · 2 refused.
"""
import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("staged")
    ap.add_argument("live")
    ap.add_argument("--expect", required=True, help="sha256 of the PASSed staged body (a prefix of >=8 is ok)")
    ap.add_argument("--pass", dest="pass_id", required=True, type=int, help="the PASS message id")
    ap.add_argument("--snapshot", help="copy the live file here first")
    ap.add_argument("--repo", default=str(REPO), help=argparse.SUPPRESS)   # the oracle's hermetic root
    a = ap.parse_args(argv)

    root = Path(a.repo).resolve()
    live = Path(a.live).absolute()
    try:
        rel = live.resolve().relative_to(root)
    except ValueError:
        print(f"REFUSED: {live} is not under the repo {root}", file=sys.stderr)
        return 2
    expect = a.expect.lower()
    if len(expect) < 8 or any(ch not in "0123456789abcdef" for ch in expect):
        print("REFUSED: --expect must be a sha256 hex (>= 8 chars)", file=sys.stderr)
        return 2
    body = Path(a.staged).read_bytes()
    got = sha256_bytes(body)
    if not got.startswith(expect):
        print(f"REFUSED: staged {a.staged} is {got[:16]}…, the PASS named {expect[:16]}… — nothing written",
              file=sys.stderr)
        return 2

    before = sha256_bytes(live.read_bytes()) if live.exists() else "absent"
    if before != "absent" and a.snapshot:
        snap = Path(a.snapshot)
        snap.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live, snap / f"{live.name}.{before[:12]}.{int(time.time())}")
    mode = live.stat().st_mode & 0o7777 if live.exists() else 0o644
    live.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=live.parent, prefix=f".{live.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        os.chmod(tmp, mode)
        os.replace(tmp, live)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    after = sha256_bytes(live.read_bytes())                   # re-read: the receipt names what IS there
    if after != got:
        print(f"FAILED: live reads {after[:16]}… after the write, staged was {got[:16]}…", file=sys.stderr)
        return 2
    print(f"applied: {rel} {before} → {after} (PASS #{a.pass_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
