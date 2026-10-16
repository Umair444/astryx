#!/usr/bin/env python3
"""ASTRYX tool nudge — UserPromptSubmit. Label the task, and when its FAMILY RECURS, point the
agent at the tool registry before it does the work by hand (goal 4227, S4).

    recurring family (≥ RECUR_N prior labels, org-wide, RECUR_DAYS)  → search the registry first
    complex and novel                                                → decompose; check for pieces
    anything else (trivial, simple one-off)                          → print nothing
    …and never twice for one (agent, family) within COOLDOWN_DAYS.

THE COOLDOWN (abstractor-4, plan-4227 W2). Recurrence is org-wide, because a family recurring
across agents is exactly the shared-tool signal. That makes the org's dominant families
(night-review, plan review, wire replies) "recurring" for every agent from day one, and a hint
repeated on every wake trains dismissal. The first nudge carries all the information. It's
recorded on the classification row (nudged=true), so the cooldown is DERIVED from the table
rather than remembered, and it can't be lost.

It's gated on recurrence, not difficulty: a complex one-off tool gets 0 calls, so it's worth 0.

THE CLASSIFIER IS PLUGGABLE AND EXTERNAL. The owner's AnyJev (Qwen3, local) runs as its own
service outside astryx, and astryx is backend-agnostic. Contract, over HTTP/1.1:
    POST <endpoint>  {"text": "<prompt>"}  →  {"family": "<slug>", "tier": "trivial|simple|complex",
                                               "model": "<optional id>"}
Configured ONLY in .env: ASTRYX_CLASSIFIER_URL=http://127.0.0.1:<port>/<path> or
unix:/path/to.sock[:/path]. If it's unset, the hook does nothing, which is the state until the
service runs.

NO PROMPT IS EVER BLOCKED (I6). Every path exits 0. A hard wall-clock deadline (HARD_S, a
SIGALRM over the whole hook) ends the run silently, however the time was spent: connect, a
server that accepts and never answers, a slow drip, the DB. It runs as its own hook entry so it
can't spend usage.py's time. An exit 2 on UserPromptSubmit would block the prompt, so the
oracle (tests/test_nudge.py) statically refuses any non-zero exit in this file.

PRIVACY (I5), graded honestly:
  * The endpoint must be a literal loopback IP (127.0.0.0/8, ::1) or a unix socket. A hostname
    is refused even when it's "localhost", because a name can be re-pointed. Anything else is
    refused and logged as an error step, unless the OWNER sets
    ASTRYX_CLASSIFIER_ALLOW_REMOTE=1 in .env. Against a same-uid actor, who can edit .env or
    this file, that's DETECTION-grade, not prevention.
  * Agents whose content is not public (nucleus/tier.py, grant-derived, fail-closed) are
    never classified: their prompts carry owner-personal data.
  * Nothing from the prompt is persisted. The table stores the label, and its CHECKs refuse a
    label shaped like prompt text. The label is validated here too, before it's written.
The label only ever steers ADVICE. A prompt injection that flips it costs one wrong hint.
"""
import ipaddress
import json
import os
import re
import signal
import socket
import sys
import http.client
from urllib.parse import urlsplit

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

HARD_S = 1.5            # the whole hook, wall clock
CLASSIFY_S = 1.0        # socket timeout for the classifier (each op); HARD_S bounds the total
RECUR_N = 3             # prior labels of the same family that make it "recurring"
RECUR_DAYS = 14
COOLDOWN_DAYS = 7       # at most one nudge per (agent, family) in this window
TEXT_MAX = 8000         # characters of prompt sent to the classifier
FAMILY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,47}$")
TIERS = ("trivial", "simple", "complex")
MODEL_RE = re.compile(r"^[A-Za-z0-9_.:/@+-]{1,64}$")


class _Deadline(Exception):
    pass


def _alarm(*_):
    raise _Deadline()


def env_file() -> dict:
    out = {}
    try:
        with open(os.path.join(REPO, ".env")) as f:
            for line in f:
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


def endpoint_ok(url: str) -> bool:
    """True for a unix socket, or an http(s) URL whose host is a literal loopback IP."""
    if url.startswith("unix:"):
        return True
    try:
        u = urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            return False
        return ipaddress.ip_address(u.hostname).is_loopback
    except ValueError:
        return False                     # a hostname, not an IP, and names can be re-pointed


class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


def classify(url: str, text: str) -> dict | None:
    body = json.dumps({"text": text[:TEXT_MAX]})
    if url.startswith("unix:"):
        rest = url[len("unix:"):]
        sock, _, path = rest.partition(":")
        conn = _UnixHTTP(sock, CLASSIFY_S)
        path = path or "/classify"
    else:
        u = urlsplit(url)
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        conn = cls(u.hostname, u.port, timeout=CLASSIFY_S)
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    try:
        conn.request("POST", path, body, {"Content-Type": "application/json"})
        r = conn.getresponse()
        if r.status != 200:
            return None
        out = json.loads(r.read(4096).decode("utf-8", "replace"))
    finally:
        conn.close()
    if not isinstance(out, dict):
        return None
    fam, tier = out.get("family"), out.get("tier")
    if not isinstance(fam, str) or not FAMILY_RE.match(fam) or tier not in TIERS:
        return None                      # malformed, or shaped like prompt text: no label
    model = out.get("model")
    return {"family": fam, "tier": tier,
            "model": model if isinstance(model, str) and MODEL_RE.match(model) else None}


