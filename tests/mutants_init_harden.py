"""Mutants for init.sh's harden node (tests/test_init_harden.py).

DECLARED, NOT AUTHORED: widening the domain (dropping the `:'only'` name filter, or the pg_has_role clause). Under
the oracle that mutant would REVOKE on the LIVE databases, so running it would mutate the estate the whole design
exists not to touch. Its arm ("the unnamed one is still open") is real; the probe just must not be the one to fire it.
NOT PROBED (a named gap): the run-role exclusion (`NOT LIKE 'bc\\_%'`). No arm plants a bc_* role, so dropping it
would survive; its effect is that a live branch_check run would HOLD every database it can reach while it runs.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "init.sh"
ORACLE = REPO / "tests" / "test_init_harden.py"
ENV = "INIT_HARDEN_SRC"
MUTANTS = {
    "H1 the check ignores a psql failure (an unreachable server reads green)":
        ('local o; o=$(_open_dbs "$@") || return 1; [ -z "$o" ]', 'local o; o=$(_open_dbs "$@"); [ -z "$o" ]'),
    "H2 the act grants instead of revoking":
        ("format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', datname)",
         "format('GRANT CONNECT ON DATABASE %I TO PUBLIC', datname)"),
    "H3 the node isn't in the reconciler":
        ('"schema|interior" "harden|interior" "hardencut|halt"', '"schema|interior" "hardencut|halt"'),
    "H4 the domain query can never see an open database (the check is blind)":
        ("AND has_database_privilege('public', datname, 'CONNECT')",
         "AND has_database_privilege('public', datname, 'TEMP') AND false"),
    "H5 dependents are never found (another app's PUBLIC-only role gets cut)":
        ("JOIN pg_roles r ON r.rolcanlogin AND NOT r.rolsuper", "JOIN pg_roles r ON false AND NOT r.rolsuper"),
    "H6 the act ignores the hold (revokes the held database anyway)":
        ("FROM ($_HARDEN_FREE) f \\gexec", "FROM ($_HARDEN_Q) f \\gexec"),
    "H7 an explicit GRANT doesn't release the hold":
        ("WHERE x.privilege_type = 'CONNECT' AND x.grantee <> 0", "WHERE x.privilege_type = 'CONNECT' AND false"),
    "H8 hardencut isn't a boundary in the reconciler":
        ('"hardencut|halt"', '"hardencut|interior"'),
}
