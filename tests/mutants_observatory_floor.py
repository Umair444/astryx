"""Mutants for observatory/api/main.py's floor routes, /api/influence and /api/cog (seed #60078, goal 11324). The
oracle is tests/test_observatory_floor.py, which loads OBS_MAIN_SRC in place of the real main.py.

Not listed, on purpose: dropping either route's own x-obs-key check. As with /api/thread/read, neither path is in
PUBLIC_PATHS, so the central default-deny gate answers a keyless call 403 before the route runs; the route's check is
a second guard, and the GATE arms pin the 403 either way."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "observatory" / "api" / "main.py"
ORACLE = REPO / "tests" / "test_observatory_floor.py"
ENV = "OBS_MAIN_SRC"
MUTANTS = {
    "F1 the coverage floor is dropped (a kind measured on 40% of its domain draws edges)":
        ("    w = _influence.kind_weights(cov)\n", "    w = {k: 1.0 for k in _influence.KINDS}\n"),
    "F2 no decay (a 60-day edge weighs what yesterday's does)":
        ('_influence.view("floor", w, {})', '_influence.view("floor", w, {}, half_life_days=1e9)'),
    "F3 a pair's edges don't sum (the last one wins)":
        ("pair[(s, d)] = pair.get((s, d), 0.0) + x", "pair[(s, d)] = x"),
    "F4 the ranks mix compute runs (every snapshot, not the latest)":
        ('"AND computed_at = (SELECT max(computed_at) FROM influence_value "',
         '"AND computed_at >= (SELECT min(computed_at) FROM influence_value "'),
    "F5 the ranks are not ordered by value":
        ('INFLUENCE_VALUES_SQL + " ORDER BY value DESC, agent"', 'INFLUENCE_VALUES_SQL + " ORDER BY agent"'),
    "F6 an edge carries its topic out":
        ('[{"src": s, "dst": d, "w": round(x, 6)} for (s, d), x in sorted(pair.items())]',
         '[{"src": s, "dst": d, "w": round(x, 6), "topic": [r["kind"] for r in rows]} for (s, d), x in sorted(pair.items())]'),
    "F7 a registry that refuses reads as a cog of one (fails open)":
        ("    except orgs.RegistryError:\n        return Response(status_code=500)\n",
         "    except orgs.RegistryError:\n        reg = None\n"),
    "F8 no room is marked as ours":
        ('"this": o == me,', '"this": False,'),
    "F9 a room carries its org's HOME out":
        ('"badge": badge if o == me else None}', '"badge": badge if o == me else None, "home": str(reg[o]["home"])}'),
    "F10 the badge is not the gateway's key":
        ('badge = (ident.get("pubkey") or "")[:8] or None', 'badge = None'),
}
