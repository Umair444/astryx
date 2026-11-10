"""Authored mutants for src/astryx/security/sqlguard/fixture.py's reaper, oracle tests/test_fixture_reaper.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_fixture_reaper.py

The reaper DROPs databases WITH (FORCE), so its battery lives in the tree, not in a message (a3 #39195). Most mutants
make it MORE aggressive. SAFE BY CONSTRUCTION (seed #34899): the oracle's live arms run under a PRIVATE prefix
(astryx_fx_rptest<pid>_), so an aggressive mutant can only ever see databases the oracle itself made.
Z1-Z5 (plan-11253 S3) mutate the batch and the lifetime seam; their arms are section B of the oracle.
Not here, because EQUIVALENT: `keep=` ignored (a3 M7). fixture_db reaps BEFORE its CREATE, so its own name is
never listed.
THE BOUNDARY of that construction (a3 #39299): it protects every mutant that judges WITHIN reap()'s candidate set.
It does NOT protect a mutant that removes or widens reap()'s own `starts_with(datname, PREFIX)` filter. That one
would see every astryx_fx_* on the shared server. Don't add such a mutant here without a different construction:
a throwaway cluster, or a check of the candidate set against a planted allowlist BEFORE any DROP.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "src" / "astryx" / "security" / "sqlguard" / "fixture.py"
ORACLE = REPO / "tests" / "test_fixture_reaper.py"
ENV = "SQLGUARD_FIXTURE_SRC"
TIMEOUT = 300
MUTANTS = {
    "S1 nothing is held across CREATE → COMMENT (a gate cap's kill leaves the database UNSTAMPED, kept forever)":
        ("_HELD = (signal.SIGTERM, signal.SIGHUP)\n", "_HELD = ()\n"),
    "S2 the main thread holds by a per-thread MASK only (a live daemon thread takes the TERM mid-window, a3 #61239)":
        ("    if threading.current_thread() is threading.main_thread():\n        got = []\n",
         "    if False:\n        got = []\n"),
    "S3 a recorded TERM is never raised again (the caller's kill is swallowed: the run lives on past its cap)":
        ("                signal.raise_signal(n)\n", "                pass\n"),
    "I1 reap's writes run on the CALLER's connection (a FATAL closes it under fixture_db's CREATE, steward #61372)":
        ("                        side = _side_admin(admin)\n", "                        side = admin\n"),
    "I2 an invalid database is un-templated first (ALTER draws a FATAL: the side connection dies, nothing is dropped)":
        ("                    if not invalid:\n", "                    if True:\n"),
    "T1 a condemned template is not un-templated (DROP refuses it: a killed batch run's template is kept forever)":
        ("                        side.execute('ALTER DATABASE \"{}\" IS_TEMPLATE false'.format(name.replace('\"', '\"\"')))\n",
         "                        pass\n"),   # a valid body: an empty try is an IndentationError, a vacuous catch (a4 #60380)
    "T2 a refused un-template is reported as a refused DROP, and the DROP is attempted anyway":
        ("            if act == \"reap\":\n                try:\n                    _drop(side, name)",
         "            if True:\n                try:\n                    _drop(side, name)"),
    "D-A the drop never falls back (an autovacuum worker fails a run role's teardown again, steward #55022)":
        ("    except psycopg.errors.InsufficientPrivilege:\n        admin.execute(f\"DROP DATABASE IF EXISTS {q}\")",
         "    except NotImplementedError:\n        admin.execute(f\"DROP DATABASE IF EXISTS {q}\")"),
    "D-B the drop falls back on ANY error (a real connected session is waited out silently)":
        ("    except psycopg.errors.InsufficientPrivilege:\n        admin.execute(f\"DROP DATABASE IF EXISTS {q}\")",
         "    except psycopg.Error:\n        admin.execute(f\"DROP DATABASE IF EXISTS {q}\")"),
    "R1 another pid namespace or host is judged (a bwrap run's pid read as a host pid)":
        ('    if not st["pidns"] or st["pidns"] != pidns or st["host"] != host:',
         '    if False:'),
    "R2 an unknowable pidns on BOTH sides is judged (a3 M3: two /proc-less sandboxes)":
        ('    if not st["pidns"] or st["pidns"] != pidns or st["host"] != host:',
         '    if st["pidns"] != pidns or st["host"] != host:'),
    "R3 the NAME is trusted: an unstamped DB is reaped when its tail pid looks dead":
        ('        return "keep", f"no owner stamp (name tail pid {name_pid(name)}, never trusted)"',
         '        p = name_pid(name)\n        return ("keep", "x") if p is None or alive(p) else ("reap", "name")'),
    "R4 pid reuse fails OPEN: PermissionError (another owner's live process) reads dead":
        ('    except (PermissionError, OverflowError, ValueError):\n        return True',
         '    except (PermissionError, OverflowError, ValueError):\n        return False'),
    "R5 reap() drops on KEEP (the verdict is inverted at the actuator)":
        ('        act, why = verdict(name, comment)\n',          # re-anchored: reap() now has two `if act == "reap"`
         '        act, why = verdict(name, comment)\n        act = "keep" if act == "reap" else "reap"\n'),
    "R6 no reap at fixture_db entry (the leak stays)":
        ('    reap(admin, keep=name)  ',
         '    pass  '),
    "R7 no owner stamp written (nothing is ever reapable)":
        ("            admin.execute(f'COMMENT ON DATABASE \"{name}\" IS \\'{owner_stamp()}\\'')",
         "            pass"),
    # plan-11253 S3 (a4 #57171, a3 BC-6 #57352): the opt-in batch, the lifetime seam 11254 extends (#57439 §1)
    "Z1 the batch close drops SERIALLY (one worker: each DROP's checkpoint wait is paid in turn, a3's 19-25 s)":
        ("        with ThreadPoolExecutor(max_workers=len(names), thread_name_prefix=BATCH_THREAD) as pool:",
         "        with ThreadPoolExecutor(max_workers=1, thread_name_prefix=BATCH_THREAD) as pool:"),
    "Z2 an already-GONE member whose drop errored is raised (a concurrent sweep turns the run red: BC-6)":
        ('        failed = {r["name"]: r["error"] or "still exists after its drop" for r in self.report if r["name"] in left}',
         '        failed = {r["name"]: r["error"] or "still exists after its drop" for r in self.report\n'
         '                  if r["name"] in left or r["error"]}'),
    "Z3 a member that still exists and failed is SWALLOWED (the close reads clean over a leak)":
        ("        if failed:\n            raise BatchDropError(failed)", "        if False:\n            raise BatchDropError(failed)"),
    "Z4 the DEFAULT lifetime no longer drops at block exit (every immediate caller silently becomes batch-like)":
        ('                _drop(admin, name)                   # "immediate"', '                pass                   # "immediate"'),
    "Z5 a \"batch\" member is dropped at block exit anyway (the batch saves nothing)":
        ('            if lifetime == "batch":\n                pass ', '            if False:\n                pass '),
}
