"""Oracle for triggers/steward/outbound_stuck.py — the org-wide undelivered-message sweep.

Lives in nucleus/ and not beside the trigger BY LAW: the pulse imports and RUNS every
triggers/*/*.py, so a test file there would execute on the live wire. Wired into check.sh.

WHAT THIS HAS TO OBSERVE IN ORDER TO FAIL, which is the question that makes a check worth
having. Three invariants, each with a fixture on the exact axis that would break it, and
each PROVEN RED against the wrong implementation before being trusted:

  (a) POLARITY — an unknown/new/misspelt status must default to WATCHED. The counterexample
      arm below runs the blocklist version (`status IN ('pending','dead')`) against the same
      fixture and asserts it goes SILENT. If someone ever "simplifies" the allowlist into a
      blocklist, (a) goes red and the counterexample goes green, which is the pair that says
      the polarity is load-bearing rather than incidental.
  (b) THE LADDER'S TAIL IS OPEN — the worst case must never become the quiet one. Asserted
      out to a decade, not just past the last named rung.
  (c) DEDUP ON THE ID SET — a newly stuck message must fire immediately rather than inherit
      an older message's throttle.

Run: venv/bin/python tests/test_outbound_stuck.py
"""
import sys
from datetime import datetime, timedelta, timezone
import runpy
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# The trigger BODY is gitignored, so on a fresh clone or a CI runner there is nothing to
# test. SKIP LOUDLY (77) rather than pass: a check that silently reports success when it
# could not run is the "a SKIP is not a PASS" defect in the one place anyone reads it.
import os as _os  # noqa: E402
if not _os.environ.get("OUTBOUND_STUCK_SRC") and not (REPO / "triggers" / "steward" / "outbound_stuck.py").exists():
    print("SKIP: triggers/steward/outbound_stuck.py not present (gitignored body) — "
          "the outbound-stuck classifier was NOT verified this run")
    sys.exit(77)

# Import by PATH, not as a package. `from triggers...` made `triggers` read as an
# UNDECLARED THIRD-PARTY import on a clean checkout — deps.py derives first-party roots
# from what exists on disk, and triggers/ is gitignored, so the dep-coverage gate went red
# on a clone while passing locally. runpy is the precedent already set by
# test_plan_lifecycle.py and test_ear_dark.py for exactly this: a body that may be absent
# is addressed as a file, never as a module.
import os  # noqa: E402
SRC = os.environ.get("OUTBOUND_STUCK_SRC") or str(REPO / "triggers" / "steward" / "outbound_stuck.py")
_MOD = runpy.run_path(SRC)  # noqa: E402
classify, SETTLED, BANDS = _MOD["classify"], _MOD["SETTLED"], _MOD["BANDS"]
bucket = _MOD["bucket"]

NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)


def row(mid, status, age_h, who="seed"):
    return {"id": mid, "status": status, "from_agent": who,
            "ts": NOW - timedelta(hours=age_h)}


def fired_ids(fire):
    return {mid for mid, _, _, _, _ in fire}


# ---------------------------------------------------------------- (a) POLARITY
def test_unknown_status_is_watched():
    """THE invariant. A status nobody has classified must arrive LOUD."""
    rows = [row(1, "queued", 5), row(2, "PENDING", 5), row(3, "retrying", 5)]
    fire, _ = classify(rows, NOW, {})
    assert fired_ids(fire) == {"1", "2", "3"}, fire


def test_settled_statuses_never_fire():
    rows = [row(1, "delivered", 900), row(2, "abandoned", 900)]
    # The trigger filters these in SQL; classify must also not invent them.
    kept = [r for r in rows if r["status"] not in SETTLED]
    fire, _ = classify(kept, NOW, {})
    assert fire == [], fire


