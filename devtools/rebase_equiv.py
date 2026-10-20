#!/usr/bin/env python3
"""rebase_equiv.py <reviewed A..B> <rebased C..D> [--onto <ref>]: is a rebased range the SAME WORK a reviewer PASSed?

A rebase re-enters review only if it changed something, and on 10-20 the evidence for "it didn't" was hand-built three
times (a4 #61445/#61452, seed's land), with two defects a hand chain hides:
  1. BLOBS CAN'T BE THE TEST. Once the base touched a file, its blob on the rebased tip differs whatever the rebase
     did. And patch-id can't be the test either: it hashes CONTEXT lines, so a main commit that edits a line NEXT to a
     reviewed hunk changes the patch-id of an unchanged change (probe-why-r1's test file, de56 vs c9d7). The test is the
     CHANGED LINES alone: per file, the -U0 diff's +/- lines, in order, with no hunk header and no context.
  2. A REBASE EDITS MESSAGES. After a conflict, `git rebase --continue` runs the message through cleanup=strip, which
     drops every line starting with '#', and this org wraps "#61157)" onto a line start. 1e8dbc0 lost one silently.
     So each commit's raw message (git cat-file, the bytes after the header) is compared exactly.
--onto (default main) adds what "lands" means: the rebased tip merges into that ref without conflict (merge-tree).

Commits pair by position, oldest first. rc 0 SAME WORK (counts, file sets, changed lines and messages all equal, and
no conflict with --onto); rc 1 DIFFERS, naming each difference; rc 2 a bad ref or usage. Blob equality and patch-ids
are printed as information, never as the verdict.
"""
import argparse
import subprocess
import sys


def git(*a, check=True) -> str:
    r = subprocess.run(["git", *a], capture_output=True, text=True)
    if check and r.returncode:
        raise LookupError(f"git {' '.join(a)}: {r.stderr.strip()}")
    return r.stdout


