"""Authored mutants for bridges/gateway.py's cog DOORS (plan-11324 S3e 2/n), oracle tests/test_fed_doors.py (DB-free).

    venv/bin/python devtools/mutation_probe.py tests/mutants_fed_doors.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "bridges" / "gateway.py"
ORACLE = REPO / "tests" / "test_fed_doors.py"
ENV = "FED_GATEWAY_SRC"
TIMEOUT = 120
MUTANTS = {
    "W1 an envelope addressed to another org lands at whichever door it was posted to (no addressed_to)":
        ("    if ctx.org is not None and not node.addressed_to(e, ctx.name):\n", "    if False:\n"),
    "W2 the registry's door is ignored: the bare root of a cog serves nobody":
        ("    return next((x for x in c.values() if x.org == _DOOR), None) if _DOOR else None", "    return None"),
    "W3 the bare root serves an org that is NOT the door":
        ("if x.org == _DOOR), None)", "if x.org != _DOOR), None)"),
    "W4 one org grows /o/ doors (its paths no longer byte for byte today's)":
        ("    return route(name) if ESTATE is None else None\n", "    return route(name)\n"),
    "W5 /o/<X>/astryx/inbox lands at the root's org, not X's":
        ("    ctx = at(name)\n    return await inbox(", "    ctx = root()\n    return await inbox("),
    "W6 the intro cap counts per org: one IP gets INTRO_RATE hellos at EVERY org of the cog":
        ('        return Response(status_code=429)\n    try:\n        d = await request.json()\n    except Exception:\n'
         '        return Response(status_code=400)\n    ctx = at(name)',
         '        pass\n    try:\n        d = await request.json()\n    except Exception:\n'
         '        return Response(status_code=400)\n    ctx = at(name)'),
    "W7 a cog org advertises the install's bare base, not its /o/<X> url":
        ('url=node.public_url(e.get("ASTRYX_URL", ""), name, True),', 'url=e.get("ASTRYX_URL", ""),'),
    "W8 the agent is read from the LAST '@' side (the org), not through split_to":
        ('node.split_to(e["to"])[0] if ctx.org', 'e["to"].rpartition("@")[2] if ctx.org'),
    "W9 one org enforces the address too (a `to` with no '@', today's legal reading, refused)":
        ("    if ctx.org is not None and not node.addressed_to(e, ctx.name):\n",
         "    if not node.addressed_to(e, ctx.name):\n"),
    "W10 /o/<X>/astryx/pickup serves the root's org, not X's":
        ("    ctx = at(name)\n    return await pickup(", "    ctx = root()\n    return await pickup("),
    "W11 a cog's relay host is dropped: the door's ASTRYX_RELAY_HOST=1 mounts nothing (the 10-19 live gap)":
        ("               relay_host=host, relay_reach_private", "               relay_host=False, relay_reach_private"),
    "W12 a NON-door org may host the relay (its /relay/* would be served as the door's bare root)":
        ("    if host and org != orgs.door():\n", "    if False:\n"),
    "W13 the relay mounts on one org only again (a cog's door never hosts)":
        ("    _ONE = root()                       # one org", "    _ONE = root() if ESTATE is not None else None  # one org"),
    "W14 the relay reads the cog's FIRST org's database, not the door's":
        ("        lambda: _ONE.pool, org_ok,", "        lambda: next(iter(cog().values())).pool, org_ok,"),
    "W15 a new _env key spelled with single quotes reaches the checkout .env unset (a2 #61438 A-1)":
        ('RELAY_BACKOFF = float(_env("ASTRYX_RELAY_BACKOFF", "60"))', "RELAY_BACKOFF = float(_env('ASTRYX_PROBE_X', \"60\"))"),
    "W16 an _env key held in a name, not a literal, is unseen":
        ('RELAY_BACKOFF = float(_env("ASTRYX_RELAY_BACKOFF", "60"))',
         'RELAY_BACKOFF = float(_env(_K := "ASTRYX_PROBE_Y", "60"))'),
    "W17 _env passed on as a value (the read happens through another name)":
        ('RELAY_BACKOFF = float(_env("ASTRYX_RELAY_BACKOFF", "60"))',
         'RELAY_BACKOFF = float((lambda f: f("ASTRYX_PROBE_Z", "60"))(_env))'),
}