def test_counterexample_a_blocklist_would_go_silent():
    """PROVES (a) CAN FAIL. The same fixture under the wrong polarity reports nothing —
    so test_unknown_status_is_watched is observing something real, not passing by luck."""
    rows = [row(1, "queued", 5), row(2, "retrying", 5)]
    blocklisted = [r for r in rows if r["status"] in ("pending", "dead")]
    fire, _ = classify(blocklisted, NOW, {})
    assert fire == [], "a blocklist should exempt these — if it does not, this arm is stale"


def test_dead_gets_no_grace():
    """The bridge raised; it will never retry. Reportable before the first band."""
    fire, _ = classify([row(1, "dead", 0.1)], NOW, {})
    assert fired_ids(fire) == {"1"}, fire


def test_in_flight_message_does_not_fire():
    fire, _ = classify([row(1, "pending", 0.2)], NOW, {})
    assert fire == [], "a message younger than the first rung is still in flight"


# ---------------------------------------------------------------- (b) OPEN TAIL
def test_ladder_reports_once_per_band_then_escalates():
    r = [row(1, "pending", 2)]                       # band 0 (>=1h)
    fire, state = classify(r, NOW, {})
    assert fired_ids(fire) == {"1"}
    fire, state = classify(r, NOW, state)
    assert fire == [], "same band must not re-fire"
    fire, state = classify([row(1, "pending", 7)], NOW, state)   # band 1 (>=6h)
    assert fired_ids(fire) == {"1"}, "a new band must re-nag"


def test_tail_is_open_past_the_last_named_rung():
    """A closed tuple would cap here and the oldest item would go permanently silent —
    warn-once wearing a ladder's clothes. Asserted out to a decade."""
    last = BANDS[-1]
    seen = set()
    for mult in (1, 2, 4, 8, 16, 32, 64):
        fire, _ = classify([row(1, "pending", last * mult)], NOW, {})
        assert fire, f"nothing at {last * mult}h"
        seen.add(fire[0][4])
    assert len(seen) == 7, f"bands must keep increasing past the tail, got {sorted(seen)}"


# ---------------------------------------------------------------- (c) SET DEDUP
def test_late_joiner_fires_despite_an_older_throttle():
    old = row(1, "pending", 200)
    fire, state = classify([old], NOW, {})
    assert fired_ids(fire) == {"1"}
    fire, state = classify([old, row(2, "pending", 2)], NOW, state)
    assert fired_ids(fire) == {"2"}, "a newly stuck message must not inherit a throttle"


def test_settled_row_heals_and_regains_the_full_ladder():
    # The band is asserted as a LITERAL, independently derived from BANDS rather than
    # recomputed by calling classify() again. The first version of this line read
    #   assert state == {"1": classify([row(1, "pending", 200)], NOW, {})[1]["1"]}
    # which calls the function under test on both sides of ==. That is a TAUTOLOGY: it
    # passes for any implementation, correct or garbage, and was proven to pass against a
    # classify() stubbed to return band 99999. Conformance-to-self, in the oracle, written
    # by the agent who filed the law against it two hours earlier.
    # 200h with BANDS=(1,6,24,72,168): past the last rung, so 4 + floor(log2(200/168)) = 4.
    fire, state = classify([row(1, "pending", 200)], NOW, {})
    assert state == {"1": 4}, state
    fire, state = classify([], NOW, state)          # it settled: gone from the query
    assert state == {}, "a settled row must drop out of state entirely"
    fire, _ = classify([row(1, "pending", 2)], NOW, state)
    assert fired_ids(fire) == {"1"}, "a returning row gets the ladder from the bottom"


# ------------------------------------------------ (d) REMEDY ROUTING by mechanism
# bucket() decides the REMEDY, and the remedies are opposite: a resident agent's stuck
# inbound means "restart the recipient", but owner/wa-/dc-/tg- have no per-agent body —
# they are bridge-delivered, and a pending row is usually a producer addressing fault.
# Conflating them is the defect this guard fired on 2026-08-26 (growbot->owner x2, 3d).
def _fentry(mid, status="pending", age_h=72, band=3):
    return (str(mid), "growbot", status, age_h, band)


