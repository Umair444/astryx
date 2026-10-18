"""Authored mutants for bridges/gateway.py's pickup_task (plan-11324 S3c, a2 #60443: one inbound door), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_gateway_pickup.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "bridges/gateway.py"
ORACLE = REPO / "tests" / "test_gateway_pickup.py"
ENV = "GATEWAY_PICKUP_SRC"
TIMEOUT = 180

MUTANTS = {
    "PK1 pickup inserts what it collects itself again (past reach, the intent gate, the cap, the replay set)":
        ("                            res = await inbox(ctx, e)\n",
         "                            res = await pool.execute(\"INSERT INTO messages (from_agent, from_org, to_agent, "
         "to_org, intent, body, sig) VALUES ($1, $2, $3, 'local', $4, $5, $6)\", str(e.get('from')).partition('@')[0], "
         "p['org'], str(e.get('to')).partition('@')[0], str(e.get('intent')), str(e.get('body')), e.get('sig'))\n"),
    "PK2 a polled peer may deliver another peer's envelope":
        ('                        if isinstance(e, dict) and str(e.get("from", "")).partition("@")[2] == p["org"]:\n',
         '                        if isinstance(e, dict):\n'),
    "PK3 our own 429 settles the envelope (the watermark passes it: dropped at the peer)":
        ("                                break            # our own cap", "                                pass             # our own cap"),
}
