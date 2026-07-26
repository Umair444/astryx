#!/usr/bin/env python3
"""astryx · canopus recruiter-inbound poller — the FIRST consumer of the
tier-crossing doorbell (signals table, plan-16 / goal 16).

WHY THIS EXISTS. canopus's highest-value inbound is a recruiter reply to a live
job application; a screen invite is time-sensitive. Detected only by canopus's
daily 09:00 gmail sweep, worst-case latency is ~24h — too slow. SQL/python
triggers can't help directly: they see postgres, not gmail. This poller is the
bridge — it lands a WAKE (not the mail) into postgres, where an SQL trigger can
fire canopus in minutes.

WHY A SEPARATE TIMER, NOT A PULSE TRIGGER. The pulse must never grow an IMAP
dependency in its critical path (a hung fetch would drag every agent's clock).
So this is its own systemd timer (astryx-canopus-inbound.timer), fully
decoupled. Poller death = silent LATENCY regression only; the daily sweep is the
correctness floor. This is a latency primitive, NEVER a correctness one.

THE TIER CONTRACT (canopus Law 2 / local.md human-personal tier). Recruiter mail
content — employer, role, comp, stage — is personal-tier and NEVER touches the
wire or any RAG-reachable store. This poller:
  • reads ONLY message headers (From, Subject) for classification — never bodies;
  • persists to `signals` ONLY {agent, priority, ref}: a coarse binary urgency
    (1=urgent, 2=routine) and an OPAQUE ref (the IMAP UID, meaningless to any
    reader but canopus). No subject, sender, company, or classification label
    ever lands in the row (schema forbids it; signals_schema_guard.py watches);
  • keeps its dedup watermark in a 0600 file under gitignored homes/canopus/,
    holding only integers (uidvalidity, last_uid) — no mail content.
On wake, canopus resolves the actual mail via its OWN gmail grant (re-search;
the daily sweep is the backstop if the opaque ref has rotted).

EXPOSURE, NAMED HONESTLY. A same-uid peer can SELECT signals and infer career-
activity TIMING/RATE (not content). canopus classified this wake-signal as
career-ADJACENT (not tier-identical like a geofence timestamp) and accepted the
detection-grade residual until uid-isolation (goal #4) — see plan-16 step-6.

CLASSIFICATION is high-precision, NOT exhaustive (documented so it is not
mistaken for total coverage). It keys on ATS/employer sender domains + strong
recruiter-interaction tokens, and EXCLUDES job-board alert senders. It will miss
a personal recruiter mailing from a novel domain; the daily sweep catches those.
Tune the sets as real mail teaches new shapes.

Run by hand any time: venv/bin/python nucleus/canopus_inbound.py
"""
from __future__ import annotations

import email
import email.header
import imaplib
import json
import sys
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[1]
_env = {k: v for k, v in
        (l.split("=", 1) for l in (REPO / ".env").read_text().splitlines() if "=" in l)}
ADDR = _env["GMAIL_ADDRESS"].strip()
PASS = _env["GMAIL_APP_PASSWORD"].strip()
DSN = _env["ASTRYX_DSN"].strip()

AGENT = "canopus"
STATE = REPO / "homes" / "canopus" / ".inbound_state.json"   # 0600, gitignored, integers only
SCAN_LIMIT = 60         # newest N new UIDs per run — a burst never floods

# --- classification sets (high-precision, tune as mail teaches) --------------
# Generic ATS / recruiting platforms — universal recruiting infrastructure, NOT
# Umair-specific (every job seeker's mail flows through these), so safe to keep in
# this git-trackable file.
GENERIC_ATS_DOMAINS = (
    "deel.com", "greenhouse.io", "greenhouse-mail.io", "us.greenhouse.io",
    "eu.greenhouse.io", "lever.co", "hire.lever.co", "ashbyhq.com", "ashby.io",
    "myworkday.com", "myworkdayjobs.com", "smartrecruiters.com", "workable.com",
    "workablemail.com", "teamtailor.com", "icims.com", "jobvite.com",
    "recruitee.com", "pinpointhq.com",
)
# Target EMPLOYER domains are TIER-PRIVATE (Law 2): naming them reveals Umair's
# career targets, so they live ONLY in a gitignored 0600 file, never hardcoded in
# this trackable poller and never on the wire. Absent file → degrade gracefully to
# generic-ATS + token detection (still catches recruiter mail, daily sweep backstops).
_TARGETS_FILE = REPO / "homes" / "canopus" / ".recruiter_targets.json"


def _employer_domains() -> tuple[str, ...]:
    try:
        return tuple(json.loads(_TARGETS_FILE.read_text()).get("employer_domains", []))
    except (OSError, ValueError):
        return ()


