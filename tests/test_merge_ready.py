#!/usr/bin/env python3
"""Oracle for triggers/seed/merge_ready.py — the merge-ready watch (plan-5791) — and nucleus/apply_receipt.py.

    venv/bin/python tests/test_merge_ready.py   (MERGE_READY_SRC=<path> overrides the subject)

The subject is gitignored (triggers/), so it is path-loaded; absent → SKIP 77. Every git arm runs in a
HERMETIC temp repo with its own bare `origin` (never this repo, never a fetch). Arms (design a4 #27819;
conditions a1 #27821, a3 #28076, a2 #28077, a4 #28080):
  1. marker grammar: ready/supersedes/retract/hold/applied parse; a quoted <template> is not a claim;
     malformed lines and a supersedes without a merge-ready are reported; a hold needs a reason.
  2. prose PASS instrument: 'PASS <sha>' is a verdict; 'NOT PASS' and 'PASS/REVISE' are not.
  3. request flags (a2 C1): a request TO the sender → REQUESTED; the sender announced the range first
     → SELF-MARKED; neither → UNREQUESTED. LIVE (read-only, fixed ids): a2's four real PASSes
     (#23332 #23400 #23791 #27591) and a3's first marker #28083 all read REQUESTED.
  4. the machine, hermetic: a synthetic PASS reads PASSED (RED-first) → rebase-landed under a new sha
     reads MERGED-not-pushed → pushed reads silent; merge→revert reads BACKED-OUT and the `diff c^ c -R`
     spelling provably misses it (a2 C2 RED control); revert-of-revert reads MERGED again (a3 BC-1);
     a squash is an INSTRUMENTS-DISAGREE notice; a replacement on a retracted base reports only its own
     commit; supersedes retracts the old set in one row; a fresh hold trails, a stale one is STANDING;
     an unresolvable range is a notice; UNREQUESTED/SELF-MARKED print, REQUESTED does not.
  5. coverage (a1 BC-2): a pre-adoption prose PASS on an unlanded commit is BACKFILL; post-adoption it
     is STANDING; a merge-retract clears it; a landed commit is never listed.
  6. gitignored chain (a3 G1/BC-3) with the REAL helper: 3 applies chain silently; a direct live edit is
     TAIL-MISMATCH; a '?' sha is a GAP; a non-linking before is a BREAK; the helper refuses a body that
     does not match --expect (live untouched) and names a new file's before `absent`.
  7. blind checker: no `main` → Blind, never "nothing merged".
  8. dedup: same sets silent; change speaks; standing re-nags after RENAG_S; notices do not; lost state
     re-alarms; empty is silent.
  9. ENTRYPOINT through pulse_run's OWN Ctx on a sqlguard fixture DB: a local marker reports; a pulse
     row and a foreign-org row carrying markers are ignored; the next run is silent.
Exit 0 pass · 1 fail · 77 could-not-run (a partial skip is a 77 too).
"""
import datetime as dt
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Scrub every inherited GIT_* FIRST: under a linked-worktree pre-push, GIT_DIR names the SHARED repo, and a
# child git (the body's patch-id pipe, a `git init`) would then act on it — the 09-29 core.bare incident class.
for _k in [k for k in os.environ if k.startswith("GIT_")]:
    del os.environ[_k]
REPO = Path(__file__).resolve().parents[1]
BODY = Path(os.environ.get("MERGE_READY_SRC") or REPO / "triggers" / "seed" / "merge_ready.py")
PY = sys.executable
HELPER = REPO / "nucleus" / "apply_receipt.py"
fails, skips = [], []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


# ------------------------------------------------------------------------------------------------ 0
# The TRACKED helper needs no watch body, so its arms run FIRST and everywhere — a fresh clone included
# (a3 #32619: the reachability exemption says "its oracle is what check.sh runs", which must not depend on
# the gitignored body being present). A plain temp dir as --repo: the helper never touches git.
import hashlib  # noqa: E402
print("0. apply_receipt helper (tracked; needs no watch body):")
_h0 = tempfile.TemporaryDirectory()
H0 = Path(_h0.name) / "repo"
(H0 / "triggers" / "seed").mkdir(parents=True)
H0LIVE = H0 / "triggers" / "seed" / "x.py"
H0B = []
for _i in range(3):
    _b = Path(_h0.name) / f"stage{_i}.py"
    _b.write_text(f"# body {_i}\n")
    H0B.append(_b)


def happly(b, live=H0LIVE, expect=None, pass_id=7):
    exp = expect or hashlib.sha256(b.read_bytes()).hexdigest()
    return subprocess.run([PY, str(HELPER), str(b), str(live), "--expect", exp, "--pass", str(pass_id),
                           "--repo", str(H0)], capture_output=True, text=True)


_rs = [happly(b, pass_id=100 + i) for i, b in enumerate(H0B)]
check("helper: 3 sequential applies exit 0", all(x.returncode == 0 for x in _rs), str([x.stderr for x in _rs]))
_ln = [x.stdout.strip().split() for x in _rs]
_sha = [hashlib.sha256(b.read_bytes()).hexdigest() for b in H0B]
check("helper: a NEW file's before is `absent`; the receipt names the repo-relative path and PASS id",
      _ln[0][:3] == ["applied:", "triggers/seed/x.py", "absent"] and _ln[0][-2:] == ["(PASS", "#100)"], str(_ln[0]))
check("helper: every after-sha is the COMPUTED sha256 of the body applied, and each before is the prior after",
      [x[4] for x in _ln] == _sha and [x[2] for x in _ln[1:]] == _sha[:2], str(_ln))
_before = H0LIVE.read_bytes()
_bad = happly(H0B[0], expect="0" * 64)
check("helper REFUSES a body that does not match --expect, and writes nothing",
      _bad.returncode == 2 and "REFUSED" in _bad.stderr and H0LIVE.read_bytes() == _before, _bad.stderr)
_o = happly(H0B[0], expect="zz")
check("helper REFUSES a non-hex --expect", _o.returncode == 2, _o.stderr)
_o = happly(H0B[0], live=Path(_h0.name) / "outside.py")
check("helper REFUSES a live path outside the repo",
      _o.returncode == 2 and not (Path(_h0.name) / "outside.py").exists(), _o.stderr)
