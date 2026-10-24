#!/usr/bin/env python3
"""sqlguard enforce is READ-ONLY on the seen-set clocks unless it is the timer (plan-11908 D5, a3 BC-1 #62652).

    venv/bin/python tests/test_sqlguard_seen.py

_clock upserted `runs` for every key a run merely couldn't search (an early R-CLOCK on a narrow run) and DELETED every
key the run didn't list (a2's data loss), on every check.sh: merge checks, hand runs, pushed-tree checks. Now only
enforce's __main__ maps ASTRYX_SQLGUARD_WRITE_SEEN=1 (check_watch.sh exports it), and enforce() defaults to False.
Drives the REAL enforce() in process against a stamped fixture DB (sqlguard_seen from schema.sql):
  N1 a read-only enforce leaves sqlguard_seen identical: count, max(last_seen), a hash of every (kind, key, runs,
     first_seen); a site it couldn't search adds no row, and a stored key it didn't list is not deleted
  N2 ...and it names the omission: "seen-set clocks not advanced (read-only run)", rc 77 on an otherwise clean run
  N3 ...even with ASTRYX_SQLGUARD_WRITE_SEEN=1 in its OWN process env: the function never reads the env (only __main__)
  N4 a read-only run still READS the stored clocks: an aged key is R-CLOCK RED, and the RED is rc 1 (never masked)
  N5 control: write_seen=True advances the clocks (runs +1 on a listed key, the unlisted key deleted), no ○ line
Mutants: tests/mutants_sqlguard_seen.py (default True; the function reads the env itself).
Exit 0 pass · 1 fail · 77 no reachable fixture server (nothing verified).
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate, unavailable  # noqa: E402
gate("test_sqlguard_seen", REPO, deps=("psycopg",), env=False)
import psycopg  # noqa: E402
from astryx.security.sqlguard import enforce as enf  # noqa: E402
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402
from astryx.security.sqlguard.privacy import text_key  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  ({detail})"))
    if not ok:
        fails.append(name)


CAN = enf.CANARY + "\x1fselect 1"
NS = "subj/seen.py::f\x1fselect id from goals where id = ?"          # a site this run couldn't search
AGED = "subj/seen.py::g\x1fselect id from goals where owner = ?"     # one whose stored clock is past the limits
STATE = ("SELECT count(*), max(last_seen), md5(coalesce(string_agg(kind || ':' || key || ':' || runs || ':' || "
         "first_seen, ',' ORDER BY kind, key), '')) FROM sqlguard_seen")


def rep(*ns):
    return {"sites": {CAN: {"rung": "RESPONSIVE"}, **{k: {"rung": "NOT SEARCHED"} for k in ns}},
            "run_not_searched": [], "gates": {}, "covering": {}, "extractors": {}, "blind": []}


LED = {"rows": {}, "extractors": {}, "covering": {}}


def main():
    run_id = os.environ.get("ASTRYX_SQLGUARD_RUN") or f"seen{os.getpid()}"
    os.environ["ASTRYX_SQLGUARD_RUN"] = f"st{os.getpid()}"       # the state DB must not be "this run's" (R-LEAK)
    with fixture_db() as fx:
        os.environ["ASTRYX_SQLGUARD_RUN"] = run_id
        dsn = fx["dsn"]
        with psycopg.connect(dsn, autocommit=True) as st:
            st.execute("INSERT INTO sqlguard_seen (kind, key) VALUES ('ns_site', 'unlisted-key')")
            st.execute("INSERT INTO sqlguard_seen (kind, key, runs, first_seen) VALUES ('ns_site', %s, 99, "
                       "now() - interval '10 days')", (text_key(AGED),))
            s0 = st.execute(STATE).fetchone()

            out = enf.enforce("", ledger=LED, dsn=dsn, rep=rep(NS))
            s1 = st.execute(STATE).fetchone()
            check("N1 a read-only enforce leaves sqlguard_seen identical (count, max(last_seen), keys+runs hash)",
                  s1 == s0, f"{s0} -> {s1}")
            check("N2 the read-only run names the omission, rc 77 on an otherwise clean run",
                  enf.READ_ONLY in out["not_searched"] and out["rc"] == 77 and not out["red"],
                  f"rc={out['rc']} ns={out['not_searched']} red={out['red']}")

            os.environ["ASTRYX_SQLGUARD_WRITE_SEEN"] = "1"
            try:
                out3 = enf.enforce("", ledger=LED, dsn=dsn, rep=rep(NS))
            finally:
                os.environ.pop("ASTRYX_SQLGUARD_WRITE_SEEN", None)
            check("N3 the flag in enforce()'s own process env changes nothing: only __main__ maps it",
                  st.execute(STATE).fetchone() == s0 and enf.READ_ONLY in out3["not_searched"],
                  f"{st.execute(STATE).fetchone()} ns={out3['not_searched']}")

            out4 = enf.enforce("", ledger=LED, dsn=dsn, rep=rep(NS, AGED))
            check("N4 read-only still READS the clocks: the aged key is R-CLOCK RED, rc 1 (a RED is never masked)",
                  out4["rc"] == 1 and any(r.startswith("R-CLOCK") for r in out4["red"])
                  and st.execute(STATE).fetchone() == s0, f"rc={out4['rc']} red={out4['red']}")

            out5 = enf.enforce("", ledger=LED, dsn=dsn, rep=rep(AGED), write_seen=True)
            rows = dict(st.execute("SELECT key, runs FROM sqlguard_seen WHERE kind = 'ns_site'").fetchall())
            check("N5 control: write_seen=True advances the clocks (runs +1, the unlisted key deleted), no ○ line",
                  rows == {text_key(AGED): 100} and enf.READ_ONLY not in out5["not_searched"], f"{rows} {out5['not_searched']}")


try:
    main()
except FixtureUnavailable as e:
    unavailable("test_sqlguard_seen", REPO, e, failed=fails)

print(f"\n{'FAIL' if fails else 'PASS'}: sqlguard seen-set read-only ({len(fails)} failing)")
sys.exit(1 if fails else 0)