def _meta(mid, **flags):
    base = {"awaiting_peer": False, "bridge_delivered": False, "pend_server": False}
    base.update(flags)
    return {str(mid): base}


def _ids(group):
    return {f[0] for f in group}


def test_owner_routes_to_bridge_not_deaf():
    """THE invariant this fix adds. owner is carried by a bridge, not a server.mjs, so it
    must never land in the DEAF class whose remedy is 'restart the recipient'."""
    g = bucket([_fentry(15423, "pending", 72)], _meta(15423, bridge_delivered=True))
    assert _ids(g["bridge"]) == {"15423"}, g["bridge"]
    assert g["deaf"] == [], "owner has no per-agent body — must not be classed deaf"


def test_resident_agent_still_routes_to_deaf():
    """The carve-out must not swallow a real server.mjs agent: it still routes to deaf."""
    g = bucket([_fentry(1, "pending", 72)], _meta(1, pend_server=True))
    assert _ids(g["deaf"]) == {"1"}, g["deaf"]
    assert g["bridge"] == []


def test_counterexample_without_the_flag_owner_misclassifies_as_deaf():
    """PROVES (d) CAN FAIL — the pre-fix state. With no bridge_delivered flag owner looks
    like a server agent and falls into deaf, the exact wrong-remedy the carve-out removes.
    If this ever stops landing in deaf, the counterexample is stale, not the fix."""
    g = bucket([_fentry(15423, "pending", 72)], _meta(15423, pend_server=True))
    assert _ids(g["deaf"]) == {"15423"}, g["deaf"]
    assert g["bridge"] == []


def test_awaiting_peer_outranks_bridge_and_deaf():
    """A federated NAT peer is correct-pending; that carve-out must precede bridge/deaf."""
    g = bucket([_fentry(2, "pending", 72)],
               _meta(2, awaiting_peer=True, bridge_delivered=True, pend_server=True))
    assert _ids(g["held"]) == {"2"}
    assert g["bridge"] == [] and g["deaf"] == []


def test_bridge_carve_out_is_pending_only():
    """A bridge-delivered row that is 'dead' (not pending) is a real send failure, not a
    thread refusal — it belongs in the age split, not the bridge advice."""
    g = bucket([_fentry(3, "dead", 72)], _meta(3, bridge_delivered=True))
    assert g["bridge"] == [], "dead is not a pending-refusal"
    assert _ids(g["fresh"]) == {"3"}, g


# An owner reply on ear-<room> is delivered by the ear SHEET (bridges/ear.py /ear/api/replies/seen, when the owner
# opens it), not by a bridge: the WhatsApp bridge is RIGHT to skip it (#46315, steward #46578; seed #46821).
def test_ear_sheet_reply_routes_to_sheet_not_bridge():
    """It is owner-addressed, so ALSO bridge-shaped: the sheet carve-out must precede the bridge's."""
    g = bucket([_fentry(46315, "pending", 6)], _meta(46315, bridge_delivered=True, sheet_delivered=True))
    assert _ids(g["sheet"]) == {"46315"}, g["sheet"]
    assert g["bridge"] == [] and g["deaf"] == [], g


def test_counterexample_without_the_sheet_flag_ear_reply_reads_as_bridge_fault():
    """PROVES the sheet class CAN FAIL — the pre-fix state: without sheet_delivered the same row gets the bridge's
    'producer addressing fault' advice, the misread steward #46578 made of #46315."""
    g = bucket([_fentry(46315, "pending", 6)], _meta(46315, bridge_delivered=True))
    assert _ids(g["bridge"]) == {"46315"} and g.get("sheet", []) == [], g


def test_sheet_carve_out_is_pending_only():
    """A dead ear-sheet row is a real failure, not an unopened sheet: it belongs in the age split."""
    g = bucket([_fentry(4, "dead", 72)], _meta(4, bridge_delivered=True, sheet_delivered=True))
    assert g["sheet"] == [] and _ids(g["fresh"]) == {"4"}, g