_link = H0 / "triggers" / "seed" / "linked.py"
_link.symlink_to(H0LIVE)
_o = happly(H0B[0], live=_link)
check("helper REFUSES a symlinked live path (os.replace would swap the link for a file; a3 #29321 nit)",
      _o.returncode == 2 and _link.is_symlink() and H0LIVE.read_bytes() == _before, _o.stderr)

if not BODY.exists():
    if fails:
        print(f"\nFAIL: {len(fails)} helper arm(s); the watch body is absent (gitignored triggers/), its arms not run")
        sys.exit(1)
    print("\nSKIP (partial): the helper's arms PASSED; the merge_ready body is absent (gitignored triggers/) — "
          "every watch arm unverified.")
    sys.exit(77)
sys.path.insert(0, str(REPO))
try:
    _s = importlib.util.spec_from_file_location("merge_ready_under_test", BODY)
    m = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(m)
except Exception as e:  # noqa: BLE001
    print(f"SKIP: merge_ready not importable ({type(e).__name__}: {e}).")
    sys.exit(77)

NOW = dt.datetime.now(dt.timezone.utc)
POST = m.ADOPTION_MSG_ID + 1000          # message ids after the adoption boundary
PRE = 100                                # and before it


def msg(i, body, sender="abstractor-3", to="seed", ts=None):
    return {"id": i, "ts": ts or NOW, "from_agent": sender, "to_agent": to, "thread": "t", "body": body}


# ------------------------------------------------------------------------------------------------ 1
print("1. marker grammar:")
A, B, C = "a" * 40, "b" * 40, "c" * 40
P = m.parse_markers([
    msg(1, f"REVIEW ok: PASS.\nmerge-ready: feat/x {A[:7]}..{B[:7]}\nsupersedes: {A[:7]}..{C[:7]}\n"),
    msg(2, "- `merge-ready: <branch> <base>..<head>`: the grammar\nmerge-ready: <branch> <base>..<head>"),
    msg(3, "merge-ready: feat/y notarange"),
    msg(4, f"supersedes: {A[:7]}..{B[:7]}"),
    msg(5, f"merge-retract: {A[:9]} {B[:7]} withdrawn, see #3", sender="abstractor-4"),
    msg(6, f"merge-hold: {C[:7]} waiting on the owner's sign-off", sender="seed"),
    msg(7, f"merge-hold: {C[:7]}", sender="seed"),
    msg(8, f"applied: ./triggers/seed/x.py {'1' * 64} → {'2' * 64} (PASS #42)\n"
           f"applied: triggers/seed/x.py {'2' * 64} -> ? (#43)\napplied: triggers/new.py absent → {'3' * 64}"),
])
r = P["ready"]
check("merge-ready parses branch/base/head", len(r) == 1 and (r[0]["branch"], r[0]["base"], r[0]["head"])
      == ("feat/x", A[:7], B[:7]), str(r))
check("a quoted <template> line is not a claim (and not MALFORMED)", not any(b["id"] == 2 for b in P["malformed"]),
      str(P["malformed"]))
check("a merge-ready without a range is MALFORMED", any(b["id"] == 3 for b in P["malformed"]), str(P["malformed"]))
P3 = m.parse_markers([msg(20, f"merge-ready: feat/n {A[:7]}..{B[:7]} (a2 PASS #31541)\nsupersedes: {A[:7]}..{C[:7]} (old)"),
                      msg(21, f"merge-ready: feat/n {A[:7]}..{B[:7]} and more words")])
check("a trailing '(...)' note after the range parses (live a1 #31542 read MALFORMED and went unwatched)",
      [r["id"] for r in P3["ready"]] == [20] and any(x.get("range") == (A[:7], C[:7]) for x in P3["retract"]), str(P3))
check("  any other trailing text is still MALFORMED", [b["id"] for b in P3["malformed"]] == [21], str(P3["malformed"]))
check("supersedes without a merge-ready in the same message is MALFORMED",
      any(b["id"] == 4 and "without a merge-ready" in b.get("why", "") for b in P["malformed"]))
sup = [x for x in P["retract"] if x.get("range")]
check("supersedes in the ready's message → a retract of the old range, superseded-by its head",
      len(sup) == 1 and sup[0]["range"] == (A[:7], C[:7]) and sup[0]["superseded_by"] == B[:7], str(sup))
ret = [x for x in P["retract"] if x.get("shas")]
check("merge-retract names its shas, attributed", len(ret) == 1 and ret[0]["shas"] == [A[:9], B[:7]]
      and ret[0]["sender"] == "abstractor-4", str(ret))
check("merge-hold keeps its reason; a hold with no reason is MALFORMED",
      len(P["hold"]) == 1 and P["hold"][0]["reason"] == "waiting on the owner's sign-off"
      and any(b["id"] == 7 for b in P["malformed"]), str(P["hold"]))
ap = P["applied"]
check("applied: → and -> both parse; './' is the same path; PASS id read",
      len(ap) == 3 and ap[0]["path"] == ap[1]["path"] == "triggers/seed/x.py" and ap[0]["pass_id"] == 42, str(ap))
check("applied: '?' kept as a gap token; `absent` is a genesis before",
      ap[1]["after"] == "?" and ap[2]["before"] == "absent", str(ap))

# ------------------------------------------------------------------------------------------------ 2
print("\n2. prose PASS instrument:")
pp = m.prose_passes([msg(1, "REVIEW abc1234: PASS."), msg(2, "NOT PASS abc1234"),
                     msg(3, "PASS/REVISE here on abc1234"), msg(4, "PASS with no sha"),
                     msg(5, "PASSes abc1234")])
check("'PASS <sha>' is a verdict; NOT PASS / PASS/REVISE / PASSes / no-sha are not",
      [x[0]["id"] for x in pp] == [1] and pp[0][1] == ["abc1234"], str([(x[0]["id"], x[1]) for x in pp]))
