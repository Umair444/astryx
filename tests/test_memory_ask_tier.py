#!/usr/bin/env python3
"""The SECOND wall for mcp/memory/server.py — an INDEPENDENT tier-boundary proof (goal 3410).

memory's graph resolvers (mcp/memory/resolvers.py) hide tier-private nodes by POSITIVE ADMIT:
corpus()/onehop() serve only nodes carrying admitted=true, so a Person / un-admitted node is
invisible by OMISSION. That is the FIRST wall, and it verifies itself. This oracle is the
second, and it shares NO computation with that gate: it plants a tier-private node carrying a
unique secret token, drives the REAL ask() end-to-end, and asserts the secret reaches NEITHER
the answer NOR the citations — a black-box data-flow proof on ask()'s literal output, not a
recomputation of the filter with the filter's own code.

Three arms, on a throwaway postgres+AGE graph (never the org's own):
  A · GATED (the property): ask() over an admitted page + a tier-private Person that SHARE the
      query terms → the secret appears nowhere in ask()'s output, AND the admitted page IS
      cited (non-vacuous: retrieval actually fired, so "absent" isn't "nothing matched").
  B · MUTATION / leak control (proves A has teeth): drop the admit gate (admit_filter="",
      both_admitted="") and re-run ask() → the secret NOW leaks. If removing the gate does not
      leak, A was proving nothing. This is the RED arm — seen fail before A's green is trusted.
  C · INDEPENDENT reachability (my own raw Cypher, no resolver code): the private node exists
      and its text carries the query terms, so absent the gate it is genuinely retrievable —
      establishing, without the emitter's functions, that the gate is the ONLY thing hiding it.

Synthesis is forced EXTRACTIVE (OpenAI key withheld): hermetic, deterministic, zero external
spend, and STRICTER — extractive quotes page text verbatim, so a leaked page shows its secret
literally rather than at an LLM's discretion. Throwaway DB only (role must CREATE DATABASE and
AGE must be installable), else SKIP 77. Run by check.sh.
"""
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO / "mcp" / "memory"
EXIT_SKIP = 77


def skip(m):
    print(f"SKIP: {m}")
    sys.exit(EXIT_SKIP)