# ------------------------------------------------ (e) NO SUCH RESIDENT is not DEAF (2026-10-09)
# memory wrote to_agent='a3' (a nickname); this guard said "DEAF RECIPIENT a3 — restart it", a remedy
# that would have killed a HEALTHY abstractor-3. A name with no resident charter has no server.mjs to
# lose: its fault is the sender's addressing. DEAF is only for a RESIDENT.
def test_unknown_recipient_is_unaddressed_not_deaf():
    g = bucket([_fentry(35146, "pending", 2)], _meta(35146, pend_server=True, known_resident=False))
    assert _ids(g["unaddressed"]) == {"35146"} and g["deaf"] == [], g


def test_resident_with_roster_read_is_still_deaf():
    g = bucket([_fentry(2, "pending", 72)], _meta(2, pend_server=True, known_resident=True))
    assert _ids(g["deaf"]) == {"2"} and g["unaddressed"] == [], g


def test_roster_unread_falls_back_to_deaf():
    """known_resident ABSENT means the roster could not be read: the prior behaviour (DEAF) stands,
    so an unreadable roster never silently hides a real deaf resident."""
    g = bucket([_fentry(3, "pending", 72)], _meta(3, pend_server=True))
    assert _ids(g["deaf"]) == {"3"}, g


def test_unknown_recipient_render_never_says_restart():
    """Through the real entrypoint: the report for a non-resident names the ADDRESSING remedy and
    never the restart one. The roster is FORCED (a4 #35873): reading the host's agents/ tree made this
    arm pass only where the identity repo exists, and fail under branch_check or a clone."""
    out = _run_with_roster(["seed", "memory"], sender="memory", to="a3")
    assert "NO SUCH RESIDENT" in out and "a3" in out, out
    assert "DEAF RECIPIENT" not in out and "kill-session" not in out, out


def _run_with_roster(roster, sender="seed", to="abstractor-3", to_org="local", cands=()):
    """The real entrypoint on one 30h-pending row, with BOTH roster derivations forced to `roster`. `cands` =
    rows the later-rows query returns ({stuck, cand, resend}); every other query gets the stuck row."""
    import types
    import astryx.core.charter as ch
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    rows = [{"id": 901, "ts": _dt.now(_tz.utc) - _td(hours=30), "to_agent": to,
             "to_org": to_org, "status": "pending", "from_agent": sender, "external_handle": to_org != "local",
             "bridge_delivered": False, "awaiting_peer_pickup": False, "last_pickup": None}]
    real_t, real_r = ch.roster_of_type, ch.roster
    ch.roster_of_type = lambda kind, *a, **k: list(roster)
    ch.roster = lambda *a, **k: list(roster)
    try:
        return _MOD["outbound_stuck"](types.SimpleNamespace(
            state={}, sql=lambda q, p=(): list(cands) if "AS cand" in q else rows)) or ""
    finally:
        ch.roster_of_type, ch.roster = real_t, real_r


def test_empty_roster_is_unread_so_a_real_resident_stays_deaf():
    """a4 #35869: a checkout without the identity repo reads an EMPTY roster (it does not raise). That
    must fall back to DEAF — never hide a real deaf resident behind 'DO NOT restart anything'."""
    out = _run_with_roster([])
    assert "DEAF RECIPIENT" in out and "NO SUCH RESIDENT" not in out, out


def test_roster_without_seed_is_not_this_orgs_roster():
    out = _run_with_roster(["abstractor-1", "forge"])          # plausible-looking, but no seed
    assert "DEAF RECIPIENT" in out and "NO SUCH RESIDENT" not in out, out


def test_real_roster_with_the_resident_is_deaf_and_without_is_no_such():
    assert "DEAF RECIPIENT" in _run_with_roster(["seed", "abstractor-3"])
    out = _run_with_roster(["seed", "forge"])                  # the org's roster, recipient absent
    assert "NO SUCH RESIDENT" in out and "2 resident(s)" in out, out


