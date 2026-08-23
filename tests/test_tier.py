"""Hermetic test of the ONE content-tier authority (nucleus/tier.py) — the grade-3
floor for plan-18 LANE 2. Proves the LOAD-BEARING invariant against a real temp
agents/ tree: an agent's content is public ONLY IF every grant it holds is a known
org-actuation grant; ANY grant outside the positive allowlist — a known PII grant OR
an UNKNOWN/NEW one — floors it to private. This is the polarity that, if it regressed
to a PII denylist, would leak the next new grant. That regression is exactly what
this test catches.

Run: venv/bin/python tests/test_tier.py   (also collected by pytest).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleus.tier import is_content_public, content_public_agents, ORG_ACTUATION_GRANTS  # noqa: E402


def _tree(grants_by_agent: dict) -> Path:
    """A temp agents/ tree; grants_by_agent maps name -> Grants: line value (or None
    for no Grants line at all)."""
    d = Path(tempfile.mkdtemp()) / "agents"
    d.mkdir()
    for name, grants in grants_by_agent.items():
        p = d / name / f"{name}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        body = f"# {name}\n"
        if grants is not None:
            body += f"Grants: {grants}\n"
        p.write_text(body)
    return d


def test_no_grants_is_public():
    d = _tree({"seed": None, "forge": None})
    assert is_content_public("seed", d)
    assert is_content_public("forge", d)


def test_org_actuation_only_is_public():
    d = _tree({"memory": "compose", "poster": "channels", "both": "compose, channels"})
    assert is_content_public("memory", d)
    assert is_content_public("poster", d)
    assert is_content_public("both", d)


def test_any_pii_grant_is_private():
    d = _tree({"canopus": "gmail, contacts, geoloc, browser",
               "gemini": "geoloc, contacts",
               "mixed": "compose, gmail"})   # one PII grant among actuation ones ⇒ private
    assert not is_content_public("canopus", d)
    assert not is_content_public("gemini", d)
    assert not is_content_public("mixed", d)


def test_unknown_or_new_grant_defaults_private():
    # THE fail-closed invariant: a grant nobody has classified must default private,
    # so a future capability can't silently make content public. If this ever flips,
    # the authority has been inverted to a denylist — the leak this test exists to stop.
    assert "calendar" not in ORG_ACTUATION_GRANTS and "sms" not in ORG_ACTUATION_GRANTS
    d = _tree({"future": "calendar", "future2": "compose, drive"})
    assert not is_content_public("future", d)
    assert not is_content_public("future2", d)


def test_unknown_agent_is_private():
    d = _tree({"seed": None})
    assert not is_content_public("ghost-departed", d)   # no charter ⇒ private


def test_content_public_agents_is_positive_subset():
    d = _tree({"seed": None, "memory": "compose",
               "canopus": "gmail", "future": "calendar"})
    pub = content_public_agents(["seed", "memory", "canopus", "future", "ghost"], d)
    assert pub == {"seed", "memory"}                    # private + unknown excluded


# ---------------------------------------------------------------- COVERAGE (plan-18)
# Everything above proves the tier AUTHORITY behaves. This section proves the authority
# is actually REACHED by every anonymous path that can carry a message — a different
# question, and the one that was live-leaking for four hours on 2026-08-12.
#
# WHAT HAPPENED: the anonymous-visibility rule was written TWICE — as SQL in
# /api/messages and as Python in /api/events' visible(). Seed fixed the SQL copy; the
# Python copy kept the old rule and every WhatsApp/Discord/Telegram message kept pushing
# with full body to any anonymous SSE client. The comment at the top of PUBLIC_PATHS
# NAMED both paths, and a comment cannot fail a build.
#
# WHY THIS IS A COVERAGE CHECK AND NOT ANOTHER CONFORMANCE ONE (abstractor-4's spec):
# the path list is ENUMERATED FROM PUBLIC_PATHS in the real source, never hand-written
# here. A fourth anonymous path added later is caught BY CONSTRUCTION — nobody has to
# remember to extend a list. A check that derives its own subject from a hand-list can
# only ever prove conformance for the members somebody remembered.
#
# AND IT MATCHES CALLS, NOT TEXT. The first draft of this assert grepped the handler
# source for "anonymous_can_see" and passed /api/messages — on the strength of a COMMENT
# mentioning the function. That is the same defect this file exists to catch, committed
# inside the catcher: the check could not observe the thing it claimed to cover. It now
# walks the AST for an actual Call node.
import ast  # noqa: E402
import re   # noqa: E402

MAIN_PY = Path(__file__).resolve().parent.parent / "observatory" / "api" / "main.py"
# The shared ROOT the rule's content lives in. Authorities are DISCOVERED as the
# functions that derive from it — never a hard-coded name list here, because a name
# list is the same hand-kept-set defect one level up, and it would have to be edited
# every time a rendering is added. First version of this check DID hard-code
# "anonymous_can_see" and went red on correct code the moment the sanctioned
# `anonymous_can_see_sql` sibling appeared: the assert was narrower than its own design.
RULE_ROOT = "ANON_PEER_COLUMNS"
PERSONAL_ORGS = ("whatsapp", "discord", "telegram")   # local.md human-personal tier


def _main_ast():
    src = MAIN_PY.read_text()
    return src, ast.parse(src)


def _public_paths(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(
                getattr(t, "id", None) == "PUBLIC_PATHS" for t in n.targets):
            return {e.value for e in n.value.elts if isinstance(e, ast.Constant)}
    raise AssertionError("PUBLIC_PATHS not found in main.py — the allowlist moved or "
                         "was renamed; this check is blind until it is re-pointed")


def _public_handlers(src, tree):
    """(path, method, funcnode) for every route registered on a PUBLIC_PATHS path."""
    pub = _public_paths(tree)
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)):
                continue
            if getattr(d.func.value, "id", None) != "app":
                continue
            if d.args and isinstance(d.args[0], ast.Constant) and d.args[0].value in pub:
                out.append((d.args[0].value, d.func.attr, n))
    return out


def _calls(node, name) -> bool:
    """A real Call to `name` — not the name appearing in a comment or a docstring."""
    return any(isinstance(c, ast.Call) and
               (getattr(c.func, "id", None) == name or
                getattr(c.func, "attr", None) == name)
               for c in ast.walk(node))


def _carries_message_content(node) -> bool:
    """Does this handler hand message ROWS/BODIES to the caller (vs counting them)?"""
    if _calls(node, "msg"):                       # the message row serializer
        return True
    for c in ast.walk(node):                      # an SSE path filtering event types
        if isinstance(c, ast.Constant) and c.value == "message":
            return True
    return False


def _authorities(tree):
    """Every module-level function that DERIVES from the shared rule root.

    Discovered structurally, so the check follows a rename and admits a new rendering
    (python predicate, SQL emitter, a future one) without being edited — while a
    function that merely restates the rule in its own words is NOT an authority and
    cannot satisfy the coverage assert."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                isinstance(x, ast.Name) and x.id == RULE_ROOT for x in ast.walk(n)):
            out.add(n.name)
    return out


