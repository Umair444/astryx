"""Hermetic test of the ONE content-tier authority (nucleus/tier.py) — the grade-3
floor for plan-18 LANE 2. Proves the LOAD-BEARING invariant against a real temp
agents/ tree: an agent's content is public ONLY IF every grant it holds is a known
org-actuation grant; ANY grant outside the positive allowlist — a known PII grant OR
an UNKNOWN/NEW one — floors it to private. This is the polarity that, if it regressed
to a PII denylist, would leak the next new grant. That regression is exactly what
this test catches.

Run: venv/bin/python nucleus/test_tier.py   (also collected by pytest).
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
