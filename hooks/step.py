#!/usr/bin/env python3
"""ASTRYX step + turn writer. Every agent action lands in pg. Fail-silent, never blocks.
Wired as PreToolUse + PostToolUse + Stop hooks in each home's settings.json.

- PreToolUse / PostToolUse  -> one `steps` row per tool (the live stream the wall renders).
- Stop                      -> reconstruct the whole turn from the transcript the hook is
                               handed, write ONE `turns` row (verbatim raw of everything the
                               model generated for that prompt), back-fill steps.turn_id AND
                               messages.turn_id (the replies the agent sent this turn), and
                               keep a short `response` step for the wall/status line.

The causal graph: turns.input_msg_id -> the message that triggered the turn;
messages.turn_id -> the turn that produced the message. One message chains two turns.

TOOL LEDGER (goal 4227, S0): a call of a registered tool carries steps.meta — {registry_id} on
the `tool` row (one per call: COUNT here), {registry_id, result_bytes} on its tool_done/error
row (the COST), and {edits} on a Write/Edit of a tool's source (authorship evidence, never a
call). Every one also carries "v", the version of the call semantics that produced it
(toolreg.LEDGER_V). nucleus/toolreg.py is the one authority on ids. Only the id and a byte count are kept:
the command, the arguments and the result text are read to resolve the id and then dropped
(I5). A toolreg failure writes the step WITHOUT meta; it never costs the row.

SECRETS (plan-5497 S1a): this is the writer of turns.raw_payload, the one copy of every transcript
we OWN, and every pg_dump inherits it. So every declared secret (nucleus/secretset.py, derived from
.env and ~/.pgpass at write time) is replaced by "[redacted:<name>]" BEFORE any row is written:
the payload, the input prompt, the reply text and a step's detail. If the set can't be derived,
the transcript copies are WITHHELD (a marker in their place) and an error step says so. A writer's
unknown is "don't copy", never "copy raw".

Agent from ASTRYX_AGENT env. The transcript is the hook's own input, not a side-channel:
nothing else reads it — every consumer reads the tables.
"""
import json, os, re, sys
from datetime import datetime, timezone

REPO = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO)                 # so the Stop hook can reuse nucleus.usage_refresh

# One /api/oauth/usage call at most this often across the WHOLE org. The gauge is
# account-global — every agent shares one Claude account, so a single fresh read serves the
# fleet; there is no reason for 13 agents to each hit the endpoint on every turn. Activity
# drives the cadence: when the org is busy (burning) it refreshes often, when idle it does
# not refresh because nothing is changing. Tune here; this is the org's only usage-poll knob.
USAGE_THROTTLE_S = 120


def brief(v, n=400) -> str:
    if isinstance(v, str):
        return v[:n]
    try:
        return json.dumps(v)[:n]
    except Exception:
        return str(v)[:n]


def ledger_meta(tool, tool_input, response=None):
    """steps.meta for one call, or None. Never raises: telemetry must not cost the step row."""
    try:
        from nucleus.toolreg import resolve
        m = resolve(tool, tool_input)
        if response is not None:
            if "registry_id" not in m:
                return None               # tool_done carries only CALL cost, never edits
            m = {"registry_id": m["registry_id"], "v": m["v"],
                 "result_bytes": len(json.dumps(response, default=str).encode())}
        if not m:
            return None
        from psycopg.types.json import Jsonb
        return Jsonb(m)
    except Exception:
        return None


# TURN SCOPE (owner 11-15: a chat's live progress is for everyone in it): which messages opened the turn a step belongs
# to. steps.turn_id is back-filled only at Stop, so a live reader (a bridge's progress line) couldn't tell a step that
# serves this chat's ask from one serving another thread, and streamed them all into the group (medic 12159). Each
# Pre/PostToolUse step now carries meta.turn_msgs: the msg_ids in the turn's opening prompt (a redelivered batch holds
# several). Read from the session's own transcript, which the hook is handed anyway; a cache per transcript keeps the
# offset already read, so a call reads only what the session wrote since. Never raises: an unknown is [] (no scope,
# so a scoped reader shows nothing rather than everything). A batch whose messages came from two threads stamps the
# turn for both, so its work shows in both chats: one turn served both, there is no finer truth to show.
TURN_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", f"astryx-turn-{os.getuid()}")   # 0700, ours
TURN_CACHE = os.path.join(TURN_DIR, "{agent}.json")
TURN_SCAN = 1 << 20                      # a cold start scans back from the end this many bytes at a time
COMPACT_LEAD = "This session is being continued from a previous conversation"


def _opening_msgs(line: str):
    """The msg_ids a transcript line opens a turn with, or None when the line changes no scope. A message that lands
    INSIDE a running turn is no user line: Claude Code writes it as an `attachment` of type queued_command (medic
    12163: 22 in one 11 MB transcript), and the agent works on it in the same turn, so from there on no step can be
    told apart: the scope becomes [] (unknown is nothing; a union would let one chat's job show another's work)."""
    try:
        e = json.loads(line)
    except Exception:
        return None
    if e.get("type") == "attachment" and (e.get("attachment") or {}).get("type") == "queued_command":
        return []
    if e.get("type") != "user":
        return None
    c = (e.get("message") or {}).get("content")
    if is_tool_result(c) or e.get("isCompactSummary"):
        return None
    text = c if isinstance(c, str) else json.dumps(c)
    # a channel wake is written isMeta (so isMeta is NOT a "skip"); the one user line inside a turn is the compaction
    # summary, which shares its turn's index (seen in medic's and db's transcripts, 11-15)
    if text.lstrip().startswith(COMPACT_LEAD):
        return None
    return [int(x) for x in re.findall(r'msg_id=\\?"(\d+)', text)][:20]