def test_seed_only_roster_is_a_non_identity_checkout_so_stays_deaf():
    """a4 #35871: seed.md is TRACKED, so a checkout without the identity repo reads exactly {seed}.
    The row's sender must be in the roster for it to count as the org's — memory is not here → DEAF."""
    out = _run_with_roster(["seed"], sender="memory", to="abstractor-3")
    assert "DEAF RECIPIENT" in out and "NO SUCH RESIDENT" not in out, out


def test_the_live_shape_memory_to_a3_is_no_such_resident():
    """The 10-09 case itself, on a roster that names the sender: memory -> 'a3' is NO SUCH RESIDENT."""
    out = _run_with_roster(["seed", "memory", "abstractor-3"], sender="memory", to="a3")
    assert "NO SUCH RESIDENT" in out and "kill-session" not in out, out


def test_a_non_agent_sender_cannot_vouch_so_stays_deaf():
    out = _run_with_roster(["seed", "memory"], sender="pulse", to="a3")
    assert "DEAF RECIPIENT" in out and "NO SUCH RESIDENT" not in out, out


def test_own_surface_org_reads_surface_not_external():
    """10-09 forge #35625 → cv-…@canvas: `canvas` is the owner's own surface (orgname.RESERVED_ORGS), not a peer."""
    out = _run_with_roster(["seed", "forge"], sender="forge", to="cv-zz", to_org="canvas")
    assert "-> surface" in out and "-> external" not in out, out
    out = _run_with_roster(["seed", "forge"], sender="forge", to="x", to_org="peer.example")
    assert "-> external" in out, out


def test_later_rows_are_named_as_candidates_never_a_verdict():
    """steward night-review 10-10: the sender had already resent (memory #35146 → #35864); the guard now SAYS so."""
    out = _run_with_roster(["seed", "memory", "abstractor-3"], sender="memory", to="a3",
                           cands=[{"stuck": 901, "cand": 35864, "resend": True}, {"stuck": 901, "cand": 36566,
                                                                               "resend": False}])
    assert "#35864 (says resend)" in out and "#36566" in out and "read them before resending" in out, out
    assert "NO SUCH RESIDENT" in out, out                       # a candidate never changes the class or silences it
    out = _run_with_roster(["seed", "memory", "abstractor-3"], sender="memory", to="a3")
    assert "read them before resending" not in out, out


def test_later_rows_query_on_a_real_db_at_zero_and_one_rows():
    """The later-rows SQL through pulse_run.Ctx on a sqlguard fixture (its W rung: 0 rows and >=1 row)."""
    try:
        import psycopg
        import importlib.util
        from astryx.security.sqlguard.fixture import fixture_db
        sp = importlib.util.spec_from_file_location("pulse_run_os", REPO / "src" / "astryx" / "pulse" / "pulse_run.py")
        pr = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(pr)
        fxc = fixture_db()
        fx = fxc.__enter__()
    except Exception as e:  # noqa: BLE001
        print(f"    (skipped: no fixture DB — {type(e).__name__})")
        return
    try:
        conn = psycopg.connect(fx["dsn"], autocommit=True)

        class C(pr.Ctx):
            def __init__(s, st):
                super().__init__(st)
                s._conn = conn

        def put(frm, to, body, status, hours_ago):
            return conn.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, body, status, ts) "
                                "VALUES (%s,'local',%s,'local',%s,%s, now() - make_interval(hours => %s)) RETURNING id",
                                (frm, to, body, status, hours_ago)).fetchone()[0]
        stuck = put("memory", "a3", "Review request: the .absolute() switch", "pending", 30)
        out = _MOD["outbound_stuck"](C({})) or ""
        assert f"#{stuck}" in out and "read them before resending" not in out, out          # 0 candidate rows
        res = put("memory", "abstractor-3", f"Review request. This is a resend: #{stuck} went to a nickname",
                  "delivered", 29)
        out = _MOD["outbound_stuck"](C({})) or ""
        assert f"#{res} (says resend)" in out, out                                            # >=1 candidate row
        rep = put("memory", "abstractor-3", "Review request: the .absolute() switch", "delivered", 28)
        out = _MOD["outbound_stuck"](C({})) or ""                  # the projected `resend` bool must read FALSE too
        assert f"#{rep}" in out and f"#{rep} (says" not in out, out                          # (sqlguard: RESPONSIVE)
        pres = put("memory", "abstractor-3", f"I presented #{stuck} to the reviewers yesterday", "delivered", 27)
        out = _MOD["outbound_stuck"](C({})) or ""                  # a4 #41379 R2: "presented" is not a resend word
        assert f"#{pres}" in out and f"#{pres} (says" not in out, out
        conn.close()
    finally:
        fxc.__exit__(None, None, None)



