#!/usr/bin/env python3
"""Oracle for mcp/memory/server.py window() — the synthesis-context span picker (goal 3438
item-1 follow-on, memory msg 17231). HERMETIC: a synthetic page, no DB, no memory estate.

THE DEFECT (memory reproduced it live on verification.md, 26.8k chars): window() picked the
span with the most raw query-token HITS, counting every token equally — so stopwords
(what/is/the) and page-wide generics swamp the rare discriminators (red/before/green) and the
window lands on a stopword-dense decoy, excluding the answer-bearing section retrieval ranked
the page #1 for. FIX: weight each hit by rarity (1/page_freq), so the span with the most
rare-discriminator MASS wins. Rarity subsumes stopword-stripping — a stopword appearing 200×
gets weight ~0.005 with no hardcoded list, and it also demotes page-SPECIFIC generics a global
stoplist would miss.

The fixture is built so the two behaviours DISAGREE: the answer cluster carries the rare
discriminator ('frobnicate', once) at the page head; a far decoy span is packed with the common
query term ('widget', many) so it wins on raw COUNT but not on rarity MASS. The invariant — the
returned window contains the rare discriminator — is RED against count-based selection and GREEN
against rarity-weighted. Pure stdlib; run by check.sh.
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SD = REPO / "mcp" / "memory"
sys.path.insert(0, str(SD))


def skip(m):
    print(f"SKIP: {m}")
    sys.exit(77)


try:
    spec = importlib.util.spec_from_file_location("memask_server", SD / "server.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
except Exception as e:                                              # noqa: BLE001
    skip(f"{type(e).__name__}: {e} — the window oracle needs the ask server importable")

fails = []


def want(label, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        fails.append(label)


# ── fixture: a UNIQUE rare term at the head vs a far decoy PACKED with a common query term ──
# The rarity math guarantees the disagreement independent of tuning: the answer window carries
# frobnicate(weight 1/1=1.0) + one widget, mass = 1 + 1/(N+1); the decoy carries N widgets,
# mass = N/(N+1) < 1. Answer always wins on MASS (margin 2/(N+1) > 0) but always LOSES on raw
# COUNT (2 hits vs N) — so count-based excludes the rare term and rarity-weighted captures it.
RARE = "frobnicate"            # the discriminator — appears EXACTLY once, in the answer
COMMON = "widget"             # the common query term — packed into the decoy (wins on count)
QUERY = f"{RARE} {COMMON}"
N = 60

answer = f"Intro {RARE} {COMMON} defines the core mechanism here. "     # head: rare term lives here
# neutral filler carrying NO query token, long enough to push the decoy past one window width
filler = ("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi "
          "omicron rho sigma tau upsilon phi ") * 40
decoy = (COMMON + " ") * N                                             # N common terms, NO rare term
page = answer + filler + decoy + " coda finis terminus "

assert len(page) > 2400, "fixture must exceed one window width"
assert page.count(RARE) == 1, "rare term must be unique (its whole point)"

w = S.window(page, QUERY)
decoy_at, rare_at = page.find(COMMON + " " + COMMON), page.find(RARE)
print(f"page len {len(page)} | RARE@{rare_at} | decoy@{decoy_at} | N={N}")
# THE INVARIANT: the window must carry the rare discriminator, not the count-winning decoy.
want("window captures the rare discriminator (not the common-term decoy)", RARE in w)
# non-vacuous: the decoy sits beyond one window from the answer, so a wrong pick EXCLUDES the rare term
want("fixture is discriminating (decoy span sits beyond one window from the answer)",
     decoy_at - rare_at > 2400)
# a page shorter than the window is returned whole (unchanged contract)
short = f"a short page mentioning {RARE} and {COMMON}"
want("short page (<= width) returned whole", S.window(short, QUERY) == short)
# a query with no page term falls back to the head, never crashes
want("no-match query falls back to head", S.window(page, "zzz nomatch qqq")[:10] == page[:10])

print()
if fails:
    print(f"test_memory_window: {len(fails)} FAIL — {fails}")
    sys.exit(1)
print("test_memory_window: ALL PASS — window() lands on the rare-discriminator mass, not raw hit count")
sys.exit(0)