def turn_msgs(path, agent) -> list:
    try:
        if not path or not os.path.isfile(path):
            return []
        size = os.path.getsize(path)
        cache_f = TURN_CACHE.format(agent=re.sub(r"[^a-z0-9_-]", "", agent))
        d = os.path.dirname(cache_f)
        os.makedirs(d, mode=0o700, exist_ok=True)
        st = os.lstat(d)                          # a dir someone else made, or a link, is not ours: no cache, no scope
        if st.st_uid != os.getuid() or not os.path.isdir(d) or os.path.islink(d):
            return []
        try:
            with open(cache_f) as f:
                c = json.load(f)
        except Exception:
            c = {}
        msgs, off = c.get("msgs", []), c.get("off", 0)
        with open(path, "rb") as f:
            if c.get("path") != path or off > size:   # a new session (or a rewritten file): find the last opening
                msgs, pos, tail = [], size, b""
                while pos > 0:
                    step = min(TURN_SCAN, pos)
                    pos -= step
                    f.seek(pos)
                    tail = f.read(step) + tail
                    lines = tail.split(b"\n")
                    found = next((m for m in (_opening_msgs(l.decode("utf-8", "replace")) for l in reversed(lines[1 if pos else 0:]))
                                  if m is not None), None)
                    if found is not None:
                        msgs = found
                        break
                    tail = lines[0] if pos else b""
                off = size
            else:
                f.seek(off)
                chunk = f.read(size - off)
                end = chunk.rfind(b"\n") + 1         # only whole lines; a half-written one is read next time
                for l in chunk[:end].split(b"\n"):
                    m = _opening_msgs(l.decode("utf-8", "replace"))
                    if m is not None:
                        msgs = m
                off += end
        tmp = cache_f + ".tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600), "w") as f:
            json.dump({"path": path, "off": off, "msgs": msgs}, f)
        os.replace(tmp, cache_f)
        return msgs
    except Exception:
        return []


# SUB-AGENTS (owner 11-15: "agents use forks and sub-agents … it should also appear in chat"). Measured on this host the
# same day: a sub-agent's tool events carry agent_id/agent_type and the PARENT's transcript_path, and the parent's
# PostToolUse(Agent) response carries the same id as `agentId`. Reading the transcript for a sub-agent's step would give
# the parent's CURRENT turn, wrong for a background helper that outlives the turn that launched it, so each helper is
# BOUND, at its launch, to the turn that launched it (one file per helper beside the turn cache); an unbound helper
# takes the launch still in flight (a foreground helper runs inside its Agent call), and nothing otherwise.
SUB_TTL = 24 * 3600                     # a binding (or a launch left open) older than this is forgotten


def _subs_dir(agent, kind):
    """<cache>/<agent>.<kind>/: ONE FILE PER HELPER (kind "subs", by agent_id) or per launch in flight (kind "launch",
    by the Agent call's tool_use_id). One writer per file: parallel launches in one message each write their own
    (medic 12186: a shared dict lost 13 of 60 bindings to concurrent read-modify-write)."""
    d = os.path.join(os.path.dirname(TURN_CACHE.format(agent="x")), re.sub(r"[^a-z0-9_-]", "", agent) + "." + kind)
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _key(s):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(s))[:64] or "x"


def _put(path, obj):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def _prune(d):
    try:
        now = datetime.now().timestamp()
        for n in os.listdir(d):
            p = os.path.join(d, n)
            if now - os.lstat(p).st_mtime > SUB_TTL:
                os.unlink(p)
    except Exception:
        pass


def launch_open(agent, tool_use_id, msgs):
    """PreToolUse(Agent): a helper is being launched from the turn `msgs` opened (until its PostToolUse)."""
    try:
        d = _subs_dir(agent, "launch")
        _put(os.path.join(d, _key(tool_use_id)), {"msgs": msgs})
        _prune(d)
    except Exception:
        pass


def launch_scope(agent, tool_use_id):
    """The scope captured when this launch opened (None when there is no such launch)."""
    try:
        with open(os.path.join(_subs_dir(agent, "launch"), _key(tool_use_id))) as f:
            return json.load(f).get("msgs") or []
    except Exception:
        return None


def launch_close(agent, tool_use_id=None):
    """Close one launch, or (no id: the turn ended) every launch still open: a launch whose PostToolUse never came (an
    interrupted Agent call) can't be inherited later (medic 12189)."""
    try:
        d = _subs_dir(agent, "launch")
        for n in ([_key(tool_use_id)] if tool_use_id else os.listdir(d)):
            try:
                os.unlink(os.path.join(d, n))
            except FileNotFoundError:
                pass
    except Exception:
        pass


def bind_sub(agent, aid, msgs, desc, kind):
    """The parent launched helper `aid` from the turn `msgs` opened: remember it, in a file of its own."""
    try:
        d = _subs_dir(agent, "subs")
        _put(os.path.join(d, _key(aid)), {"msgs": msgs, "desc": (desc or "")[:80], "type": (kind or "")[:40]})
        _prune(d)
    except Exception:
        pass