# the live false positives of 09-30 (steward #29220, a3 #29321): DISCUSSION naming a sha with PASS further down,
# and a REVISE lead that says "before I PASS", became STANDING nags. A verdict LEADS (a1 #27806 F5): first line.
pp = m.prose_passes([msg(6, "plan-5791 built, in review.\nbackfill: aeb21dc (a3 PASS #22311), clear it"),
                     msg(7, "BUILD REVIEW → REVISE (one defect)\nfbcb8fe: fix it before I PASS with the marker"),
                     msg(8, "REVIEW fbcb8fe → REVISE, then PASS on the re-post"),
                     msg(9, "Review of 9c1b729 (doorbell): PASS. Seed, this clears the merge.\nalso 1b510a2")])
check("a verdict must LEAD: PASS deeper in a discussion, or on a REVISE first line, is not a verdict",
      [x[0]["id"] for x in pp] == [9], str([x[0]["id"] for x in pp]))
check("  a leading verdict still names shas from the WHOLE body", pp and pp[0][1] == ["1b510a2", "9c1b729"],
      str(pp and pp[0][1]))

# ------------------------------------------------------------------------------------------------ 3
print("\n3. request flags (a2 C1):")
check("a request TO the sender → REQUESTED",
      m.request_flag("a2", [], [{"id": 1, "from_agent": "steward", "to_agent": "a2"}])[0] == "REQUESTED")
check("the sender announced the range to another first → SELF-MARKED",
      m.request_flag("forge", [], [{"id": 1, "from_agent": "forge", "to_agent": "a4"},
                                   {"id": 2, "from_agent": "a4", "to_agent": "forge"}])[0] == "SELF-MARKED")
check("nothing earlier → UNREQUESTED", m.request_flag("a9", [], [])[0] == "UNREQUESTED")
# a3 #31311 R2: a BRANCH name can be written before any commit exists (an assignment: "build it on plan-x-fix"),
# so branch evidence must never pick `first`: the builder who then announces its range by sha and self-marks is
# SELF-MARKED. Branch rows only upgrade UNREQUESTED → REQUESTED.
check("a branch-only ASSIGNMENT before the builder's sha announce does not hide SELF-MARKED (a3 R2)",
      m.request_flag("builder", [], [{"id": 1, "from_agent": "seed", "to_agent": "builder", "by_sha": False},
                                     {"id": 2, "from_agent": "builder", "to_agent": "a2", "by_sha": True}])[0]
      == "SELF-MARKED")
check("  branch-only evidence TO the sender upgrades UNREQUESTED → REQUESTED",
      m.request_flag("a2", [], [{"id": 1, "from_agent": "a1", "to_agent": "a2", "by_sha": False}])[0] == "REQUESTED")
check("  branch-only evidence FROM the sender never makes it SELF-MARKED (only a sha can say who built it)",
      m.request_flag("a9", [], [{"id": 1, "from_agent": "a9", "to_agent": "a3", "by_sha": False}])[0] == "UNREQUESTED")
check("a note-to-self is not an announcement → UNREQUESTED",
      m.request_flag("a9", [], [{"id": 1, "from_agent": "a9", "to_agent": "a9"}])[0] == "UNREQUESTED")
try:
    _p = importlib.util.spec_from_file_location("pulse_run_mr", REPO / "nucleus" / "pulse_run.py")
    pr = importlib.util.module_from_spec(_p)
    _p.loader.exec_module(pr)
    live = pr.Ctx({})
    live.sql("SELECT 1")
except Exception as e:  # noqa: BLE001
    live = None
    print(f"  SKIP  live request arms — wire unreachable ({type(e).__name__}: {e})")
    skips.append("live request arms")
if live is not None:
    earlier = m._earlier(live)                         # the entrypoint's own SQL, SELECT-only, fixed ids
    for mid, sender, sha in ((23332, "abstractor-2", "b10f007"), (23400, "abstractor-2", "2bdbb76"),
                             (23791, "abstractor-2", "f61bbf8"), (27591, "abstractor-2", "b9d7792"),
                             (28083, "abstractor-3", "bfa7a2e")):
        flag, ev = m.request_flag(sender, [], earlier(mid, [sha]))
        check(f"live #{mid} ({sender} on {sha}) → REQUESTED", flag == "REQUESTED", f"{flag} {ev}")
    live._conn and live._conn.close()

