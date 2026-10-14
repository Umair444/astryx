"""Mutants for the S1b-2b bridge half, bridges/common.py's wire_insert (plan-9139): ways a tier route's inbound text
could reach the raw row. The oracle is tests/test_release_ingress.py."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "bridges" / "common.py"
ORACLE = REPO / "tests" / "test_release_ingress.py"
ENV = "BRIDGE_COMMON_SRC"
MUTANTS = {
    "B1 a malformed tier declaration takes today's raw path":
        ("            tiered = True                      # a malformed declaration",
         "            tiered = False                     # a malformed declaration"),
    "B2 the quoted reply's text stays in delivery":
        ("    quoted = meta.pop(\"reply_to_body\", \"\") or \"\"\n", "    quoted = meta.get(\"reply_to_body\", \"\") or \"\"\n"
         "    _INGRESS_META = (*globals()[\"_INGRESS_META\"], \"reply_to_body\")\n"),
    "B3 the row goes to an agent other than the route's (here the @mention's)":
        ("from_agent, from_org, route.get(\"agent\"), thread", "from_agent, from_org, \"seed\", thread"),
    "B4 a refusal falls back to the raw row":
        ("        out = \"[tier-routed message withheld: \" + type(e).__name__ + \"]\"\n",
         "        out = body\n"),
}
