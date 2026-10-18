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
    "F1 the coverage floor is ignored (a kind measured on 40% of its domain reads measured)":
        ('"measured": w[k] > 0,', '"measured": True,'),
    "F2 the window is ignored (7d draws a 10-day edge)":
        ("AND ts >= now() - make_interval(days => $1)", "AND $1::int > 0"),
    "F3 a pair's edges aren't counted (each one reads n=1)":
        ('        e["n"] += 1\n', '        e["n"] = 1\n'),
    "F4 the ranks mix compute runs (every snapshot, not the latest)":
        ('"AND computed_at = (SELECT max(computed_at) FROM influence_value "',
         '"AND computed_at >= (SELECT min(computed_at) FROM influence_value "'),
    "F5 the ranks are not ordered by value":
        ('''view = 'global') ORDER BY value DESC, agent")''', '''view = 'global') ORDER BY agent")'''),
    "F6 the top threads aren't capped at 3":
        ("key=lambda x: (-x[1], x[0]))[:3]]", "key=lambda x: (-x[1], x[0]))[:9]]"),
    "F7 a registry that refuses reads as a cog of one (unreachable fail-open: _env re-loads the registry and raises out of the route; caught as a 500 crash, not an arm, a4 #60129)":
        ('        return JSONResponse({"error": f"cog registry refused: {e}"}, status_code=500)\n', '        reg = None\n'),
    "F14 a kind's coverage comes from the window's rows (7d calls a kind unmeasured that the ranks weigh: a4 #60129 A-1)":
        ('    cov = {r["kind"]: r["coverage"] for r in await pool.fetch(INFLUENCE_COVERAGE_SQL)}\n',
         '    cov = {r["kind"]: r["coverage"] for r in rows}\n'),
    "F8 a backend in a cog names no room (its registry name is dropped)":
        ('me = None if reg is None else orgs.org_of(ESTATE)', 'me = None'),
    "F9 a backend lists its cog's other orgs (the front's job, #60439)":
        ('"orgs": [{"org": me, "name": me_name, "base": "/", "badge": badge}]}',
         '"orgs": [{"org": me, "name": me_name, "base": "/", "badge": badge}] + [{"org": o} for o in sorted(reg or {}) if o != me]}'),
    "F10 the badge is not the gateway's key":
        ('badge = (ident.get("pubkey") or "")[:8] or None', 'badge = None'),
    "F11 an unknown window is served (as the default) instead of 400":
        ("    if window not in INFLUENCE_WINDOWS:\n        return Response(status_code=400)\n",
         "    if window not in INFLUENCE_WINDOWS:\n        window = \"14d\"\n"),
    "F15 a registry that doesn't name our home answers as an unnamed room":
        ("    if reg is not None and me is None:", "    if False:"),
    "F12 a refused registry is a bare 500 (the floor can't say why)":
        ('JSONResponse({"error": f"cog registry refused: {e}"}, status_code=500)', 'Response(status_code=500)'),
    "F13 the kinds' coverage is dropped (an unmeasured kind can't say how close it is)":
        ('"coverage": cov.get(k),', '"coverage": None,'),
}