def test_the_rule_has_one_root_with_more_than_one_rendering():
    """The collapse is real: the rule's CONTENT lives in one constant, and the
    renderings derive from it rather than from each other."""
    src, tree = _main_ast()
    assert any(isinstance(n, ast.Assign) and
               any(getattr(t, "id", None) == RULE_ROOT for t in n.targets)
               for n in ast.walk(tree)), f"{RULE_ROOT} is gone — this check is blind"
    auth = _authorities(tree)
    assert len(auth) >= 2, (
        f"expected >=2 renderings deriving from {RULE_ROOT}, found {auth or 'none'} — "
        "if a rendering stopped deriving from the root it is restating the rule again")


def test_public_paths_are_enumerable():
    # If this fails, every assert below is silently checking nothing.
    src, tree = _main_ast()
    pub = _public_paths(tree)
    assert "/api/messages" in pub and "/api/events" in pub, pub
    assert _public_handlers(src, tree), "no public route handlers resolved"


def test_every_anonymous_message_path_routes_through_the_authority():
    """THE coverage assert. Enumerated from PUBLIC_PATHS, so a path added later is
    covered without anyone extending a list here."""
    src, tree = _main_ast()
    auth = _authorities(tree)
    offenders = []
    for path, method, fn in _public_handlers(src, tree):
        if method != "get":                # POST/PUT carry their own key gate, not a read surface
            continue
        if not _carries_message_content(fn):
            continue
        if not any(_calls(fn, a) for a in auth):
            offenders.append(f"{method.upper()} {path} (line {fn.lineno})")
    assert not offenders, (
        "anonymous message-bearing path(s) that call no rendering of the visibility "
        "rule (authorities deriving from " + RULE_ROOT + ": " + ", ".join(sorted(auth))
        + "): " + "; ".join(offenders) + ". Each such path re-expresses the rule in its "
        "own words, which is the two-writer defect that leaked the personal tier to the "
        "live SSE stream on 2026-08-12. Route it through an authority.")