# ------------------------------------------------------------------------------------------------ 4
print("\n4. the machine (a hermetic temp repo with its own bare origin):")
_tmp = tempfile.TemporaryDirectory()
TD = Path(_tmp.name)
T = TD / "r"
ORIGIN = TD / "origin.git"
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}   # a hook's GIT_DIR must not leak in
ENV.update(GIT_CONFIG_NOSYSTEM="1", HOME=str(TD))
G = ["git", "-C", str(T), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


def git(*a, check=True):
    r = subprocess.run(G + list(a), capture_output=True, text=True, env=ENV)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {a}: {r.stderr}")
    return r.stdout.strip()


def commit(path, text, subject):
    f = T / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    git("add", path)
    git("commit", "-q", "-m", subject)
    return git("rev-parse", "HEAD")


subprocess.run(["git", "init", "-q", "--bare", str(ORIGIN)], check=True, env=ENV)
subprocess.run(["git", "init", "-q", "-b", "main", str(T)], check=True, env=ENV)
(T / ".gitignore").write_text("triggers/\n")
git("add", ".gitignore")
git("commit", "-q", "-m", "root")
commit("base.txt", "base\n", "base")
git("remote", "add", "origin", str(ORIGIN))
git("push", "-q", "origin", "main")
_orig_run = m.Git.run


def _hermetic_run(self, *args, stdin=None, check=False):      # the body's git sees the scrubbed env too
    r = subprocess.run(["git", "-C", str(self.repo), *args], input=stdin, capture_output=True, text=True,
                       timeout=20, env=ENV)
    return r


m.Git.run = _hermetic_run


def ev(msgs, prose=(), earlier=lambda mid, pre, br=None: [{"id": 1, "from_agent": "builder", "to_agent": "abstractor-3"}]):
    st, no, tr, dom = m.evaluate(msgs, list(prose), earlier, T, now=NOW.timestamp())
    return ("\n".join(x[1] for x in st), "\n".join(x[1] for x in no), "\n".join(tr), dom, st, no)


main0 = git("rev-parse", "main")
git("checkout", "-q", "-b", "f1")
c1 = commit("f1.txt", "one\n", "f1: the synthetic change")
git("checkout", "-q", "main")
MK1 = msg(POST + 1, f"PASS.\nmerge-ready: f1 {main0[:7]}..{c1[:7]}")
st, no, tr, dom, S, N = ev([MK1])
check("RED-FIRST: a synthetic PASS on an unmerged sha → STANDING 'PASSED, not merged'",
      "PASSED, not merged: " + c1[:10] in st, st)
check("  attributed to its marker (#id, sender, stated range)", f"abstractor-3 #{POST + 1}" in st, st)
check("the domain line states the exact-inverse residual and the never-fetch rule",
      "exact inverse" in dom and "never fetches" in dom, dom)
commit("moves.txt", "main moved\n", "main moves on")          # a new parent, so the pick CAN'T reuse c1's sha
git("cherry-pick", c1)                                       # rebase-landed: same patch, new sha
landed = git("rev-parse", "HEAD")
st, *_ = ev([MK1])
check("rebase-landed under a new sha → 'MERGED, not pushed' (patch-id '-')",
      landed != c1 and "MERGED, not pushed: " + c1[:10] in st and "PASSED" not in st, st)
git("push", "-q", "origin", "main")
st, no, *_ = ev([MK1])
check("pushed → silent once merged (no standing, no disagreement)", st == "" and no == "", st + no)

# merge → revert → BACKED-OUT; the -R spelling misses it (a2 C2)
git("checkout", "-q", "-b", "f2")
c2 = commit("f2.txt", "two\n", "f2: to be backed out")
git("checkout", "-q", "main")
git("merge", "-q", "--no-ff", "-m", "merge f2", "f2")
git("revert", "--no-edit", c2)
rv = git("rev-parse", "HEAD")
git("push", "-q", "origin", "main")
MK2 = msg(POST + 2, f"merge-ready: f2 {main0[:7]}..{c2[:7]}")
st, *_ = ev([MK2])
check("merge → clean revert → STANDING 'BACKED-OUT', naming the reverting commit",
      f"BACKED-OUT: {c2[:10]}" in st and rv[:10] in st, st)


def _inv_R(self, c):
    r = self.run("diff", "--no-color", "-U0", f"{c}^", c, "-R")     # differs from the body ONLY in -R
    return self._patch_id(r.stdout)


_real_inv = m.Git.inv_pid
m.Git.inv_pid = _inv_R
stR, *_ = ev([MK2])
m.Git.inv_pid = _real_inv
check("RED CONTROL: the `diff c^ c -R` spelling never matches the revert → reads not-BACKED-OUT (fail-open)",
      "BACKED-OUT" not in stR, stR)
git("revert", "--no-edit", rv)                               # revert-of-revert: re-land
git("push", "-q", "origin", "main")
st, *_ = ev([MK2])
check("land → revert → re-land → not BACKED-OUT (the latest carrier decides; a3 BC-1)",
      "BACKED-OUT" not in st and c2[:10] not in st, st)

# a3 #29321 R1: a CLEAN revert whose diff CONTEXT moved (main edited a neighbour line between landing and revert)
# must still read BACKED-OUT. With context-hashing patch-ids it read PUSHED and left the standing set in silence.
NUM = "".join(f"{i}\n" for i in range(1, 21))
commit("ctx.txt", NUM, "ctx: twenty lines")
git("push", "-q", "origin", "main")
ctx_base = git("rev-parse", "HEAD")
git("checkout", "-q", "-b", "f8")
c8 = commit("ctx.txt", NUM.replace("\n5\n", "\nFIVE\n"), "f8: change five")
git("checkout", "-q", "main")
git("merge", "-q", "--no-ff", "-m", "merge f8", "f8")
commit("ctx.txt", (T / "ctx.txt").read_text().replace("\n7\n", "\nSEVEN\n"), "main: neighbour seven")
git("revert", "--no-edit", c8)
rv8 = git("rev-parse", "HEAD")
git("push", "-q", "origin", "main")
st, *_ = ev([msg(POST + 5, f"merge-ready: f8 {ctx_base[:7]}..{c8[:7]}")])
check("a clean revert with SHIFTED CONTEXT (a neighbour edited in between) → BACKED-OUT, naming the reverter",
      "FIVE" not in (T / "ctx.txt").read_text() and f"BACKED-OUT: {c8[:10]}" in st and rv8[:10] in st, st)

# ... and when the landing is a REBASE (a cherry-pick, not an ancestor), the branch commit's OWN patch-id must be
# context-free too, or it never finds its landing in main's -U0 log
git("checkout", "-q", "-b", "f9")
c9 = commit("ctx.txt", (T / "ctx.txt").read_text().replace("\n10\n", "\nTEN\n"), "f9: change ten")
git("checkout", "-q", "main")
commit("moves9.txt", "m\n", "main moves before the pick")
git("cherry-pick", c9)
pick9 = git("rev-parse", "HEAD")
commit("ctx.txt", (T / "ctx.txt").read_text().replace("\n12\n", "\nTWELVE\n"), "main: neighbour twelve")
git("revert", "--no-edit", pick9)
rv9 = git("rev-parse", "HEAD")
git("push", "-q", "origin", "main")
st, *_ = ev([msg(POST + 6, f"merge-ready: f9 {git('merge-base', 'main', c9)[:7]}..{c9[:7]}")])
check("a REBASE-landed commit, reverted after a neighbour edit → BACKED-OUT (its own patch-id is context-free)",
      "TEN" not in (T / "ctx.txt").read_text() and f"BACKED-OUT: {c9[:10]}" in st and rv9[:10] in st, st)

# squash → DISAGREE
git("checkout", "-q", "-b", "f3")
c3a = commit("f3a.txt", "3a\n", "f3: first squashed half")
c3b = commit("f3b.txt", "3b\n", "f3: second squashed half")
git("checkout", "-q", "main")
git("merge", "-q", "--squash", "f3")
git("commit", "-q", "-m", "squash f3\n\n* f3: first squashed half\n* f3: second squashed half")
git("push", "-q", "origin", "main")
st, no, *_ = ev([msg(POST + 3, f"merge-ready: f3 {main0[:7]}..{c3b[:7]}")])
check("a squash merge → an INSTRUMENTS DISAGREE notice per commit (patch-id '+', subject in main)",
      no.count("INSTRUMENTS DISAGREE") == 2 and c3a[:10] in no and c3b[:10] in no, no)
check("  and stays STANDING (the loud side), never silently resolved", c3a[:10] in st and c3b[:10] in st, st)

# replacement on a retracted base
git("checkout", "-q", "-b", "f4", main0)
c4a = commit("f4.txt", "4a\n", "f4: retracted base")
c4b = commit("f4b.txt", "4b\n", "f4: replacement")
git("checkout", "-q", "main")
st, no, tr, *_ = ev([msg(POST + 10, f"merge-ready: f4 {main0[:7]}..{c4a[:7]}"),
                     msg(POST + 11, f"merge-retract: {c4a[:7]}"),        # SAME sender: cancels its own
                     msg(POST + 12, f"merge-ready: f4 {c4a[:7]}..{c4b[:7]}")])
check("a replacement PASS on a retracted base reports ONLY its own commit",
      c4b[:10] in st and c4a[:10] not in st, st)
check("  the retract trails, attributed (by <agent> #<id>)", f"retracted {c4a[:10]} by abstractor-3 #{POST + 11}"
      in tr, tr)

# supersedes
git("checkout", "-q", "-b", "f5", main0)
x1 = commit("f5.txt", "v1\n", "f5: first attempt")
git("checkout", "-q", "-b", "f5b", main0)
x2 = commit("f5.txt", "v2\n", "f5: reworked")
git("checkout", "-q", "main")
st, no, tr, *_ = ev([msg(POST + 20, f"merge-ready: f5 {main0[:7]}..{x1[:7]}"),
                     msg(POST + 21, f"merge-ready: f5b {main0[:7]}..{x2[:7]}\nsupersedes: {main0[:7]}..{x1[:7]}")])
check("supersedes: retracts the old set in one row; only the replacement is standing",
      x2[:10] in st and x1[:10] not in st and f"superseded-by {x2[:7]}" in tr, st + " | " + tr)

# the live #28111 shape: a re-PASS whose new range RE-COVERS the superseded commit keeps it standing
git("checkout", "-q", "-b", "f5c", main0)
y1 = commit("f5c.txt", "y1\n", "f5c: base half")
y2 = commit("f5d.txt", "y2\n", "f5c: delta on top")
git("checkout", "-q", "main")
st, no, tr, *_ = ev([msg(POST + 22, f"merge-ready: f5c {main0[:7]}..{y1[:7]}"),
                     msg(POST + 23, f"merge-ready: f5c {main0[:7]}..{y2[:7]}\nsupersedes: {main0[:7]}..{y1[:7]}")])
check("supersedes + a new range that re-covers the old commit → the commit stays STANDING (ready wins in-message)",
      y1[:10] in st and y2[:10] in st and y1[:10] not in tr, st + " | " + tr)

# RETRACT RULES (a2 #31306, a4 #31308, steward #31309, a3 #31839): nobody silences another sender's claim
git("checkout", "-q", "-b", "f11", main0)
c11 = commit("f11.txt", "11\n", "f11: contested")
git("checkout", "-q", "-b", "f11b", main0)
c12 = commit("f11.txt", "12\n", "f11: someone else's rework")
git("checkout", "-q", "main")
A3 = msg(POST + 80, f"PASS\nmerge-ready: f11 {main0[:7]}..{c11[:7]}")
OBJ = msg(POST + 81, f"merge-retract: {c11[:7]} doesn't carry over", sender="abstractor-4")
st, no, tr, *_ = ev([A3, msg(POST + 79, f"merge-ready: f11 {main0[:7]}..{c11[:7]}", sender="abstractor-4"),
                     msg(POST + 81, f"merge-retract: {c11[:7]}", sender="abstractor-4")])
check("a4 #31303 shape: the builder retracting its OWN self-mark leaves the reviewer's PASS standing",
      f"PASSED, not merged: {c11[:10]}" in st and "abstractor-3 #" in st and "CONTESTED" not in st, st)
st, no, tr, *_ = ev([A3, OBJ])
check("aeb21dc shape: a CROSS-sender retract → STANDING 'CONTESTED', the PASS and the objection both printed",
      f"CONTESTED, not merged: {c11[:10]}" in st and f"abstractor-3 #{POST + 80}" in st
      and f"objected by abstractor-4 #{POST + 81}: doesn't carry over" in st and "PASSED, not merged" not in st, st)
st, no, tr, *_ = ev([A3, OBJ, msg(POST + 82, f"merge-retract: {c11[:7]}")])
check("discharge (1): the ORIGINAL marker's sender retracts → nothing stands; the retract trails",
      c11[:10] not in st and f"retracted {c11[:10]} by abstractor-3 #{POST + 82}" in tr, st + " | " + tr)
st, no, tr, *_ = ev([A3, OBJ, msg(POST + 82, f"merge-ready: f11 {main0[:7]}..{c11[:7]}", sender="abstractor-4")])
check("discharge (2): the OBJECTOR marks it merge-ready afterwards → withdrawn, attributed; PASSED again",
      f"PASSED, not merged: {c11[:10]}" in st and "CONTESTED" not in st
      and f"objection #{POST + 81} by abstractor-4 withdrawn by its own merge-ready #{POST + 82}" in tr, st + " | " + tr)
st, no, tr, *_ = ev([A3, OBJ, msg(POST + 82, f"merge-hold: {c11[:7]} owner call", sender="seed")])
check("discharge (3): a later merge-hold → HELD (trailing), still naming the objection",
      "CONTESTED" not in st and "HELD" in tr and f"objected by abstractor-4 #{POST + 81}" in tr, st + " | " + tr)
st, *_ = ev([A3, OBJ, msg(POST + 82, f"merge-hold: {c11[:7]} owner call", sender="seed", ts=NOW - dt.timedelta(days=m.HOLD_DAYS + 1))])
check("  ... and a stale hold on a contest is STANDING-HOLD, objection still named",
      "STANDING-HOLD" in st and f"objected by abstractor-4 #{POST + 81}" in st, st)
st, *_ = ev([A3, msg(POST + 82, f"merge-hold: {c11[:7]} owner call", sender="seed"),
             msg(POST + 83, f"merge-retract: {c11[:7]} doesn't carry over", sender="abstractor-4")])
check("a hold placed BEFORE the objection does not discharge it (the objection is news) → CONTESTED",
      f"CONTESTED, not merged: {c11[:10]}" in st, st)
st, *_ = ev([A3, OBJ, msg(POST + 82, f"PASS again\nmerge-ready: f11 {main0[:7]}..{c11[:7]}")])
check("NEGATIVE: the objected-to reviewer re-marking does NOT clear the contest",
      f"CONTESTED, not merged: {c11[:10]}" in st, st)
st, *_ = ev([A3, msg(POST + 81, f"merge-ready: f11b {main0[:7]}..{c12[:7]}\nsupersedes: {main0[:7]}..{c11[:7]}",
                     sender="abstractor-4")])
check("a CROSS-sender supersedes → CONTESTED for the old range (never cancelling), marked as a supersedes",
      f"CONTESTED, not merged: {c11[:10]}" in st and "(a supersedes)" in st and f"PASSED, not merged: {c12[:10]}" in st, st)

# a3 #32627 F1, the live #28491 shape: ONE message = a same-sender `supersedes:` of the unlanded PRE-rebase commit
# + a `merge-ready:` of the landed rebased one. Both share a -U0 key, but git cherry is context-sensitive, so the
# watch must judge the commit the STANDING marker names — judging the first-seen (old) one nagged a merged branch.
commit("ctxr.txt", NUM, "ctxr: twenty lines")
rb0 = git("rev-parse", "HEAD")
git("checkout", "-q", "-b", "fr1")
r1 = commit("ctxr.txt", NUM.replace("\n5\n", "\nFIVE\n"), "fr: change five (pre-rebase)")
git("checkout", "-q", "main")
commit("ctxr.txt", NUM.replace("\n7\n", "\nSEVEN\n"), "main: ctxr neighbour seven")
rb1 = git("rev-parse", "HEAD")
git("checkout", "-q", "-b", "fr2")
r2 = commit("ctxr.txt", (T / "ctxr.txt").read_text().replace("\n5\n", "\nFIVE\n"), "fr: change five (rebased)")
git("checkout", "-q", "main")
git("merge", "-q", "--no-ff", "-m", "merge fr2", "fr2")
git("push", "-q", "origin", "main")
st, no, tr, *_ = ev([msg(POST + 90, f"merge-ready: fr1 {rb0[:7]}..{r1[:7]}", sender="abstractor-4"),
                     msg(POST + 91, f"merge-ready: fr2 {rb1[:7]}..{r2[:7]}\nsupersedes: {rb0[:7]}..{r1[:7]}",
                         sender="abstractor-4")])
check("F1: supersedes of an unlanded pre-rebase commit + the LANDED rebased range in one message → nothing standing",
      r1[:10] not in st and r2[:10] not in st, st)

# a3 #32627 F3, the live #30443 shape: a reviewer's ONE message re-covering another sender's range (supersedes +
# a merge-ready that includes it) is not an objection plus a withdrawal
git("checkout", "-q", "-b", "f13", main0)
d1 = commit("f13a.txt", "d1\n", "f13: builder's first commit")
d2 = commit("f13b.txt", "d2\n", "f13: the delta")
git("checkout", "-q", "main")
st, no, tr, *_ = ev([msg(POST + 95, f"merge-ready: f13 {main0[:7]}..{d1[:7]}", sender="abstractor-4"),
                     msg(POST + 96, f"PASS\nmerge-ready: f13 {main0[:7]}..{d2[:7]}\nsupersedes: {main0[:7]}..{d1[:7]}")])
check("F3: one message re-covering another's range prints no 'objection … withdrawn by its own' line",
      "withdrawn" not in tr and "CONTESTED" not in st and f"PASSED, not merged: {d1[:10]}" in st, st + " | " + tr)

# holds
git("checkout", "-q", "-b", "f6", main0)
c6 = commit("f6.txt", "6\n", "f6: held")
git("checkout", "-q", "main")
R6 = msg(POST + 30, f"merge-ready: f6 {main0[:7]}..{c6[:7]}")
st, no, tr, *_ = ev([R6, msg(POST + 31, f"merge-hold: {c6[:7]} waits on the owner", sender="seed")])
check("a fresh hold trails with reason and sender, and is NOT standing",
      c6[:10] not in st and "waits on the owner" in tr and f"seed #{POST + 31}" in tr, st + " | " + tr)
old = NOW - dt.timedelta(days=m.HOLD_DAYS + 1)
st, *_ = ev([R6, msg(POST + 31, f"merge-hold: {c6[:7]} waits on the owner", sender="seed", ts=old)])
check("a hold older than HOLD_DAYS → STANDING-HOLD (a defer can't go permanent by being forgotten)",
      "STANDING-HOLD" in st and c6[:10] in st, st)

# unresolvable, flags
st, no, *_ = ev([msg(POST + 40, f"merge-ready: gone {'d' * 7}..{'e' * 7}")])
check("an unresolvable range → a notice (never silently unwatched)", "does not resolve" in no, no)
st, no, *_ = ev([R6], earlier=lambda mid, pre, br=None: [])
check("UNREQUESTED prints for a marker no one asked for", f"UNREQUESTED #{POST + 30}" in no, no)
st, no, *_ = ev([R6], earlier=lambda mid, pre, br=None: [{"id": 5, "from_agent": "abstractor-3", "to_agent": "abstractor-1"}])
check("SELF-MARKED prints for the builder's own marker", f"SELF-MARKED #{POST + 30}" in no, no)
st, no, *_ = ev([R6])
check("REQUESTED does not print", "REQUESTED" not in no and "SELF-MARKED" not in no, no)
# the 09-30 live shape: the reviewer marked the range (REQUESTED), then the BUILDER re-marked it as one range
REV6 = msg(POST + 32, f"PASS\nmerge-ready: f6 {main0[:7]}..{c6[:7]}", sender="abstractor-2")
SELF6 = msg(POST + 33, f"merge-ready: f6 {main0[:7]}..{c6[:7]}", sender="builder")


def _req(mid, pre, br=None):                     # the builder asked abstractor-2 for the review, before both markers
    return [{"id": 1, "from_agent": "builder", "to_agent": "abstractor-2"}]


st, no, *_ = ev([REV6, SELF6], earlier=_req)
check("a builder re-marking a reviewer-marked range: still SELF-MARKED, and names its corroboration",
      f"SELF-MARKED #{POST + 33} by builder" in no and f"corroborated: every commit also marked by abstractor-2 #{POST + 32}"
      in no, no)
st, no, *_ = ev([SELF6], earlier=_req)
check("  without the reviewer's marker there is no corroboration claim", f"SELF-MARKED #{POST + 33}" in no
      and "corroborated" not in no, no)
git("checkout", "-q", "-b", "f10", main0)
c10a = commit("f10a.txt", "a\n", "f10: reviewed half")
c10b = commit("f10b.txt", "b\n", "f10: unreviewed half")
git("checkout", "-q", "main")
st, no, *_ = ev([msg(POST + 34, f"PASS\nmerge-ready: f10 {main0[:7]}..{c10a[:7]}", sender="abstractor-2"),
                 msg(POST + 35, f"merge-ready: f10 {main0[:7]}..{c10b[:7]}", sender="builder")], earlier=_req)
check("  a reviewer marker covering only PART of the self-marked range → no corroboration claim",
      f"SELF-MARKED #{POST + 35}" in no and "corroborated" not in no, no)

git("cherry-pick", c11)
git("push", "-q", "origin", "main")
st, no, *_ = ev([A3, OBJ])
check("discharge (4): the patch LANDS while contested → a 'MERGED WHILE CONTESTED' notice, never a silent drop",
      f"MERGED WHILE CONTESTED: {c11[:10]}" in no and f"objected by abstractor-4 #{POST + 81}" in no
      and c11[:10] not in st, st + " | " + no)

# ------------------------------------------------------------------------------------------------ 5
print("\n5. prose coverage + adoption boundary (a1 BC-2):")
git("checkout", "-q", "-b", "f7", main0)
c7 = commit("f7.txt", "7\n", "f7: prose only")
git("checkout", "-q", "main")
st, no, *_ = ev([], prose=[msg(PRE, f"REVIEW {c7[:7]}: PASS")])
check("a pre-adoption prose PASS on an unlanded commit → BACKFILL notice, not standing",
      c7[:10] in no and c7[:10] not in st, st + " | " + no)
st, no, *_ = ev([], prose=[msg(POST + 50, f"REVIEW {c7[:7]}: PASS")])
check("post-adoption → a 'PASS WITHOUT MARKER' NOTICE, never STANDING (a prose false positive — live a4 #32896, a "
      "REQUEST whose lead said 'for your build PASS' — must not cost seed a nag a day)",
      f"PASS WITHOUT MARKER: {c7[:10]}" in no and c7[:10] not in st, st + " | " + no)
st, no, tr, *_ = ev([msg(POST + 51, f"merge-retract: {c7[:7]}", sender="seed")],
                    prose=[msg(PRE, f"REVIEW {c7[:7]}: PASS"), msg(POST + 50, f"REVIEW {c7[:7]}: PASS")])
check("a merge-retract clears it from BOTH (the aeb21dc case leaves the steady state)",
      c7[:10] not in st and c7[:10] not in no, st + " | " + no)
check("  ... and the clearing is ATTRIBUTED in the trailer (a3 #32627 F2: a silencer nobody sees is what M4 forbids)",
      f"cleared {c7[:10]} by seed #{POST + 51}" in tr, tr)
st, no, *_ = ev([], prose=[msg(POST + 52, f"REVIEW {c1[:7]}: PASS"), msg(POST + 53, f"NOT PASS {c7[:7]}")])
check("a landed commit is never listed; NOT PASS is not a verdict", st == "" and no == "", st + " | " + no)

# ------------------------------------------------------------------------------------------------ 6
print("\n6. gitignored chain, with the REAL helper:")
LIVE = T / "triggers" / "seed" / "x.py"
bodies = []
for i in range(3):
    b = TD / f"stage{i}.py"
    b.write_text(f"# body {i}\n")
    bodies.append(b)


def apply(b, expect=None, pass_id=7):
    exp = expect or hashlib.sha256(b.read_bytes()).hexdigest()
    return subprocess.run([PY, str(HELPER), str(b), str(LIVE), "--expect", exp, "--pass", str(pass_id),
                           "--repo", str(T)], capture_output=True, text=True)


rs = [apply(b, pass_id=100 + i) for i, b in enumerate(bodies)]
check("helper: 3 applies into the hermetic git repo exit 0", all(x.returncode == 0 for x in rs), str([x.stderr for x in rs]))
lines = [x.stdout.strip() for x in rs]
check("  the first receipt there is a genesis (`absent`)",
      lines[0].startswith("applied: triggers/seed/x.py absent → "), lines[0])
RC = [msg(POST + 60 + i, f"applied to the live tree:\n{ln}", sender="seed") for i, ln in enumerate(lines)]
st, no, tr, dom, *_ = ev(RC)
check("3 sequential receipts chain: live == tail → silent (no standing, no notice)", st == "" and no == "", st + no)
check("the watched path is DECLARED in the domain line", "triggers/seed/x.py" in dom, dom)
before = LIVE.read_bytes()
LIVE.write_text("# hand edit, no review\n")
st, *_ = ev(RC)
check("a direct live edit → STANDING TAIL-MISMATCH", "TAIL-MISMATCH" in st, st)
LIVE.write_bytes(before)
h = [ln.split() for ln in lines]
gap = msg(POST + 70, f"applied: triggers/seed/x.py {h[2][4]} → ? (PASS #9)", sender="seed")
st, no, *_ = ev(RC + [gap])
check("a receipt missing a sha → a named GAP, and the tail reads UNVERIFIABLE (never landed)",
      "GAP #" in no and "tail UNVERIFIABLE" in st, st + " | " + no)
brk = msg(POST + 71, f"applied: triggers/seed/x.py {'9' * 64} → {h[2][4]} (PASS #10)", sender="seed")
st, no, *_ = ev(RC + [brk])
check("a before that is not the previous after → BREAK notice", f"BREAK before #{POST + 71}" in no, no)
P2 = m.parse_markers(RC)
check("the helper's own lines parse as a 3-link chain (computed, never typed)",
      len(P2["applied"]) == 3 and P2["applied"][2]["after"] == hashlib.sha256(before).hexdigest(), str(P2["applied"]))

# ------------------------------------------------------------------------------------------------ 7
print("\n7. blind checker:")
try:
    m.evaluate([MK1], [], lambda *a: [], TD)            # TD is not a repo
    check("a checker with no `main` raises Blind", False, "no exception")
except m.Blind:
    check("a checker with no `main` raises Blind (never reads as 'nothing merged')", True)

# ------------------------------------------------------------------------------------------------ 8
print("\n8. dedup:")
S1 = [("passed:x", "l")]
N1 = [("dis:y", "l")]
s = {}
t0 = 1_000_000.0
check("first sight speaks", m.decide(s, S1, N1, now=t0))
check("same sets → silent", not m.decide(s, S1, N1, now=t0 + 60))
check("standing non-empty → re-nags after RENAG_S", m.decide(s, S1, N1, now=t0 + m.RENAG_S + 1))
s2 = {}
m.decide(s2, [], N1, now=t0)
check("notices alone do NOT re-nag", not m.decide(s2, [], N1, now=t0 + 10 * m.RENAG_S))
check("a changed set speaks at once", m.decide(s, S1 + [("passed:z", "l")], N1, now=t0 + m.RENAG_S + 2))
check("lost state re-alarms (the loud side)", m.decide({}, S1, [], now=t0))
check("all clear → silent", not m.decide({"standing": ["passed:x"]}, [], [], now=t0))

# ------------------------------------------------------------------------------------------------ 9
print("\n9. entrypoint (pulse_run.Ctx on a sqlguard fixture):")
try:
    import psycopg
    from nucleus.sqlguard.fixture import fixture_db
    _fx = fixture_db()
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"  SKIP  entrypoint arms — fixture/runner unavailable ({type(e).__name__}: {e})")
    skips.append("entrypoint")
    fx = None