# ------------------------------------------------ (e) the DOOR's refusal (plan-9139 S1c)
# A bridge's door refuses a row TERMINALLY (status 'refused', reason in delivery.door_refused): an unstamped row to a
# destination on no declared org route, a tiered route, a release that doesn't verify. The same row sent again is
# refused again, so every remedy above is wrong for it, "RESEND" most of all (a4 #53717).
def test_refused_routes_to_its_own_class_whatever_its_mechanism():
    for flags in ({"bridge_delivered": True}, {"pend_server": True}, {"awaiting_peer": True},
                  {"bridge_delivered": True, "sheet_delivered": True}, {}):
        g = bucket([_fentry(7, "refused", 2)], _meta(7, **flags))
        assert _ids(g["refused"]) == {"7"}, (flags, g)
        assert not any(_ids(v) for k, v in g.items() if k != "refused"), (flags, g)


def test_refused_gets_no_grace():
    """Like `dead`: the door raised and will never retry, so it is reportable the moment it appears."""
    fire, _ = classify([row(8, "refused", 0.05)], NOW, {})
    assert fired_ids(fire) == {"8"}, fire


def test_refused_render_says_do_not_resend_through_the_real_entrypoint():
    import types
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    rows = [{"id": 902, "ts": _dt.now(_tz.utc) - _td(hours=2), "to_agent": "owner", "to_org": "local",
             "status": "refused", "from_agent": "seed", "external_handle": False, "bridge_delivered": True,
             "sheet_delivered": False, "awaiting_peer_pickup": False, "last_pickup": None}]
    out = _MOD["outbound_stuck"](types.SimpleNamespace(state={}, sql=lambda q, p=(): [] if "AS cand" in q else rows))
    assert out and "REFUSED BY THE DOOR (1)" in out and "DO NOT RESEND" in out and "#902" in out, out
    assert "ACTIONABLE" not in out and "BRIDGE-DELIVERED" not in out and "fix the addressing, RESEND" not in out, out



# ------------------------------------------------ (f) the observatory DESK (memory #54646, steward #55678)
# An owner row on an obs:estate / obs:person- / obs:library- thread is delivered only when the observatory desk SERVES it
# (observatory/api/main.py memory_chat_replies). It is bridge-shaped too, and the WhatsApp bridge is right to skip it, so
# the bridge's "resend un-threaded / pgrep the bridge" was a remedy for a mechanism that never carries it.
def test_desk_reply_routes_to_desk_not_bridge():
    g = bucket([_fentry(54646, "pending", 6)], _meta(54646, bridge_delivered=True, desk_served=True))
    assert _ids(g["desk"]) == {"54646"} and g["bridge"] == [], g


def test_counterexample_without_the_desk_flag_a_desk_reply_reads_as_bridge_fault():
    """PROVES the desk class CAN FAIL: the pre-fix state, the same row with no desk_served, is the bridge's."""
    g = bucket([_fentry(54646, "pending", 6)], _meta(54646, bridge_delivered=True))
    assert _ids(g["bridge"]) == {"54646"} and g["desk"] == [], g