RECRUITER_DOMAINS = GENERIC_ATS_DOMAINS + _employer_domains()
# Job-board ALERT / digest senders — never a recruiter interaction. Excluded so
# they never wake canopus (they are noise the daily scan already digests).
EXCLUDE_SENDERS = (
    "jobalerts-noreply@linkedin.com", "jobs-noreply@linkedin.com",
    "match.indeed.com", "alert@indeed.com", "donotreply@match.indeed.com",
    "noreply@glassdoor.com", "noreply@ziprecruiter.com", "jobalerts@",
    "no-reply@linkedin.com",
)
# Tokens that mark a real recruiter interaction (either the from or subject).
RECRUITER_TOKENS = (
    "recruit", "talent acquisition", "talent team", "talent partner",
    "hiring team", "hiring manager", "your application", "your candidacy",
    "thanks for applying", "thank you for applying",
)
# Urgency: an urgent token in the subject → priority 1 (time-sensitive action).
URGENT_TOKENS = (
    "interview", "schedule", "availability", "book a", "next step", "next steps",
    "phone screen", "video call", "screening call", "speak with", "let's chat",
    "meet with", "moving forward", "offer", "assessment", "would love to",
    "get on a call", "arrange a call", "your interview", "invitation",
)


def imap() -> imaplib.IMAP4_SSL:
    m = imaplib.IMAP4_SSL("imap.gmail.com")
    m.login(ADDR, PASS)
    return m


def dec(v) -> str:
    if not v:
        return ""
    return "".join(p.decode(c or "utf-8", errors="replace") if isinstance(p, bytes)
                   else p for p, c in email.header.decode_header(v))


def classify(frm: str, subject: str) -> int | None:
    """Return priority (1 urgent, 2 routine) for a recruiter-class mail, or None
    to ignore. Keys on headers only — never body. High-precision, not exhaustive.
    """
    f, s = frm.lower(), subject.lower()
    if any(x in f for x in EXCLUDE_SENDERS):
        return None
    domain = f.rsplit("@", 1)[-1].rstrip(">") if "@" in f else ""
    from_ats = any(domain == d or domain.endswith("." + d) for d in RECRUITER_DOMAINS)
    has_token = any(t in f or t in s for t in RECRUITER_TOKENS)
    if not (from_ats or has_token):
        return None                      # not recruiter-class → no signal
    urgent = any(t in s for t in URGENT_TOKENS)
    return 1 if urgent else 2


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    STATE.write_text(json.dumps(st))
    try:
        STATE.chmod(0o600)
    except OSError:
        pass


def main() -> int:
    m = imap()
    signalled = scanned = 0
    try:
        m.select("INBOX", readonly=True)
        # UIDVALIDITY: if it changes, old UIDs are meaningless — re-baseline.
        _, uv = m.status("INBOX", "(UIDVALIDITY)")
        uidvalidity = int(uv[0].split(b"UIDVALIDITY")[1].strip(b" ()").split()[0])
        _, data = m.uid("search", None, "ALL")
        uids = [int(x) for x in data[0].split()]
        if not uids:
            return 0
        max_uid = max(uids)

        st = load_state()
        # First run OR a UIDVALIDITY change → watermark-only, emit nothing (no
        # backfill flood; the whole existing inbox is not "new recruiter mail").
        if st.get("uidvalidity") != uidvalidity or "last_uid" not in st:
            save_state({"uidvalidity": uidvalidity, "last_uid": max_uid})
            print(f"canopus_inbound: baseline set (uid<= {max_uid}), no signals")
            return 0

        last_uid = int(st["last_uid"])
        fresh = [u for u in uids if u > last_uid][-SCAN_LIMIT:]
        if not fresh:
            return 0

        with psycopg.connect(DSN, autocommit=True) as conn:
            for u in fresh:
                scanned += 1
                _, d = m.uid("fetch", str(u),
                             "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                raw = next((x[1] for x in d if isinstance(x, tuple)), b"")
                hdr = email.message_from_bytes(raw)
                prio = classify(dec(hdr["From"]), dec(hdr["Subject"]))
                if prio is None:
                    continue
                # dedup guard (at-least-once safety): don't re-signal a UID that
                # already produced a row if a prior run crashed pre-state-write.
                dup = conn.execute(
                    "SELECT 1 FROM signals WHERE agent=%s AND ref=%s LIMIT 1",
                    (AGENT, u)).fetchone()
                if dup:
                    continue
                conn.execute(
                    "INSERT INTO signals (agent, priority, ref) VALUES (%s, %s, %s)",
                    (AGENT, prio, u))
                signalled += 1
        # advance watermark only AFTER inserts commit
        save_state({"uidvalidity": uidvalidity, "last_uid": max_uid})
        # meta-only log (systemd journal) — never a subject or sender
        print(f"canopus_inbound: {signalled} signal(s), {scanned} new headers scanned")
        return 0
    finally:
        m.logout()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 — meta-only, never leak mail content
        print(f"canopus_inbound failed: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