# Import the REAL server by file path. Insert only mcp/memory (for its `import resolvers`);
# do NOT put REPO on sys.path — repo root carries a `mcp/` dir that would shadow the installed
# `mcp` package the server needs for FastMCP.
sys.path.insert(0, str(SERVER_DIR))
try:
    import psycopg
    spec = importlib.util.spec_from_file_location("memask_server", SERVER_DIR / "server.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
except Exception as e:                                              # noqa: BLE001
    skip(f"{type(e).__name__}: {e} — the tier oracle needs the org runtime + the ask server")

SECRET = "SECRETXYZLEAK"          # unique token; lives ONLY on the tier-private node
PUBLIC = "PUBLICMARKEROK"         # marker on the admitted page — proves the RIGHT page surfaced
QUERY = "restart the gateway service"

fails: list[str] = []


def want(label, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        fails.append(label)


# ── throwaway substrate ──────────────────────────────────────────────────────────────
def dsn():
    if os.environ.get("ASTRYX_DSN"):
        return os.environ["ASTRYX_DSN"].strip()
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ASTRYX_DSN="):
                return line[len("ASTRYX_DSN="):].strip().strip('"').strip("'")
    return None


ADMIN_DSN = dsn()
if not ADMIN_DSN:
    skip("no ASTRYX_DSN — no graph substrate")
try:
    admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=5)
except Exception as e:                                              # noqa: BLE001
    skip(f"database unreachable ({type(e).__name__})")
row = admin.execute("SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()
if not row or not row[0]:
    admin.close()
    skip("role cannot CREATE DATABASE — a throwaway is the only safe substrate")
age = admin.execute("SELECT 1 FROM pg_available_extensions WHERE name='age'").fetchone()
if not age:
    admin.close()
    skip("Apache AGE not installed in the cluster — cannot build a throwaway graph")

PROBE_DB = f"astryx_tierprobe_{os.getpid()}"
PROBE_DSN = re.sub(r"/[^/?]+(\?|$)", f"/{PROBE_DB}\\1", ADMIN_DSN, count=1)
if PROBE_DB not in PROBE_DSN:
    admin.close()
    skip("could not derive a throwaway DSN")


def cleanup():
    try:
        admin.execute(f'DROP DATABASE IF EXISTS "{PROBE_DB}" WITH (FORCE)')
    except Exception:                                              # noqa: BLE001
        pass
    admin.close()


def cy(cur, q):
    cur.execute("LOAD 'age';")
    cur.execute('SET search_path = ag_catalog, "$user", public;')
    cur.execute(f"SELECT * FROM cypher('memory', $cyq$ {q} $cyq$) AS (a agtype);")


def raw_nodes(cur):
    """MY OWN ungated read — no resolver code — to independently prove the private node is
    reachable/term-matched absent the gate (arm C)."""
    cur.execute("LOAD 'age';")
    cur.execute('SET search_path = ag_catalog, "$user", public;')
    cur.execute("SELECT * FROM cypher('memory', $q$ MATCH (n) RETURN labels(n)[0], "
                "coalesce(n.text,'') $q$) AS (kind agtype, text agtype);")
    return [(str(k).strip('"'), str(t).strip('"')) for k, t in cur.fetchall()]


try:
    admin.execute(f'DROP DATABASE IF EXISTS "{PROBE_DB}" WITH (FORCE)')
    admin.execute(f'CREATE DATABASE "{PROBE_DB}"')
    with psycopg.connect(PROBE_DSN, autocommit=True, connect_timeout=5) as sc, sc.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS age;")
        cur.execute("LOAD 'age';")
        cur.execute('SET search_path = ag_catalog, "$user", public;')
        cur.execute("SELECT create_graph('memory');")
        # admitted page — shares the query terms, carries the PUBLIC marker
        cy(cur, "CREATE (:Concept {title:'gateway-runbook', admitted:true, "
                f"text:'Runbook to restart the gateway service run systemctl restart astryx gateway {PUBLIC}'}})")
        # tier-private Person — NO admitted flag (invisible by omission), same query terms + the SECRET
        cy(cur, "CREATE (:Person {name:'owner-contact', "
                f"text:'to restart the gateway service then phone the owner {SECRET} at his private number'}})")
        # an admitted->private LINKS edge: exercises onehop's both-admitted gate (a live edge INTO the dark node)
        cy(cur, "MATCH (c:Concept {title:'gateway-runbook'}), (p:Person {name:'owner-contact'}) "
                "CREATE (c)-[:LINKS]->(p)")

    # point the server at the throwaway, force EXTRACTIVE (no OpenAI key => no spend, verbatim quoting)
    S._env = lambda key: PROBE_DSN if key == "ASTRYX_DSN" else None

    # ── arm C: independent reachability (my raw read, no resolver) ────────────────────
    with psycopg.connect(PROBE_DSN, autocommit=True, connect_timeout=5) as c2, c2.cursor() as cur:
        alln = raw_nodes(cur)
    priv = [t for k, t in alln if k == "Person"]
    want("arm C: the tier-private Person node exists in the graph", len(priv) == 1)
    want("arm C: it carries the secret AND the query terms (retrievable absent the gate)",
         bool(priv) and SECRET in priv[0] and all(w in priv[0] for w in ("restart", "gateway", "service")))

    # ── arm B: mutation / leak control — drop the gate, the secret MUST leak ───────────
    _orig_corpus, _orig_onehop = S.R.corpus, S.R.onehop
    S.R.corpus = lambda cur: _orig_corpus(cur, admit_filter="")
    S.R.onehop = lambda cur, ids: _orig_onehop(cur, ids, both_admitted="")
    try:
        leaked = S.ask(QUERY)
    finally:
        S.R.corpus, S.R.onehop = _orig_corpus, _orig_onehop
    want("arm B: with the admit gate REMOVED, the secret leaks into ask() output "
         "(so the gate is load-bearing and arm A can detect a leak)", SECRET in leaked)

    # ── arm A: THE PROPERTY — gated ask() must not surface the secret, and must be non-vacuous ─
    out = S.ask(QUERY)
    obj = json.loads(out)
    answer, cites = obj.get("answer", ""), obj.get("citations", [])
    want("arm A: secret in NEITHER answer nor citations (whole ask() payload scanned)", SECRET not in out)
    want("arm A: non-vacuous — retrieval fired (citations returned)", len(cites) >= 1)
    want("arm A: the RIGHT (admitted) page surfaced — public marker present in the answer", PUBLIC in answer)
finally:
    cleanup()

print()
if fails:
    print(f"test_memory_ask_tier: {len(fails)} FAIL — {fails}")
    sys.exit(1)
print("test_memory_ask_tier: ALL PASS — tier-private data reaches neither ask()'s answer nor its citations")
sys.exit(0)