def _bound(agent, aid):
    try:
        with open(os.path.join(_subs_dir(agent, "subs"), _key(aid))) as f:
            b = json.load(f)
        return b if isinstance(b, dict) else None
    except Exception:
        return None


def _launching(agent):
    """The scope of the launches in flight, when they agree (one turn); else [] (unknown is nothing)."""
    try:
        d = _subs_dir(agent, "launch")
        now, seen = datetime.now().timestamp(), []
        for n in os.listdir(d):
            p = os.path.join(d, n)
            if n.endswith(".tmp") or now - os.lstat(p).st_mtime > SUB_TTL:
                continue
            with open(p) as f:
                seen.append(json.load(f).get("msgs") or [])
        return seen[0] if seen and all(x == seen[0] for x in seen) else []
    except Exception:
        return []


def scope(h, agent):
    """(turn_msgs, sub) for one hook event: the parent's own turn, or a helper's. A helper is scoped by the turn that
    LAUNCHED it: its binding, else (a foreground helper, or a first call that raced its launch's PostToolUse) the launch
    still in flight. Never by the parent's CURRENT turn, which may be another thread's by now (medic 12186): with
    neither, the scope is [] and a scoped reader shows nothing."""
    aid = h.get("agent_id")
    if not aid:
        return turn_msgs(h.get("transcript_path"), agent), None
    b = _bound(agent, aid)
    sub = {"id": str(aid)[:12], "type": (h.get("agent_type") or (b or {}).get("type") or "")[:40]}
    if b and b.get("desc"):
        sub["desc"] = b["desc"]
    return (b.get("msgs", []) if b else _launching(agent)), sub


def step_meta(base, msgs, sub=None):
    """steps.meta: the ledger's (a Jsonb or None) plus the turn's opening msg_ids and, for a helper's step, who it is."""
    if not msgs and not sub:
        return base
    try:
        from psycopg.types.json import Jsonb
        d = dict(base.obj) if base is not None else {}
        if msgs:
            d["turn_msgs"] = msgs
        if sub:
            d["sub"] = sub
        return Jsonb(d)
    except Exception:
        return base


def wall_label(cmd) -> str:
    """The public label for a description-less Bash call. It must never raise, and it must never
    fall back to the command itself."""
    try:
        from nucleus.toolreg import command_label
        return command_label(cmd) if isinstance(cmd, str) else "(command)"
    except Exception:
        return "(command)"


def dsn() -> str:
    """The org's .env line, through the ONE resolver (plan-11324 S3a): the file only, as before; raises if absent."""
    from astryx import config, paths
    return config.dsn(paths.estate(__file__) / ".env", env_first=False)


WITHHELD = "[withheld: secret redaction unavailable]"


def cleaner():
    """(clean(obj), ok). clean redacts every declared secret; when the set can't be derived it
    replaces every string with WITHHELD, so nothing unredacted is ever written."""
    try:
        from nucleus.secretset import redact, secret_set
        from nucleus.ear_fence import redact as unfence      # a fetched room span keeps its pointer, never its words
        secrets = secret_set()
        return (lambda o: unfence(redact(o, secrets))), True
    except Exception:
        def withhold(o):
            if isinstance(o, str):
                return WITHHELD if o else o
            if isinstance(o, dict):
                return {k: withhold(v) for k, v in o.items()}
            if isinstance(o, (list, tuple)):
                return type(o)(withhold(x) for x in o)
            return o
        return withhold, False


def secret_guard(tool, ti):
    """(deny_reason | None, error | None). The guard's unknown is ALLOW: it is an actuator on every
    tool call of every agent, so failing closed would block the fleet at once (a2 #27600)."""
    try:
        from nucleus.secret_guard import decide
        return decide(tool, ti), None
    except Exception as e:
        return None, f"secret guard unevaluable ({type(e).__name__}): allowed (plan-5497)"


def grep_guard(command, cwd):
    """(deny_reason | None, error | None). A recursive plain grep rooted above a .gitignore silently skips the
    gitignored estate (#12548/#40752). Same polarity as secret_guard: its unknown is ALLOW."""
    try:
        from nucleus.grep_guard import decide
        return decide(command, cwd), None
    except Exception as e:
        return None, f"grep guard unevaluable ({type(e).__name__}): allowed"


def is_tool_result(content) -> bool:
    return isinstance(content, list) and any(
        isinstance(c, dict) and c.get("type") == "tool_result" for c in content)


def parse_source(prompt):
    """(source, input_msg_id) from a channel-wrapped prompt, else ('user', None)."""
    if not isinstance(prompt, str) or "<channel" not in prompt[:40]:
        return "user", None
    mid = re.search(r'msg_id="(\d+)"', prompt)
    frm = re.search(r'from="([^"]+)"', prompt)
    intent = re.search(r'intent="([^"]+)"', prompt)
    f = frm.group(1) if frm else ""
    it = intent.group(1) if intent else ""
    src = "trigger" if (f.startswith("pulse") or it == "trigger") else "wire"
    return src, (int(mid.group(1)) if mid else None)