# Owner-tier SOURCES — artifacts whose CONTENT is the owner's private material.
# NOT `nucleus.tier`: that is the AUTHORITY, the classifier that decides what may be shown,
# and a public handler importing it is doing the right thing. The first draft of this list
# said ("people", "tier") and immediately flagged GET /api/agents for importing
# `is_content_public` — which would have driven a "fix" REMOVING the very gate that keeps
# that path safe. A false predicate attached to a real gap, inverting on the one case that
# matters most. Source and authority are opposites here; the word is the same.
TIER_SOURCE_PATTERNS = (
    r"['\"]tier/",                                  # the tier/ artifact directory
    r"\bfrom\s+nucleus\s+import\s+people\b",         # the people cache module
    r"\bnucleus\.people\b",
    r"people-graph",
)


def test_no_public_path_reads_an_owner_tier_source():
    """SIBLING COVERAGE ASSERT — TIER-BEARING IS NOT THE SAME AS MESSAGE-BEARING, and the
    assert above only sees the second.

    Found 2026-08-14 by probing a NEW surface rather than re-reading this file: seed shipped
    a People lens over `tier/people-graph.json` — 736 contacts with display names. It is
    correctly owner-gated (verified live: /api/people and /api/people/graph both 403 to
    anonymous). But `_carries_message_content` looks for the message serializer or the
    "message" event constant, so a handler serving PEOPLE returns False, is skipped, and the
    coverage assert above would have passed it silently had anyone added it to PUBLIC_PATHS.

    The gap is structural rather than an oversight: that assert was built from the SSE
    incident, so its subject is message bodies. The org has since grown tier-bearing surfaces
    that carry no messages at all, and nothing in check.sh would catch one being routed
    publicly. This closes that, narrowly and by derivation — a handler that reads an
    owner-tier SOURCE must not sit on a PUBLIC_PATHS route.

    Names are not a regex, so no scanner can police this content
    ([[project_people_graph_tier_surface]]). Placement IS the protection, which is exactly
    why it needs a standing assert rather than a discipline someone remembers."""
    src, tree = _main_ast()
    offenders = []
    for path, method, fn in _public_handlers(src, tree):
        seg = ast.get_source_segment(src, fn) or ""
        for pat in TIER_SOURCE_PATTERNS:
            if re.search(pat, seg):
                offenders.append(f"{method.upper()} {path} reads an owner-tier source "
                                 f"(/{pat}/, line {fn.lineno})")
                break
    assert not offenders, (
        "PUBLIC_PATHS route(s) reading an owner-tier source: " + "; ".join(offenders)
        + ". Owner-tier content is not detectable by pattern — a contact's name is "
        "indistinguishable from any other word — so PLACEMENT is the only protection and a "
        "public route over it cannot be walked back. Gate the path, or serve a meta-shape.")