if fx is not None:
    conn = psycopg.connect(fx["dsn"], autocommit=True)
    try:
        class TempCtx(pr.Ctx):
            def __init__(self, state, connection):
                super().__init__(state)
                self._conn = connection

        def put(frm, body, org="local", to="seed"):
            return conn.execute("INSERT INTO messages (from_agent, from_org, to_agent, body) VALUES (%s,%s,%s,%s) "
                                "RETURNING id", (frm, org, to, body)).fetchone()[0]

        m.REPO = T
        check("an empty wire → silent", m.merge_ready(TempCtx({}, conn)) is None)
        put("builder", f"please review {c6[:7]}", to="abstractor-3")
        put("pulse", f"quoted:\nmerge-ready: f4 {main0[:7]}..{c4b[:7]}")
        put("abstractor-9", f"merge-ready: f7 {main0[:7]}..{c7[:7]}", org="peer.example")
        req_id = put("abstractor-3", f"PASS\nmerge-ready: f6 {main0[:7]}..{c6[:7]}")
        # nobody asked abstractor-5, and the only earlier mention of c4b is the PULSE row: the real earlier-query
        # must return ZERO rows here (sqlguard's W rung needs both 0 and >=1 rows from it)
        unreq_id = put("abstractor-5", f"PASS\nmerge-ready: f4 {c4a[:7]}..{c4b[:7]}")
        # 09-30 live shape (a1 #29322 → a2 #29323): the request names the BRANCH only, never a sha in the range
        put("builder", "the next commit on feat/branch-only-ask is up, please look", to="abstractor-6")
        br_id = put("abstractor-6", f"PASS\nmerge-ready: feat/branch-only-ask {main0[:7]}..{x1[:7]}")
        st8 = {}
        out = m.merge_ready(TempCtx(st8, conn)) or ""
        check("a local marker reports, through the entrypoint's own SQL", c6[:10] in out and "PASSED" in out, out)
        check("a pulse row's marker is ignored (the watch's own report can't feed it)",
              f"f4 PASSed by abstractor-5 #{unreq_id}" in out and "PASSed by pulse" not in out, out)
        check("a foreign org's marker is ignored (introduced orgs write to seed)", c7[:10] not in out, out)
        check("REQUESTED via the real earlier-query → no flag", f"UNREQUESTED #{req_id}" not in out, out)
        check("UNREQUESTED via the real earlier-query (zero rows; a pulse row's mention is not a request)",
              f"UNREQUESTED #{unreq_id}" in out, out)
        rows = m._earlier(TempCtx({}, conn))(br_id, [x1[:7]], "feat/branch-only-ask")
        check("the real earlier-query marks a branch-only row by_sha=false (the SQL carries the evidence kind)",
              any(r["by_sha"] is False for r in rows) and all("by_sha" in r for r in rows), str(rows))
        check("a request naming only the BRANCH → REQUESTED (a3 BC-2; the live #29323 false flag)",
              f"feat/branch-only-ask PASSed by abstractor-6 #{br_id}" in out and f"#{br_id} by abstractor-6" not in out, out)
        check("the next run is silent (dedup)", m.merge_ready(TempCtx(st8, conn)) is None)
        m.REPO = TD                                      # not a repo: the checker is blind
        blind = m.merge_ready(TempCtx({}, conn)) or ""
        m.REPO = T
        check("a blind checker reports ONE 'UNVERIFIABLE' line and judges nothing",
              blind.count("UNVERIFIABLE") == 1 and "PASSED" not in blind, blind)
    finally:
        conn.close()
        _fx.__exit__(None, None, None)

m.Git.run = _orig_run
if fails:
    print(f"\nFAIL: {len(fails)} arm(s)")
    sys.exit(1)
if skips:
    print(f"\nSKIP (partial): {', '.join(skips)} — the rest passed")
    sys.exit(77)
print("\nALL PASS")
