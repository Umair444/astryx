#!/usr/bin/env python3
"""rebase_equiv.py <reviewed A..B> <rebased C..D> [--onto <ref>]: is a rebased range the SAME WORK a reviewer PASSed?

A rebase re-enters review only if it changed something. On 10-20 the evidence for "it didn't" was hand-built three
times (a4 #61445/#61452, seed's land), and a hand chain hides real defects:
  - BLOBS CAN'T BE THE TEST: once the base touched a file its blob moves whatever the rebase did. PATCH-ID CAN'T
    EITHER: it hashes context, so main editing a line next to a reviewed hunk moves an unchanged change's patch-id.
  - CHANGED LINES WITHOUT CONTEXT CAN'T EITHER (a3 #61571, six bypasses of this tool's first cut): dropping context
    drops WHERE a change applies, and position is the work (the same line added in g() not f(); "p NEW q" vs
    "p q NEW"), and +/- lines can't see a binary, a mode, a delete vs an empty file, or work moved between commits.
  - A REBASE EDITS MESSAGES: after a conflict, --continue's cleanup=strip drops every '#'-led line (1e8dbc0 lost
    "#61157): …" silently).
So the PRIMARY test is a per-commit REPLAY (a3's design, #61571). Commits pair by position, oldest first. Each reviewed
commit p is replayed onto its rebased twin's parent, `git merge-tree --merge-base=p^ q^ p`:
  - clean, and the tree IS q's tree   → PROVEN (placement, modes, binaries, deletes, per-commit content, all of it);
  - clean, and the trees differ       → DIFFERS, naming the files;
  - a conflict                        → the commit was RESOLVED BY HAND. Its non-conflicted files are still proven or
    refuted blob by blob against merge-tree's result. Each conflicted file falls back to evidence that is weaker and
    LABELLED so: its p^..p and q^..q changed lines (-U0, no context), its mode, and for a binary its ends byte-equal.
    A fallback mismatch DIFFERS; a match is "placement UNPROVEN", and the rebased hunk is printed for the reviewer.
Each raw message (git cat-file, the bytes after the header) is compared exactly. A range holding a MERGE commit is
refused (positional pairing can't place one). --onto (default main) adds "it lands": the rebased tip merges into the
ref without conflict.

rc 0 SAME WORK, every commit PROVEN; rc 1 DIFFERS, naming each difference; rc 3 no difference found, but some commit
was hand-resolved (read the printed hunks: that is what the reviewer re-reviews); rc 2 a bad ref, usage, or a merge.
Blob equality and patch-ids are printed as information, never as the verdict.
"""
import argparse
import subprocess
import sys

HUNK_CAP = 60          # lines of a hand-resolved file's rebased hunk printed for the reviewer


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


def entry(tree: str, f: str) -> str:
    """'<mode> <blob>' of f in a tree or commit, '' when absent: the mode is part of the work (a3 X3)."""
    out = git("ls-tree", tree, "--", f).split("\t", 1)[0].split()
    return f"{out[0]} {out[2]}" if out else ""


def binary(a: str, b: str, f: str) -> bool:
    return git("diff", "--no-renames", "--numstat", a, b, "--", f).startswith("-\t-\t")


def changed_lines(a: str, b: str, f: str) -> list:
    """The +/- lines of f's diff a..b with NO context: the FALLBACK for a hand-resolved file, never a proof."""
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


def fallback(p: str, q: str, f: str) -> str:
    """A hand-resolved file's weaker evidence: '' when it matches (placement still unproven), else what differs."""
    if entry(p, f).split(" ")[0] != entry(q, f).split(" ")[0]:
        return f"its mode or presence differs ({entry(p, f) or 'absent'} vs {entry(q, f) or 'absent'})"
    if binary(f"{p}^", p, f) or binary(f"{q}^", q, f):
        # a binary diff has no +/- lines, so any two would compare equal: equal only byte for byte at both ends
        same = entry(f"{p}^", f) == entry(f"{q}^", f) and entry(p, f) == entry(q, f)
        return "" if same else "a BINARY whose ends aren't byte-equal"
    if changed_lines(f"{p}^", p, f) != changed_lines(f"{q}^", q, f):
        return "its +/- lines differ"
    return ""