def test_internal_traffic_is_not_anonymously_visible():
    """PINS THE PREDICATE A STANDING RULING DEPENDS ON — `local` ↔ `local` must be False.

    Added 2026-08-15. I declined to add `dc:`/`tg:` surface-address patterns to pii_sweep on
    REACH rather than count: those ids live in internal agent traffic, and internal traffic is
    not anonymously visible, so 45 true-but-routine flags a month would buy nothing. gemini
    then tested the load-bearing half rather than accepting it — I had measured reach at
    `/api/messages`, which is ONE of two anonymous message-bearing paths, and `/api/events`
    had drifted from this very predicate once before.

    It holds, and for a better reason than checking twice: both paths now call one authority,
    so the question is a property of a single function rather than a per-endpoint survey.
    gemini's improvement to the trip condition follows from that — **if this predicate ever
    returns True for local↔local, every anonymous path changes at once and the pii_sweep
    ruling flips on its own terms.**

    Which is exactly why it needs an ASSERT rather than a note: a trip condition nobody
    evaluates is a discipline someone must remember. The sibling test below pins the personal
    CHANNEL orgs; nothing pinned internal traffic, so the ruling rested on an unguarded fact.
    Asserted under BOTH an empty and a populated peer set, because federation visibility is
    peer-dependent and internal visibility must not be."""
    sys.path.insert(0, str(MAIN_PY.parent.parent.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("_obs_main_internal", MAIN_PY)
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except BaseException:
        print("SKIP: observatory main.py not importable here (no .env) — internal-visibility "
              "predicate was NOT verified this run")
        sys.exit(77)
    for peers in (frozenset(), frozenset({"partnerorg"})):
        assert mod.anonymous_can_see("local", "local", peers) is False, (
            "INTERNAL AGENT TRAFFIC IS ANONYMOUSLY VISIBLE. Every dc:/tg: channel id, every "
            "thread reference and every internal deliberation is now public. This also FLIPS "
            "a standing ruling: pii_sweep declined surface-address patterns because these ids "
            "had no anonymous reach — that premise is gone, so add them.")
        # federation stays visible; the two must not be collapsed into one rule
        assert mod.anonymous_can_see("local", "partnerorg", frozenset({"partnerorg"})) is True


def test_authority_denies_the_personal_channel_orgs():
    """The rule itself: personal channels are never anonymous-visible, whatever the
    peer set says. Guards the inversion (a denylist that forgets a channel) AND the
    pathological case of an org introduced under a channel's own name."""
    sys.path.insert(0, str(MAIN_PY.parent.parent.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("_obs_main_probe", MAIN_PY)
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except BaseException:
        # BaseException, not Exception, and that distinction is the whole arm: main.py:53
        # does `raise SystemExit("no ASTRYX_DSN ...")` at import time, and SystemExit does
        # NOT inherit from Exception. So on any machine without a .env — every CI runner,
        # every fresh clone — the fallback below was unreachable and this oracle died
        # instead of degrading. check.sh then went RED on correct code, which would have
        # made the .github workflows red on arrival. Found by checking out the index into
        # a temp dir and running check.sh there, which is the only way to see what a clean
        # clone sees. Fall back to proving the SHAPE.
        src, tree = _main_ast()
        auth = _authorities(tree)
        assert auth, "no rendering derives from " + RULE_ROOT
        for name in auth:
            fn = next(n for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.name == name)
            assert RULE_ROOT in (ast.get_source_segment(src, fn) or "")
        return
    for org in PERSONAL_ORGS:
        assert not mod.anonymous_can_see(org, "local", frozenset()), org
        assert not mod.anonymous_can_see("local", org, frozenset()), org


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  ✗ {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