def usage_snapshot(cur):
    """Throttled, wire-safe account-usage snapshot for this turn -> Jsonb | None.

    THROTTLE on the last snapshot's age across the whole org (any state counts, so a down
    endpoint is not retried every turn either). Any failure returns None so the turn still
    writes — usage telemetry must never cost an agent its turn record."""
    try:
        cur.execute("SELECT ended_at FROM turns WHERE usage_snapshot IS NOT NULL "
                    "ORDER BY ended_at DESC LIMIT 1")
        row = cur.fetchone()
        if row and row[0]:
            if (datetime.now(timezone.utc) - row[0]).total_seconds() < USAGE_THROTTLE_S:
                return None
        from nucleus.usage_refresh import snapshot
        snap = snapshot(timeout=4)
        if not snap:
            return None
        from psycopg.types.json import Jsonb
        return Jsonb(snap)
    except Exception:
        return None


LAPTOP_OMITTED = "[hands laptop output omitted]"
TYPED_OMITTED = "[typed text omitted]"
PHONE_OMITTED = "[phone output omitted: not a public screen]"
PHONE_STAMP = "astryx-surface: "        # mcp/phone/server.py ends EVERY answer with this block


def _phone_public(content) -> bool:
    """A phone tool result is kept only if its LAST block is the facade's surface stamp saying tier "org"
    (plan-8675 C3). Anything else, including no stamp, an unparseable one or a string body, is not public."""
    if not isinstance(content, list) or not content:
        return False
    last = content[-1]
    if not (isinstance(last, dict) and last.get("type") == "text"
            and str(last.get("text", "")).startswith(PHONE_STAMP)):
        return False
    try:
        return json.loads(last["text"][len(PHONE_STAMP):]).get("tier") == "org"
    except (ValueError, AttributeError):
        return False


