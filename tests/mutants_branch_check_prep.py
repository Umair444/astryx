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

TIMEOUT = 600          # the oracle takes ~200 s (10-09); the 120 s default SIGKILLed it mid-run
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
    "B11 ENV_ALLOW re-widened to every whole-key non-secret (the pre-BC-2 set: live values enter the sandbox)":
        ("ENV_ALLOW = ()\n", "ENV_ALLOW = tuple(sorted(k for k in secretset.NOT_SECRET if \":\" not in k))\n"),
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
    "B20 the history scan skips COMMIT objects (a3 C2b: a DSN pasted into a message is readable and unscanned)":
        ("        if any(f in body for f in forms):", "        if typ != \"commit\" and any(f in body for f in forms):"),
    "B21 the history scan skips BLOBS (a credential added then deleted, or put in by a merge resolution, is missed)":
        ("        if any(f in body for f in forms):", "        if typ != \"blob\" and any(f in body for f in forms):"),
    "B22 provenance EXEMPTS a live oracle's test DB (a reachable open DB passes P0-b)":
        ("        if n in own_templates or t is True:", "        if n in own_templates or t is True or \"LIVE pid\" in provenance(n):"),
    "B23 a test DB gets a REVOKE suggestion too (revoking a live oracle's open DB breaks its arm)":
        ('    rest = [b.split(" (")[0] for b, why in test if not why]', '    rest = [b.split(" (")[0] for b, why in test]'),
    "B24 provenance ignores liveness (every test DB reads LIVE, debris is never named)":
        ("    if _pid_alive(pid):\n        return f\"a test DB of LIVE", "    if True:\n        return f\"a test DB of LIVE"),
    "B25 the names-mode scan still filters datallowconn (the oracle's closed decoys go unjudged)":
        ('            "WHERE d.datname = ANY(%s) AND r.rolname <> %s ORDER BY 1"', '            "WHERE d.datallowconn AND d.datname = ANY(%s) AND r.rolname <> %s ORDER BY 1"'),
    "B26 the prep oracle's wakeprobe isn't a TEST_DB (a killed oracle's wakeprobes leak forever: a2 F2)":
        ('                     r"|astryx_hardenprobe_[abc]_|astryx_wakeprobe_)(\\d+)$"', '                     r"|astryx_hardenprobe_[abc]_)(\\d+)$"'),
}