def replay(i: int, p: str, q: str, out: list, bad: list) -> bool:
    """Commit i's replay. Appends to out/bad; True when HAND-RESOLVED (no difference found, placement unproven)."""
    r = subprocess.run(["git", "merge-tree", "--write-tree", "--name-only", f"--merge-base={p}^", f"{q}^", p],
                       capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise LookupError(f"merge-tree on commit {i}: {r.stderr.strip()}")
    tree = r.stdout.split("\n", 1)[0].strip()
    tag = f"commit {i} ({p[:7]} → {q[:7]})"
    if r.returncode == 0:
        diff = git("diff", "--no-renames", "--name-only", tree, f"{q}^{{tree}}").split()
        if diff:
            bad.append(f"{tag}: the replay is clean but its tree differs from the rebased one in {diff}")
        else:
            out.append(f"  {tag}: PROVEN (its replay onto {q[:7]}^ is {q[:7]}'s tree)")
        return False
    conflicted = sorted({x for x in r.stdout.split("\n\n", 1)[0].split("\n")[1:] if x})
    others = [f for f in git("diff", "--no-renames", "--name-only", tree, f"{q}^{{tree}}").split() if f not in conflicted]
    if others:
        bad.append(f"{tag}: files the replay merged CLEANLY differ from the rebased commit: {others}")
    hand = []
    for f in conflicted:
        why = fallback(p, q, f)
        if why:
            bad.append(f"{tag}: HAND-RESOLVED {f}, and {why}")
        else:
            hand.append(f)
    if hand:
        out.append(f"  {tag}: HAND-RESOLVED in {hand}: changed lines, mode and presence equal, PLACEMENT UNPROVEN. "
                   f"The rebased hunks, for the reviewer:")
        for f in hand:
            h = git("diff", "--no-renames", "--no-color", f"{q}^", q, "--", f).split("\n")
            out += [f"      {ln}" for ln in h[:HUNK_CAP]] + ([f"      … {len(h) - HUNK_CAP} more"] if len(h) > HUNK_CAP else [])
    return bool(hand)


def compare(reviewed: str, rebased: str, onto: str = "main") -> tuple:
    """-> (rc, report lines). Pure over the repo it runs in, so the oracle drives it on a hermetic one."""
    try:
        (a, b), (c, d) = [r.split("..", 1) for r in (reviewed, rebased)]
        a, b, c, d = (sha(x) for x in (a, b, c, d))
        o = sha(onto) if onto else None
    except (ValueError, LookupError) as e:
        return 2, [f"rebase_equiv: {e if str(e) else 'want two ranges A..B C..D'}"]
    out, bad = [f"reviewed {a}..{b}", f"rebased  {c}..{d}"], []
    merges = git("rev-list", "--merges", f"{a}..{b}").split() + git("rev-list", "--merges", f"{c}..{d}").split()
    if merges:
        return 2, out + [f"rebase_equiv: REFUSED, a range holds a merge commit {[m[:7] for m in merges]} "
                         f"(positional pairing can't place one)"]
    old, new = commits(a, b), commits(c, d)
    if len(old) != len(new):
        bad.append(f"COMMITS: {len(old)} reviewed vs {len(new)} rebased")
    hand = False
    for i, (p, q) in enumerate(zip(old, new), 1):
        if message(p) != message(q):
            bad.append(f"MESSAGE of commit {i} ({p[:7]} → {q[:7]}) differs, {first_diff(message(p), message(q))}")
        try:
            hand |= replay(i, p, q, out, bad)
        except LookupError as e:
            return 2, out + [f"rebase_equiv: {e}"]
    fo, fn = files(a, b), files(c, d)
    if fo != fn:
        bad.append(f"FILES: only reviewed {sorted(set(fo) - set(fn))}, only rebased {sorted(set(fn) - set(fo))}")
    for f in sorted(set(fo) & set(fn)):
        ob, nb = entry(b, f).split(" ")[-1][:10] or "(deleted)", entry(d, f).split(" ")[-1][:10] or "(deleted)"
        pid = patch_id(a, b, f), patch_id(c, d, f)
        out.append(f"  {f}: " + ("blob EQUAL" if ob == nb else f"blob {ob}→{nb}") + " · patch-id "
                   + (f"{pid[0]} both" if pid[0] == pid[1] else f"{pid[0]}→{pid[1]}") + " (information)")
    if o:
        r = subprocess.run(["git", "merge-tree", "--write-tree", "--name-only", o, d], capture_output=True, text=True)
        if r.returncode:
            paths = [p for p in r.stdout.split("\n\n", 1)[0].split("\n")[1:] if p]
            bad.append(f"ONTO {onto}@{o[:7]}: {d[:7]} CONFLICTS in {paths}, so it does not land as it stands")
        else:
            out.append(f"  onto {onto}@{o[:7]}: merges clean" + (" (the rebased base IS it)" if o == c else ""))
    out += [f"  DIFFERS: {x}" for x in bad]
    if bad:
        out.append("rebase_equiv: DIFFERS: a reviewer reads it again")
        return 1, out
    if hand:
        out.append(f"rebase_equiv: HAND-RESOLVED: {len(new)} commit(s), no difference found, but the hunks above were "
                   f"resolved by hand and their placement is unproven: a reviewer reads THOSE")
        return 3, out
    out.append(f"rebase_equiv: SAME WORK: {len(new)} commit(s), each PROVEN by replay, every message equal")
    return 0, out


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