def strip_pixels(obj, _laptop_ids=None, _phone_ids=None):
    """No image is ever KEPT in turns (a3 #42085 L1). The agent saw it (that's its context, the
    owner's choice); the DB, every pg_dump and every branch_check clone don't keep it: a
    screenshot of the owner's real screen is his WhatsApp, his family, whatever was open. Each
    image block becomes {"type": "image_omitted", "sha256", "bytes"}. And a hands tool result
    taken on screen="laptop" keeps no TEXT body either: an act() answer names his windows."""
    import hashlib
    if _laptop_ids is None:
        _laptop_ids, _phone_ids = set(), set()
        def find(o):
            if isinstance(o, dict):
                if (o.get("type") == "tool_use" and str(o.get("name", "")).startswith("mcp__hands__")
                        and (o.get("input") or {}).get("screen") != "background"):
                    _laptop_ids.add(o.get("id"))
                if o.get("type") == "tool_use" and str(o.get("name", "")).startswith("mcp__phone__"):
                    _phone_ids.add(o.get("id"))
                for v in o.values():
                    find(v)
            elif isinstance(o, list):
                for v in o:
                    find(v)
        find(obj)
    if isinstance(obj, list):
        return [strip_pixels(v, _laptop_ids, _phone_ids) for v in obj]
    if not isinstance(obj, dict):
        return obj
    if obj.get("type") == "image":
        src = obj.get("source") or {}
        data = src.get("data") or obj.get("data") or ""
        raw = data.encode() if isinstance(data, str) else bytes(data)
        return {"type": "image_omitted", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    if (obj.get("type") == "tool_use" and str(obj.get("name", "")).startswith("mcp__hands__")
            and (obj.get("input") or {}).get("action") in ("type", "key", "do")):
        # "do" carries a whole script that can type anything anywhere in it (a3 #42362 R1)
        # what an agent TYPES can be a password from his Chromium (owner, 10-10: full access):
        # never kept, on any screen
        inp = {**obj["input"], "text": TYPED_OMITTED}
        return {**obj, "input": inp}
    if (obj.get("type") == "tool_use" and str(obj.get("name", "")).startswith("mcp__phone__")
            and (obj.get("input") or {}).get("action") == "type"):
        # what an agent types on a phone can be a password or a one-time code: never kept
        return {**obj, "input": {**obj["input"], "text": TYPED_OMITTED}}
    if obj.get("type") == "tool_result" and obj.get("tool_use_id") in _laptop_ids:
        return {**{k: v for k, v in obj.items() if k != "content"}, "content": LAPTOP_OMITTED}
    if obj.get("type") == "tool_result" and obj.get("tool_use_id") in (_phone_ids or ()) \
            and not _phone_public(obj.get("content")):
        return {**{k: v for k, v in obj.items() if k != "content"}, "content": PHONE_OMITTED}
    return {k: strip_pixels(v, _laptop_ids, _phone_ids) for k, v in obj.items()}


def _label(agent):
    """(label, None) for this agent's session, or (None, reason) when its grant is malformed (plan-9139 S1b). An ORG
    agent reads (frozenset(), None) and keeps today's path byte for byte."""
    from nucleus import release
    try:
        return release.label_of(agent), None
    except release.Refused as e:
        return None, f"malformed grant ({type(e).__name__})"


# ── plan-9139 S1d: the session side ──────────────────────────────────────────────────────────────────────────────
# A session of an agent whose charter grants owner_private:<tier> is TIER-LABELLED for its whole life (v4 D2a: the
# identity is the role; a1 F1/F2, a2 G3: the unit is the session, monotone). Its steps and turns keep METADATA only:
# tool name, kind, ids, counts, tokens, usage, the tool-identity meta. Every text a tool, a prompt or the model wrote is
# withheld AT THE WRITE (the auto-deliver release still gets the full reply). A label that can't be read (no charter,
# a malformed grant, anything raising) strips too: an unknown label is private (D2, arm vi).
MARK = "tier-labelled session"
SPAWN_TOOLS = frozenset({"Agent", "Task", "Workflow"})     # tools that start another model session


def _strip_reason(agent):
    """None for an ORG session; else why this session's text is withheld. Never raises."""
    try:
        from nucleus import release                # THIS hook's tree's agents/: the live one in production, and a
        from astryx import paths                   # fixture tree's own when a test runs a copy of the hook (its
        return MARK if release.label_of(agent, paths.estate(__file__) / "agents") else None   # HOME's on multi-org)
    except Exception as e:  # noqa: BLE001 — UnknownLabel, GrantError, an import that fails: all private
        return f"{MARK} (label unreadable: {type(e).__name__})"


def _cli_names():
    """The binary names a child session could be started by, DERIVED (seed #45086): spawn.sh's own `CLI=${ASTRYX_CLI:-x}`
    default, plus ASTRYX_CLI as this process sees it; basenames. Never empty: the known default if nothing reads."""
    names = set()
    try:
        m = re.search(r'^CLI=\$\{ASTRYX_CLI:-([^}]+)\}', open(REPO + "/scripts/spawn.sh").read(), re.M)
        if m:
            names.add(m.group(1).strip().strip('"').split()[0])
    except (OSError, IndexError):
        pass
    if os.environ.get("ASTRYX_CLI", "").split():
        names.add(os.environ["ASTRYX_CLI"].split()[0])
    return {os.path.basename(n) for n in names if n} or {"claude"}


def spawn_guard(tool, ti, strip):
    """A deny reason when a TIER-LABELLED session would start a child session, else None (seed #45086 4b: REFUSE, don't
    inherit; a child gets a new session id and the label can't follow it). The Agent/Task/Workflow tools, or a Bash
    command any of whose words is the CLI binary. Accident grade: `grep claude` is denied too, and an indirection
    through another program (station.py, tools.run) is S2's server-side verb set."""
    if not strip:
        return None
    if tool in SPAWN_TOOLS:
        return f"a {MARK} can't start a child session ({tool}): the label can't follow it (plan-9139 S1d)"
    if tool == "Bash":
        cmd = (ti or {}).get("command") or ""
        words = {os.path.basename(w) for w in re.split(r"[\s;|&()`$<>'\"=]+", cmd) if w}
        hit = sorted(words & _cli_names())
        if hit:
            return f"a {MARK} can't run {hit[0]}: a child session would carry none of its label (plan-9139 S1d)"
    return None


def _labelled_auto_deliver(cur, agent, lbl, why, src, last_text, turn_id):
    """A LABELLED member's forgotten reply goes through the one door (nucleus/release.py), never a raw INSERT
    (v4 D1: AUTO-DELIVER is a seat). Refused (no key, no owner-only route, a person's address, a bad grant) → NO
    row, a metadata-only error step, and one constant-text notice through the same door so the owner doesn't stare
    at a frozen bubble (a4 #46035 note 3). The notice carries a reason CLASS, never content."""
    from nucleus import release
    reason = why
    if not reason:
        import contextlib
        sp = getattr(getattr(cur, "connection", None), "transaction", None)
        try:                             # a SAVEPOINT: a failed labelled write must not abort the turn's own row
            with (sp() if sp else contextlib.nullcontext()):
                rid = release.send_row(cur, agent, lbl, src[0], src[2], "chat", last_text, key=release.mac_key(),
                                       store=release.TierStore(), routes=release.declared_routes())
                cur.execute("UPDATE messages SET turn_id=%s WHERE id=%s", (turn_id, rid))
            return
        except release.Refused as e:
            reason = type(e).__name__ if type(e) is not release.Refused else "refused"
            reason = f"{reason}: {str(e)[:80]}"
        except Exception as e:  # noqa: BLE001 — any other failure is a withheld reply, never a raw INSERT
            reason = f"error: {type(e).__name__}"
    cur.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,'error',%s)",
                (agent, f"auto-deliver withheld (plan-9139): {reason}"))
    if lbl:
        try:
            release.send_row(cur, agent, lbl, "owner", None, "chat", "a private reply was withheld: " +
                             reason.split(":")[0], key=release.mac_key(), store=release.TierStore(),
                             routes=release.declared_routes())
        except release.Refused:
            pass                         # no key or no route: the notice can't go either; the error step stands