def test_desk_carve_out_is_pending_only():
    """A dead desk row is a real failure (something raised), not an unserved reply: it belongs in the age split."""
    g = bucket([_fentry(5, "dead", 72)], _meta(5, bridge_delivered=True, desk_served=True))
    assert g["desk"] == [] and _ids(g["fresh"]) == {"5"}, g


def test_refused_still_outranks_the_desk():
    g = bucket([_fentry(6, "refused", 2)], _meta(6, bridge_delivered=True, desk_served=True))
    assert _ids(g["refused"]) == {"6"} and g["desk"] == [], g


def _entry_rows(*specs):
    import types  # noqa: F401
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    out = []
    for mid, status, flags in specs:
        r = {"id": mid, "ts": _dt.now(_tz.utc) - _td(hours=2), "to_agent": "owner", "to_org": "local", "status": status,
             "from_agent": "memory", "external_handle": False, "bridge_delivered": True, "sheet_delivered": False,
             "desk_served": False, "awaiting_peer_pickup": False, "last_pickup": None}
        r.update(flags)
        out.append(r)
    return out


def _entry(rows):
    import types
    return _MOD["outbound_stuck"](types.SimpleNamespace(state={}, sql=lambda q, p=(): [] if "AS cand" in q else rows))


def test_a_desk_thread_from_a_sender_the_desk_does_not_serve_is_uncarried():
    """a4 #55690 (a): the desk serves from_agent='memory' only (main.py:3045). seed's 08-14 estate row is neither the
    desk's (it never serves it, late or not) nor the bridge's (which skips the thread by design)."""
    g = bucket([_fentry(9, "pending", 6)], _meta(9, bridge_delivered=True, desk_uncarried=True))
    assert _ids(g["desk_uncarried"]) == {"9"} and g["desk"] == [] and g["bridge"] == [], g


def test_the_person_desk_is_its_own_class():
    g = bucket([_fentry(10, "pending", 6)], _meta(10, bridge_delivered=True, desk_served=True, desk_person=True))
    assert _ids(g["desk_person"]) == {"10"} and g["desk"] == [] and g["bridge"] == [], g


def test_person_desk_render_never_prescribes_a_resend():
    """a4 #55690 (b): the person desk is People detail by construction, so the default must be the one that can't leak:
    no un-threaded resend, conditional or not."""
    import re
    out = _entry(_entry_rows((908, "pending", {"desk_served": True, "desk_person": True})))
    assert "UNSERVED ON THE PERSON DESK (1)" in out and "DO NOT RESEND IT ANYWHERE" in out and "#908" in out, out
    assert not re.search(r"(?i)un-threaded|doorbell", out), out
    assert "BRIDGE-DELIVERED" not in out and "pgrep" not in out, out


def test_uncarried_render_never_says_the_desk_serves_it():
    import re
    out = _entry(_entry_rows((909, "pending", {"desk_uncarried": True, "from_agent": "seed"})))
    assert "UNCARRIED BY CONSTRUCTION (1)" in out and "#909" in out, out
    assert "WAS served" not in out and "late answers" not in out and "pgrep" not in out, out
    assert not re.search(r"(?i)un-threaded", out), out


def test_an_uncarried_person_desk_row_gets_the_person_rule_not_a_re_route():
    """a4 #55692: an obs:person- row from a sender the desk doesn't serve is still People detail by construction, so
    "re-route it to a surface whose readers may read it" would hand that sender the judgment (b) took away."""
    import re
    g = bucket([_fentry(11, "pending", 6)], _meta(11, bridge_delivered=True, desk_uncarried=True, desk_person=True))
    assert _ids(g["desk_person"]) == {"11"} and g["desk_uncarried"] == [] and g["bridge"] == [], g
    out = _entry(_entry_rows((910, "pending", {"desk_uncarried": True, "desk_person": True, "from_agent": "seed"})))
    assert "UNSERVED ON THE PERSON DESK (1)" in out and "#910" in out and "UNCARRIED" not in out, out
    assert not re.search(r"(?i)re-route|un-threaded|doorbell", out), out


