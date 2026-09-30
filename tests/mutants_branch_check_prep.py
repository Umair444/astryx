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
        ("    keep = {f\"{prefix}{k}\" for k in keep} | {name}", "    keep = {name}"),
    "B3 the eviction regex is unanchored at the END (a longer name is evicted)":
        ('(f"^{prefix}[0-9a-f]{{12}}$", list(keep))', '(f"^{prefix}[0-9a-f]{{12}}", list(keep))'),
    "B16 the eviction regex is unanchored at the START (a foreign name containing ours is evicted: seed #34141)":
        ('(f"^{prefix}[0-9a-f]{{12}}$", list(keep))', '(f"{prefix}[0-9a-f]{{12}}$", list(keep))'),
    "B17 evict=False is ignored (a concurrent run's template is dropped mid-run)":
        ("    if evict:\n", "    if True:\n"),
    "B18 the prefix isn't checked (a regex metacharacter reaches the eviction pattern)":
        ('    if not re.fullmatch(r"[a-z0-9_]+", prefix):', "    if False:"),
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
    "B10 a member whose check errors is SKIPPED, not accused":
        ("            bad.append(f\"{n} (unevaluable)\")", "            pass"),
    "B11 a 'KEY:param' exemption widened to the WHOLE key (the AUTOREMOTE drift a3 found)":
        ("ENV_ALLOW = tuple(sorted(k for k in secretset.NOT_SECRET if \":\" not in k))",
         "ENV_ALLOW = tuple(sorted({k.split(\":\")[0] for k in secretset.NOT_SECRET}))"),
    "B12 the extension template is born OPEN (connectable before its REVOKE)":
        ("        conn.execute(sql.SQL(\"CREATE DATABASE {} ALLOW_CONNECTIONS false\").format(sql.Identifier(name)))",
         "        conn.execute(sql.SQL(\"CREATE DATABASE {}\").format(sql.Identifier(name)))"),
    "B7 the admin password stays in the pg_dump argv conninfo":
        ("    pw = d.pop(\"password\", None)", "    pw = d.get(\"password\")"),
    "B15 the cached template never gets ag_catalog USAGE (the run role can't see cypher)":
        ("        t.execute(AGE_USAGE)\n", "        pass\n"),
    "B19 every live branch is fetched, not just main and the side's sha (another agent's unpushed work arrives)":
        ('    run("fetch", "-q", "--no-tags", f"file://{live}", *refs)',
         '    run("fetch", "-q", "--no-tags", f"file://{live}", *refs, "+refs/heads/*:refs/remotes/live/*")'),
    "B20 the history scan skips commit MESSAGES (a3 C2b: a pasted DSN is readable and unscanned)":
        ("        if cur and any(f in line for f in forms):", "        if cur and not in_msg and any(f in line for f in forms):"),
    "B21 the history scan reads messages only, no diffs (a credential added then deleted is missed)":
        ('    p = subprocess.Popen(["git", "log", "--all", "-p", "--text",', '    p = subprocess.Popen(["git", "log", "--all", "--text",'),
}