def handle_stop(cur, agent, h, strip=None):
    """Reconstruct the just-finished turn and write it. Returns (turn_id, last_text, tin, tout)."""
    try:
        with open(h["transcript_path"]) as f:
            lines = f.readlines()[-4000:]     # a single turn is never this long
    except Exception:
        return None
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except Exception:
            pass

    # find the prompt that opened this turn: the last non-tool-result user message
    start = None
    for i in range(len(events) - 1, -1, -1):
        e = events[i]
        if e.get("type") == "user" and not is_tool_result(e.get("message", {}).get("content")):
            start = i
            break
    if start is None:
        return None

    open_ev = events[start]
    input_prompt = open_ev.get("message", {}).get("content")
    if not isinstance(input_prompt, str):
        input_prompt = json.dumps(input_prompt)
    started_at = open_ev.get("timestamp")
    source, input_msg_id = parse_source(input_prompt)

    turn = [e for e in events[start:] if e.get("type") in ("user", "assistant")]
    messages, num_responses, num_tools, char_count = [], 0, 0, 0
    tin = tout = 0
    # TOKEN ACCOUNTING — two corrections, 2026-08-13, after Umair said "anthropic doesn't
    # give me this much" and was right.
    # (1) DE-DUPLICATION. A transcript carries MULTIPLE lines per assistant message id
    #     (streaming/iteration entries repeat the same usage block verbatim). Summing every
    #     line counted the same API call ~2.2x — measured on canopus: 320 usage-bearing
    #     lines, 144 distinct ids, 39.9M inflated to 18.1M real. Bill by message ID, once.
    # (2) THE SPLIT IS THE COST. input_tokens, cache_read and cache_creation price roughly
    #     1 : 0.1 : 1.25, and this org runs at ~96% CACHE READ (fresh was 0.0% of canopus's
    #     turn). Collapsing them into one `tokens_in` threw away the only distinction that
    #     tracks money, which is why a mostly-cached day read as a catastrophic one.
    # tokens_in stays the deduped total so every existing reader keeps working; the split
    # goes in raw_payload.usage, which needs no migration.
    seen_usage: dict = {}
    model = stop_reason = None
    last_text = ""
    for e in turn:
        m = e.get("message", {}) or {}
        # ONLY `message`, never the whole entry: a transcript's user entries also carry a top-level
        # `toolUseResult` copy of every tool result, which strip_pixels() doesn't walk. Storing whole
        # entries would bring back screenshots and laptop output (a3 #42104).
        messages.append({"type": e.get("type"), "ts": e.get("timestamp"), "message": m})
        if e.get("type") != "assistant":
            continue
        has_text = False
        for c in (m.get("content") or []):
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                has_text = True
                char_count += len(c.get("text", ""))
                last_text = c.get("text", "") or last_text
            elif c.get("type") == "tool_use":
                num_tools += 1
        if has_text:
            num_responses += 1
        u = m.get("usage", {}) or {}
        if u:
            # key on the message id; fall back to a content signature when absent, so an
            # id-less entry still cannot be counted twice
            key = m.get("id") or f"anon:{u.get('input_tokens')}:{u.get('output_tokens')}:{len(messages)}"
            seen_usage[key] = u
        model = m.get("model") or model
        stop_reason = m.get("stop_reason") or stop_reason

    # Fold the de-duplicated usage blocks into totals + the cost-bearing split.
    # `context` = the input side of the LAST api call in the turn — what the model actually
    # carried into its final response. This is the /context number, distinct from tokens_in
    # (which SUMS input across every call in a multi-tool turn and overstates the load).
    # Written per turn so awareness (hooks/usage.py) and the compact actuator read the DB,
    # not transcripts.
    fresh = cache_read = cache_create = cc_1h = cc_5m = context = 0
    for u in seen_usage.values():
        context = ((u.get("input_tokens") or 0)
                   + (u.get("cache_read_input_tokens") or 0)
                   + (u.get("cache_creation_input_tokens") or 0))  # last one wins
        fresh        += u.get("input_tokens") or 0
        cache_read   += u.get("cache_read_input_tokens") or 0
        cache_create += u.get("cache_creation_input_tokens") or 0
        tout         += u.get("output_tokens") or 0
        # A cache WRITE has two price tiers and they differ by 60%: a 5-minute write is
        # 1.25x base input, a 1-HOUR write is 2x (verified on platform.claude.com pricing,
        # 2026-08-13). This org writes 1-hour caches exclusively, so collapsing the two
        # under-prices every write. Kept separate so the rate table can price them apart.
        cc = u.get("cache_creation") or {}
        cc_1h += cc.get("ephemeral_1h_input_tokens") or 0
        cc_5m += cc.get("ephemeral_5m_input_tokens") or 0
    tin = fresh + cache_read + cache_create
    # Fresh-equivalent: cache reads bill ~0.1x and cache writes ~1.25x, so this is the
    # number that tracks the bill. Published multipliers, stated here so a future reader
    # can correct them in one place rather than re-deriving the arithmetic.
    # Multipliers relative to BASE INPUT, from platform.claude.com/docs/en/about-claude/pricing
    # (verified 2026-08-13): 5m write 1.25x, 1h write 2x, cache read 0.1x. Output is priced
    # separately per model and is NOT folded in here.
    billable = round(fresh + cc_5m * 1.25 + cc_1h * 2.0 + cache_read * 0.1
                     + max(0, cache_create - cc_5m - cc_1h) * 1.25)
    payload = {"messages": messages,
               "usage": {"tokens_in": tin, "tokens_out": tout,
                         "api_calls": len(seen_usage), "input_fresh": fresh,
                         "cache_read": cache_read, "cache_creation": cache_create,
                         "cache_write_1h": cc_1h, "cache_write_5m": cc_5m,
                         "billable_equiv_in": billable, "context": context}}

    duration_ms = None
    try:
        if started_at:
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            duration_ms = int((datetime.now(timezone.utc) - dt).total_seconds() * 1000)
    except Exception:
        pass

    # SECRETS: nothing below is written before it's cleaned (plan-5497 S1a). The usage block is
    # numbers only and stays exact, so a withheld turn still bills.
    clean, clean_ok = cleaner()
    payload["messages"] = clean(strip_pixels(payload["messages"]))
    input_prompt, last_text = clean(input_prompt), clean(last_text)
    if not clean_ok:
        payload["redaction"] = "unavailable"
        cur.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,'error',%s)",
                    (agent, "turn transcript withheld: secret redaction unavailable (plan-5497)"))

    if strip:                            # S1d: the turn's text never reaches the public row; the usage still bills
        payload = {"withheld": strip, "usage": payload.get("usage")}
        stored_prompt = f"[{MARK}]"
    else:
        stored_prompt = input_prompt

    from psycopg.types.json import Jsonb
    usnap = usage_snapshot(cur)          # throttled /api/oauth/usage; None most turns
    # ECONOMY ATTRIBUTION: which goal did this turn serve? Derived from the opening
    # message's thread (plan-<id>/goal-<id>) — the value-flow edge verified budgets
    # propagate back over. NULL when the turn served no goal thread; never guessed.
    goal_id = None
    if input_msg_id is not None:
        try:
            r = cur.execute(
                "SELECT (regexp_match(thread, '^(?:plan|goal)-(\\d+)$'))[1]::bigint "
                "FROM messages WHERE id=%s", (input_msg_id,)).fetchone()
            goal_id = r[0] if r else None
        except Exception:
            goal_id = None
    row = cur.execute(
        """INSERT INTO turns (agent, session_id, started_at, ended_at, duration_ms, source,
             input_prompt, input_msg_id, num_responses, num_tools, char_count,
             tokens_in, tokens_out, model, stop_reason, raw_payload, usage_snapshot, goal_id)
           VALUES (%s,%s,%s::timestamptz, now(), %s, %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (agent, h.get("session_id"), started_at, duration_ms, source,
         stored_prompt, input_msg_id, num_responses, num_tools, char_count,
         tin, tout, model, stop_reason, Jsonb(payload), usnap, goal_id)).fetchone()
    turn_id = row[0] if row else None

    # The nudge hook labels a prompt before its turn exists; claim its classification rows the
    # same way steps are claimed below. The row is written around submission, which can fall a
    # moment BEFORE the transcript's started_at, hence the slack. The previous turn's Stop has
    # already claimed its own rows. The session filter covers the cases where it hasn't: a
    # killed body, or two sessions of one agent overlapping (abstractor-4, plan-4227). A savepoint keeps a missing table (a DB that predates
    # 4227's schema) from aborting the turn row it's riding with.
    if turn_id is not None and started_at:
        try:
            with cur.connection.transaction():
                cur.execute(
                    "UPDATE classifications SET turn_id=%s "
                    "WHERE agent=%s AND turn_id IS NULL "
                    "AND (session_id IS NULL OR session_id = %s) "
                    "AND ts >= %s::timestamptz - interval '10 seconds'",
                    (turn_id, agent, h.get("session_id"), started_at))
        except Exception:
            pass

    # back-fill this turn's rows (scoped by start time so history is untouched):
    # the tool/response steps it produced, and the messages it sent.
    if turn_id is not None and started_at:
        cur.execute(
            "UPDATE steps SET turn_id=%s WHERE agent=%s AND turn_id IS NULL AND ts >= %s::timestamptz",
            (turn_id, agent, started_at))
        cur.execute(
            "UPDATE messages SET turn_id=%s WHERE from_agent=%s AND from_org='local' "
            "AND turn_id IS NULL AND ts >= %s::timestamptz",
            (turn_id, agent, started_at))
        cur.execute("UPDATE turns SET num_steps=(SELECT count(*) FROM steps WHERE turn_id=%s) WHERE id=%s",
                    (turn_id, turn_id))

    # AUTO-DELIVER a forgotten reply. If an OWNER message opened this turn and the agent
    # produced a response but sent NOTHING back to the owner — it wrote the answer in the
    # terminal and forgot `send` (rare, but then the owner just sees the progress bubble
    # frozen at the last step) — deliver that response for it: one wire row on the SAME
    # surface the owner asked from (src thread), and the bridge's deliver() edits the live
    # bubble into the answer (reusing ph_id, split_files/polls, the fallback-to-new). Guarded
    # to OWNER-triggered turns so an internal/cron turn never auto-messages him. NO double
    # send: the back-fill above stamped this turn's real sends with turn_id, so a turn that
    # DID reply to the owner shows already>0 and is skipped.
    if turn_id and input_msg_id and last_text and last_text.strip():
        src = cur.execute("SELECT from_agent, from_org, thread FROM messages WHERE id=%s",
                          (input_msg_id,)).fetchone()
        # Fire for a HUMAN channel message — the owner OR anyone on wa/tg/discord. A person
        # whose trusted_jid is off arrives as 'wa-<num>' (not 'owner') and shows NO progress
        # bubble, so guarding on 'owner' would strand exactly them; guard on from_org being a
        # channel instead. Internal ('local') agent turns and pulse triggers never match, so
        # they can't auto-message anyone. No bubble is fine — deliver() falls back to a fresh
        # send. Reply goes BACK to that same sender on that same surface (to_agent + thread).
        if src and src[1] in ("whatsapp", "telegram", "discord"):
            already = cur.execute(
                "SELECT count(*) FROM messages WHERE turn_id=%s AND to_agent=%s",
                (turn_id, src[0])).fetchone()[0]
            if not already:
                lbl, why = _label(agent)
                if lbl or why:
                    _labelled_auto_deliver(cur, agent, lbl, why, src, last_text, turn_id)
                else:
                    cur.execute(
                        "INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, "
                        "intent, body, turn_id) VALUES (%s,'local',%s,'local',%s,'chat',%s,%s)",
                        (agent, src[0], src[2], last_text, turn_id))
    return turn_id, last_text, tin, tout


def main():
    agent = os.environ.get("ASTRYX_AGENT")
    if not agent:
        return
    try:
        h = json.load(sys.stdin)
    except Exception:
        return
    ev = h.get("hook_event_name")

    # S1d: the session's label, read ONCE and BEFORE any DB work (a down DB never opens the spawn guard or the strip)
    strip = _strip_reason(agent)

    # SECRETS (plan-5497 S1b): decided BEFORE any DB work, so a down DB never opens the guard.
    denied = guard_err = None
    if ev == "PreToolUse":
        denied, guard_err = secret_guard(h.get("tool_name", "?"), h.get("tool_input") or {})
        if not denied:
            denied = spawn_guard(h.get("tool_name", "?"), h.get("tool_input") or {}, strip)
        if not denied and h.get("tool_name") == "Bash":
            denied, gerr = grep_guard((h.get("tool_input") or {}).get("command") or "", h.get("cwd"))
            guard_err = guard_err or gerr
        if denied:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": denied}}), flush=True)

    import psycopg
    with psycopg.connect(dsn(), connect_timeout=3) as conn:
        cur = conn.cursor()

        if ev == "PreToolUse":
            tool = h.get("tool_name", "?")
            ti = h.get("tool_input") or {}
            # NEVER the raw command: steps are public and memory's nightly drain feeds them
            # into RAG, and a command's arguments are where a secret lands (an inlined DSN, a
            # PGPASSWORD=… prefix). A description-less Bash call shows WHAT ran (its registry
            # id, else the program name) and none of its arguments. seed approved, plan-4227.
            detail = ti.get("description") or ti.get("file_path") \
                or ti.get("to") or ti.get("target") or ""
            if not detail and tool == "Bash":
                detail = wall_label(ti.get("command"))
            detail = cleaner()[0](detail)      # a description can quote a secret too
            if strip:                          # S1d: a description, a path, a target are the session's text
                detail = f"[{MARK}]"
            if denied:
                detail = f"DENIED, {'child spawn' if strip and denied.startswith('a ' + MARK) else 'secret holder'}: " \
                         f"{brief(detail, 200)}"
            msgs, sub = scope(h, agent)
            if tool in ("Agent", "Task"):                      # a helper is being launched from this scope
                launch_open(agent, h.get("tool_use_id"), msgs)
            cur.execute("INSERT INTO steps (agent, kind, content, meta) VALUES (%s,'tool',%s,%s)",
                        (agent, f"{tool}: {brief(detail)}", step_meta(ledger_meta(tool, ti), msgs, sub)))
            if guard_err:
                cur.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,'error',%s)",
                            (agent, guard_err))

        elif ev == "PostToolUse":
            tool = h.get("tool_name", "?")
            r = h.get("tool_response")
            msgs, sub = scope(h, agent)
            meta = step_meta(ledger_meta(tool, h.get("tool_input") or {}, r if r is not None else ""), msgs, sub)
            if tool in ("Agent", "Task"):
                if isinstance(r, dict) and r.get("agentId"):   # a helper launched: bind it, then close the launch
                    ti2 = h.get("tool_input") or {}
                    at = launch_scope(agent, h.get("tool_use_id"))   # the scope AT launch, not recomputed now (12189)
                    bind_sub(agent, r["agentId"], msgs if at is None else at, ti2.get("description"), ti2.get("subagent_type"))
                launch_close(agent, h.get("tool_use_id"))
            err = r.get("error") or ("" if r.get("success", True) else "failed") \
                if isinstance(r, dict) else ""
            if err:
                # The error TEXT is tool output (a Bash failure carries its stderr), so it's the
                # same class as the raw command: the wall records THAT the call failed, not what
                # it printed. (Zero error rows exist today; this closes it before one does.)
                cur.execute("INSERT INTO steps (agent, kind, content, meta) VALUES (%s,'error',%s,%s)",
                            (agent, f"{tool}: failed", meta))
            else:
                cur.execute("INSERT INTO steps (agent, kind, content, meta) VALUES (%s,'tool_done',%s,%s)",
                            (agent, f"{tool} done", meta))
            # EFFORT, FELT (owner 11-15: "agents should know they are consuming too much through econ to stop. no switch
            # or threshold"): at each doubling of its usual turn the agent is told what this turn has taken and how the
            # org feels; it decides. The step is committed first, so nothing here can cost it. Fail-open.
            conn.commit()
            if not sub and not strip and h.get("transcript_path"):
                try:
                    from astryx.econ import energy as _energy
                    said = _energy.during(conn, agent, h["transcript_path"])
                    if said:
                        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                                 "additionalContext": said}}), flush=True)
                except Exception:  # noqa: BLE001
                    pass

        elif ev == "Stop":
            launch_close(agent)                        # the turn ended: no launch of it is still in flight
            res = handle_stop(cur, agent, h, strip)
            # short response step for the wall/status line (full text lives in turns)
            if res:
                turn_id, last_text, tin, tout = res
                cur.execute(
                    "INSERT INTO steps (agent, kind, content, turn_id, tokens_in, tokens_out) "
                    "VALUES (%s,'response',%s,%s,%s,%s)",
                    (agent, (f"[{MARK}: {len(last_text.encode())} bytes]" if strip
                             else (last_text[:2000] or "(tool-only turn)")), turn_id, tin, tout))
            else:
                cur.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,'response',%s)",
                            (agent, "(turn unreadable)"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a broken hook must never break the agent