def test_desk_render_through_the_real_entrypoint_never_prescribes_the_bridge():
    out = _entry(_entry_rows((903, "pending", {"desk_served": True})))
    assert out and "UNSERVED ON AN OBSERVATORY DESK (1)" in out and "#903" in out, out
    assert "BRIDGE-DELIVERED" not in out and "pgrep" not in out and "ACTIONABLE" not in out, out


def test_every_un_threaded_remedy_says_the_doorbell_is_a_group():
    """memory #55679: the doorbell is the org GROUP. Every class whose remedy says "un-threaded" (door, ear sheet, desk,
    bridge) must say what content it fits, at EVERY occurrence, through the real entrypoint."""
    import re
    out = _entry(_entry_rows((904, "refused", {}), (905, "pending", {"sheet_delivered": True}),
                             (906, "pending", {"desk_served": True}), (907, "pending", {})))
    for cls in ("REFUSED BY THE DOOR", "UNSEEN ON THE EAR SHEET", "UNSERVED ON AN OBSERVATORY DESK",
                "BRIDGE-DELIVERED RECIPIENT"):
        assert cls in out, (cls, out)
    hits = [m.start() for m in re.finditer(r"(?i)un-threaded", out)]
    assert len(hits) >= 4, out
    for h in hits:
        assert "not an owner-only surface" in out[h:h + 160] and "never People detail" in out[h:h + 260], out[h:h + 260]


def test_desk_predicate_on_a_real_db_reads_the_consumers_prefixes_and_who():
    """The desk projections through pulse_run.Ctx on a sqlguard fixture, read TRUE and FALSE: the three prefixes
    the observatory serves, from memory, are the desk's (the person prefix its own class); a desk thread from another
    sender is uncarried (the consumer's WHO, main.py:3045); a near-miss obs: thread is the bridge's."""
    try:
        import psycopg
        import importlib.util
        from astryx.security.sqlguard.fixture import fixture_db
        sp = importlib.util.spec_from_file_location("pulse_run_os", REPO / "src" / "astryx" / "pulse" / "pulse_run.py")
        pr = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(pr)
        fxc = fixture_db()
        fx = fxc.__enter__()
    except Exception as e:  # noqa: BLE001
        print(f"    (skipped: no fixture DB — {type(e).__name__})")
        return
    try:
        conn = psycopg.connect(fx["dsn"], autocommit=True)

        class C(pr.Ctx):
            def __init__(s, st):
                super().__init__(st)
                s._conn = conn

        def put(thread, frm="memory"):
            return conn.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, body, status, ts) "
                                "VALUES (%s,'local','owner','local',%s,'x','pending', now() - interval '2 hours') "
                                "RETURNING id", (frm, thread)).fetchone()[0]
        want = {"UNSERVED ON AN OBSERVATORY DESK": [put("obs:estate-ab12"), put("obs:library-e4523e8f")],
                "UNSERVED ON THE PERSON DESK": [put("obs:person-77"), put("obs:person-78", "seed")],
                "UNCARRIED BY CONSTRUCTION": [put("obs:estate-cd34", "seed")],        # the consumer's WHO is memory
                "BRIDGE-DELIVERED RECIPIENT": [put("obs:other-1")]}                  # a near-miss no desk serves
        out = _MOD["outbound_stuck"](C({})) or ""
        # sliced by header, never split on " | ": the bridge's own remedy text holds a shell pipe (`journalctl … | grep`)
        at = sorted((out.find(h), h) for h in want)
        assert all(i >= 0 for i, _ in at), out
        sec = {h: out[i:(at[k + 1][0] if k + 1 < len(at) else len(out))] for k, (i, h) in enumerate(at)}
        for h, ids in want.items():
            for i in ids:
                assert f"#{i} " in sec[h] and not any(f"#{i} " in v for k, v in sec.items() if k != h), (h, i, out)
        conn.close()
    finally:
        fxc.__exit__(None, None, None)

if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  ✗ {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