def log_error(dsn: str, agent: str, key: str, detail: str) -> None:
    """One error step per agent per KEY per hour. Silence is the right failure for one prompt,
    and the wrong one for a standing fault (a refused endpoint, a missing migration): without a
    trace, the feature is dead and looks idle. The step names the fault, never its payload."""
    import psycopg
    with psycopg.connect(dsn, connect_timeout=1) as c:
        seen = c.execute(
            "SELECT 1 FROM steps WHERE agent=%s AND kind='error' AND content LIKE %s "
            "AND ts > now() - interval '1 hour' LIMIT 1", (agent, f"nudge: {key}%")).fetchone()
        if not seen:
            c.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,'error',%s)",
                      (agent, f"nudge: {key} ({detail})"))


def log_refusal(dsn: str, agent: str, url: str) -> None:
    """Named, not quoted: the URL could itself be something the owner keeps off the public wall."""
    log_error(dsn, agent, "classifier endpoint refused",
              "not loopback/unix socket; the owner can allow it with "
              "ASTRYX_CLASSIFIER_ALLOW_REMOTE=1")


def main() -> None:
    agent = os.environ.get("ASTRYX_AGENT")
    if not agent:
        return
    cfg = env_file()
    url = cfg.get("ASTRYX_CLASSIFIER_URL", "")
    dsn = cfg.get("ASTRYX_DSN", "")
    if not url or not dsn:
        return
    from nucleus.tier import is_content_public
    if not is_content_public(agent):
        return
    if not endpoint_ok(url) and cfg.get("ASTRYX_CLASSIFIER_ALLOW_REMOTE") != "1":
        log_refusal(dsn, agent, url)
        return
    h = json.load(sys.stdin)
    prompt = h.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return
    label = classify(url, prompt)
    if not label:
        return

    import psycopg
    try:
        kind, prior = record(psycopg, dsn, agent, h, label)
    except _Deadline:
        raise
    except Exception as e:
        # A DB fault is visible, once an hour, by exception CLASS only: the message can quote
        # SQL or values. abstractor-4, plan-4227: a missing `nudged` migration would otherwise
        # kill the nudge silently and forever.
        log_error(dsn, agent, "classification write failed", type(e).__name__)
        return
    # Printed only after the row COMMITS (record() above). If the deadline lands in between, a
    # nudge is lost rather than repeated: silence is this hook's failure direction.

    find = f"{REPO}/venv/bin/python {REPO}/nucleus/toolreg.py find <words>"
    if kind == "recurring":
        print(f"[tools] Recurring work: task family '{label['family']}' came up {prior}x in "
              f"{RECUR_DAYS}d. Search the registry before doing it by hand: `{find}` (or "
              f"mcp__tools__find). If nothing fits, read {REPO}/skills/tool-building/SKILL.md "
              f"and make one.")
    elif kind == "complex":
        print(f"[tools] Complex task: decompose it first, and check the registry for pieces "
              f"you can reuse: `{find}`.")


def record(psycopg, dsn, agent, h, label) -> tuple:
    """Count the family, apply the cooldown, write the label. Returns (nudge kind or None, prior)."""
    with psycopg.connect(dsn, connect_timeout=1) as c:
        prior = c.execute(
            "SELECT count(*) FROM classifications WHERE family=%s "
            "AND ts > now() - make_interval(days => %s)",
            (label["family"], RECUR_DAYS)).fetchone()[0]
        cooling = c.execute(
            "SELECT 1 FROM classifications WHERE agent=%s AND family=%s AND nudged "
            "AND ts > now() - make_interval(days => %s) LIMIT 1",
            (agent, label["family"], COOLDOWN_DAYS)).fetchone()
        kind = None
        if not cooling:
            if prior >= RECUR_N and label["tier"] != "trivial":
                kind = "recurring"
            elif label["tier"] == "complex":
                kind = "complex"
        c.execute("INSERT INTO classifications (agent, session_id, family, tier, classifier, "
                  "nudged) VALUES (%s,%s,%s,%s,%s,%s)",
                  (agent, (h.get("session_id") or None), label["family"], label["tier"],
                   label["model"], kind is not None))
    return kind, prior


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, HARD_S)
        main()
    except BaseException:
        pass                             # a nudge is advice; any failure is silence
    finally:
        try:
            signal.setitimer(signal.ITIMER_REAL, 0)
        except BaseException:
            pass
    sys.stdout.flush()
    os._exit(0)
