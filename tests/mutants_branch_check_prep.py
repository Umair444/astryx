"""Authored mutants for nucleus/branch_check_prep.py (plan-4918 P0/P1), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_branch_check_prep.py

One per safety property: the NULL-ACL precondition, the template keep set and LIKE escape, the template's
PUBLIC CONNECT revoke, the credential-bearing file skip, the generated env's allowlist, and the password kept
off argv.
NOT authored (declared): a wildcard prefix match (the old B9). TRANSIENT now pairs startswith with a strict
per-class regex, so a lookalike that a wildcard admitted fails the regex and is accused as "no parseable creator
pid": an equivalent mutant BY CONSTRUCTION (two fences), not by data.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "branch_check_prep.py"
ORACLE = REPO / "tests" / "test_branch_check_prep.py"
ENV = "BRANCH_CHECK_PREP_SRC"

MUTANTS = {
    "B1 P0-b reads datacl TEXT, so a NULL (default) ACL passes vacuously":
        ("            if conn.execute(\"SELECT has_database_privilege('public', %s, 'CONNECT')\", (n,)).fetchone()[0]:",
         "            if conn.execute(\"SELECT d.datacl::text LIKE '%%=c/%%' FROM pg_database d WHERE d.datname = %s\", (n,)).fetchone()[0]:"),
    "B2 eviction ignores the keep set (the two sides evict each other)":
        ("    keep = {f\"{TPL_PREFIX}{k}\" for k in keep} | {name}", "    keep = {name}"),
    "B3 LIKE unescaped ('_' matches any char: a lookalike is evicted)":
        ("(TPL_PREFIX.replace(\"_\", \"\\\\_\") + \"%\", list(keep))", "(TPL_PREFIX + \"%\", list(keep))"),
    "B4 the template keeps PUBLIC CONNECT":
        ("        conn.execute(sql.SQL(P0A).format(sql.Identifier(name)))\n", ""),
    "B5 a credential-bearing estate file is copied anyway":
        ("            if carries_secret(f, secrets_):\n", "            if False:\n"),
    "B6 the generated env copies every live key, not the allowlist":
        ("[f\"{k}={live_env[k]}\" for k in ENV_ALLOW if k in live_env]", "[f\"{k}={v}\" for k, v in live_env.items() if k != \"ASTRYX_DSN\"]"),
    "B8 the human-personal tier is COPIED into the run, not linked":
        ("        if rel.split(\"/\")[0] in PRIVATE_TIER:\n", "        if False:\n"),
    "B14 a transient prefix is re-added (pid-keyed exemption under --unshare-pid)":
        ("TRANSIENT = {}      # EMPTY", "TRANSIENT = {\"astryx_wakeprobe_\": (re.compile(r\"^astryx_wakeprobe_(\\d+)$\"), \"x\")}      # EMPTY"),
    "B7 the admin password stays in the pg_dump argv conninfo":
        ("    pw = d.pop(\"password\", None)", "    pw = d.get(\"password\")"),
}