def sha(ref: str) -> str:
    s = git("rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False).strip()
    if not s:
        raise LookupError(f"no such commit: {ref}")
    return s


def commits(a: str, b: str) -> list:
    return git("rev-list", "--reverse", "--topo-order", f"{a}..{b}").split()


def message(c: str) -> str:
    raw = git("cat-file", "commit", c)
    return raw.split("\n\n", 1)[1] if "\n\n" in raw else ""


def files(a: str, b: str) -> list:
    return sorted(git("diff", "--no-renames", "--name-only", a, b).split("\n")[:-1])


def binary(a: str, b: str, f: str) -> bool:
    return git("diff", "--no-renames", "--numstat", a, b, "--", f).startswith("-\t-\t")


def changed_lines(a: str, b: str, f: str) -> list:
    """The +/- lines of f's diff a..b with NO context and no hunk headers: what the change IS, wherever it sits."""
    out = git("diff", "--no-renames", "-U0", "--no-color", a, b, "--", f)
    return [ln for ln in out.split("\n") if ln[:1] in "+-" and not ln.startswith(("+++ ", "--- "))]


def patch_id(a: str, b: str, f: str = None) -> str:
    d = subprocess.run(["git", "diff", "--no-renames", a, b] + (["--", f] if f else []), capture_output=True).stdout
    r = subprocess.run(["git", "patch-id", "--stable"], input=d, capture_output=True).stdout.decode().split()
    return r[0][:12] if r else "-"


def first_diff(x: str, y: str) -> str:
    xs, ys = x.split("\n"), y.split("\n")
    for i, (p, q) in enumerate(zip(xs, ys), 1):
        if p != q:
            return f"line {i}: {p!r} vs {q!r}"
    return f"line {min(len(xs), len(ys)) + 1}: one message has {abs(len(xs) - len(ys))} more line(s)"


def compare(reviewed: str, rebased: str, onto: str = "main") -> tuple:
    """-> (rc, report lines). Pure over the repo it runs in, so the oracle drives it on a hermetic one."""
    try:
        (a, b), (c, d) = [r.split("..", 1) for r in (reviewed, rebased)]
        a, b, c, d = (sha(x) for x in (a, b, c, d))
        o = sha(onto) if onto else None
    except (ValueError, LookupError) as e:
        return 2, [f"rebase_equiv: {e if str(e) else 'want two ranges A..B C..D'}"]
    out, bad = [f"reviewed {a}..{b}", f"rebased  {c}..{d}"], []
    old, new = commits(a, b), commits(c, d)
    if len(old) != len(new):
        bad.append(f"COMMITS: {len(old)} reviewed vs {len(new)} rebased")
    for i, (p, q) in enumerate(zip(old, new), 1):
        if message(p) != message(q):
            bad.append(f"MESSAGE of commit {i} ({p[:7]} → {q[:7]}) differs, {first_diff(message(p), message(q))}")
    fo, fn = files(a, b), files(c, d)
    if fo != fn:
        bad.append(f"FILES: only reviewed {sorted(set(fo) - set(fn))}, only rebased {sorted(set(fn) - set(fo))}")
    for f in sorted(set(fo) & set(fn)):
        if binary(a, b, f) or binary(c, d, f):
            # a binary diff has no +/- lines ("Binary files … differ"), so ANY two changes would compare equal. A
            # binary is the same work only byte for byte at both ends; otherwise a reader can't separate the rebase
            # from main's own edit, and it DIFFERS (fail closed)
            ends = [git("rev-parse", f"{x}:{f}", check=False).strip() for x in (a, c, b, d)]
            same = ends[0] == ends[1] and ends[2] == ends[3]
        else:
            same = changed_lines(a, b, f) == changed_lines(c, d, f)
        if not same:
            bad.append(f"CHANGE in {f}: its +/- lines differ (the rebase changed what the commit does here)"
                       if not binary(c, d, f) else f"CHANGE in {f}: a BINARY whose ends aren't byte-equal (read it)")
        ob = git("rev-parse", f"{b}:{f}", check=False).strip()[:10] or "(deleted)"
        nb = git("rev-parse", f"{d}:{f}", check=False).strip()[:10] or "(deleted)"
        blob = "blob EQUAL" if ob == nb else f"blob {ob}→{nb}"
        pid = patch_id(a, b, f), patch_id(c, d, f)
        out.append(f"  {f}: changed lines {'EQUAL' if same else 'DIFFER'} · {blob} · patch-id "
                   + (f"{pid[0]} both" if pid[0] == pid[1] else f"{pid[0]}→{pid[1]} (context moved)"))
    out.append(f"  whole range patch-id {patch_id(a, b)} vs {patch_id(c, d)} (information: it hashes context)")
    if o:
        r = subprocess.run(["git", "merge-tree", "--write-tree", "--name-only", o, d], capture_output=True, text=True)
        if r.returncode:
            paths = [p for p in r.stdout.split("\n\n", 1)[0].split("\n")[1:] if p]
            bad.append(f"ONTO {onto}@{o[:7]}: {d[:7]} CONFLICTS in {paths}, so it does not land as it stands")
        else:
            out.append(f"  onto {onto}@{o[:7]}: merges clean" + (" (the rebased base IS it)" if o == c else ""))
    out += [f"  DIFFERS: {x}" for x in bad]
    out.append("rebase_equiv: " + ("DIFFERS: a reviewer reads it again" if bad else
                                   f"SAME WORK: {len(new)} commit(s), every changed line and message equal"))
    return (1 if bad else 0), out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("reviewed")
    ap.add_argument("rebased")
    ap.add_argument("--onto", default="main", help="the ref it must merge into cleanly ('' skips; default main)")
    a = ap.parse_args()
    rc, lines = compare(a.reviewed, a.rebased, a.onto)
    print("\n".join(lines))
    return rc


if __name__ == "__main__":
    sys.exit(main())
