"""astryx whatsapp bridge — WhatsApp as an owner surface on the wire.

Platform translation ONLY; everything shared lives in common.py:

  inbound   wacli webhook (HMAC-signed) -> row INSERT into messages -> native
            channel delivery wakes the agent
  outbound  agent `send`s to the surface identity -> wire doorbell -> wacli
            send -> row marked delivered. WhatsApp is the owner's HOME surface:
            un-threaded owner-bound messages deliver here (tg:/dc: threads are
            the other bridges' and are skipped).
  progress  the agent's hook steps render as a typing indicator plus one
            message edited per event. Purely event-driven; edits serialized
            per job and coalesced to the latest step (WhatsApp round-trip is
            the pacing, not a timer). Edits only work ~15 min — deliver()
            falls back to a fresh message.
  media     inbound attachments land in media/; audio arrives transcribed.
            Outbound [[file:/abs/path]] ships the file via the store outbox.
  polls     [[poll:]] -> wacli send poll; creations AND votes recorded in the
            shared `polls` table whoever sent them (FromMe included — a vote
            from the linked phone must still count); votes wake the ASKING
            agent with the delta.

Config: .env for secrets, routes-whatsapp.json for chats (trusted_jids =
sender JIDs stamped `owner`; others are `wa-<number>` on open routes).

Run: uvicorn bridges.whatsapp:app --host 172.17.0.1 --port 8477  (repo root)
"""

import asyncio
import hashlib
import hmac
import json
import os
import re
import shlex
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
from fastapi import FastAPI, Request, Response

from .common import (HERE, MEDIA_DIR, Outcome, route_target, describe_media,
                     env, listen, load_routes,
                     record_poll, split_files, split_polls, step_line,
                     update_poll_votes, vote_body, vote_changes, wire_insert)
from .providers.whatsapp import WhatsAppProvider

PROVIDER = WhatsAppProvider()          # wacli send logic

DSN = env("ASTRYX_DSN")
SECRET = env("WA_WEBHOOK_SECRET").encode()
WA_CLI = shlex.split(env("WA_CLI", "docker exec wacli-sync wacli"))
DATA_HOST = env("WA_DATA_HOST")       # wacli store dir on the host (media on/off switch)
DATA_CTR = env("WA_DATA_CTR", "/data")    # same dir as the wacli process sees it
WA_DOCKER = WA_CLI[2] if WA_CLI[:2] == ["docker", "exec"] else ""
ROUTES_FILE = HERE / "routes-whatsapp.json"

JOB_TIMEOUT = 1800    # lifecycle GC only: forget a job nobody answered in 30 min

pool: asyncpg.Pool | None = None
seen_msgids: dict[str, float] = {}       # webhook dedup (wacli retries)
jobs: dict[str, dict] = {}               # agent -> live progress job


def routes() -> list[dict]:
    return load_routes(ROUTES_FILE)


#: A destination we can address DETERMINISTICALLY: a WhatsApp JID, or a bare phone number.
#: Anything else is a NAME, and a name is resolved by wacli against the mutable contact
#: store — impure, and the vector for the 2026-07-25 misdelivery. See deliver().
_ADDRESSABLE = re.compile(r"^\d{5,20}(@(s\.whatsapp\.net|g\.us|lid))?$")


def _is_addressable(chat: str) -> bool:
    return bool(_ADDRESSABLE.match((chat or "").strip()))


def jid_str(v) -> str:
    if isinstance(v, dict):
        return f"{v.get('User', '')}@{v.get('Server', '')}"
    return str(v or "")


async def wacli(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *WA_CLI, *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        # a failed call must fail loudly; a silent non-zero exit hides a lost send
        raise RuntimeError(f"wacli {' '.join(args[:2])}: "
                           f"{err.decode(errors='replace').strip()[:200]}")
    return out.decode(errors="replace")


def find_id(obj) -> str | None:
    """Fish a message id out of whatever JSON shape wacli returns."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() == "id" and isinstance(v, str) and v:
                return v
            got = find_id(v)
            if got:
                return got
    if isinstance(obj, list):
        for v in obj:
            got = find_id(v)
            if got:
                return got
    return None


# ---------------------------------------------------------------------- media
async def fetch_media(chat: str, msgid: str, media: str) -> Path | str:
    """Inbound attachment -> host Path (or an excuse string). sync
    --download-media already saves every file under store/media/<chat>/<msgid>/,
    so no second download (and no store-lock contention): we wait for it."""
    if not DATA_HOST:
        return f"<{media} attached, media dir not configured>"
    rel = f"store/media/{chat.replace('@', '_')}/{msgid}"
    base = Path(DATA_HOST) / rel
    for _ in range(20):
        try:
            files = [p for p in base.rglob("message-*") if os.access(p, os.R_OK)]
        except PermissionError:
            files = []
        if files:
            return files[0]
        if WA_DOCKER:                      # store unreadable from host: copy out
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "exec", WA_DOCKER, "sh", "-c",
                    f"ls {DATA_CTR}/{rel}/*/message-* 2>/dev/null | head -1",
                    stdout=asyncio.subprocess.PIPE)
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                ctr_path = out.decode().strip()
                if ctr_path:
                    MEDIA_DIR.mkdir(exist_ok=True)
                    dst = MEDIA_DIR / Path(ctr_path).name
                    with open(dst, "wb") as f:
                        proc = await asyncio.create_subprocess_exec(
                            "docker", "exec", WA_DOCKER, "cat", ctr_path, stdout=f)
                        await asyncio.wait_for(proc.wait(), timeout=30)
                    if dst.stat().st_size > 0:
                        return dst
            except Exception:
                pass
        await asyncio.sleep(1)
    return f"<{media} attached, file never landed in the store>"


async def send_files(chat: str, files: list[str], out: Outcome | None = None):
    """Attachments. `out` is optional so existing callers keep working; when supplied,
    every skipped or failed upload reaches the receipt instead of vanishing."""
    def _fail(detail):
        if out is not None:
            out.failed("file", detail)
    if not DATA_HOST:
        if files and out is not None:
            # NOT a failure: WA_DATA_HOST unset is the documented media on/off switch for
            # this surface (see :55), i.e. an operator decision, not broken config. The
            # text portion genuinely delivered, so failing the row here would install a
            # false failure. But the caller did attach something that was silently
            # dropped, so it is REPORTED. (gemini, msg 5981.)
            out.noted("file", f"media disabled on this surface (WA_DATA_HOST unset) — "
                              f"{len(files)} attachment(s) not sent")
        return
    outbox = Path(DATA_HOST) / "astryx-outbox"
    outbox.mkdir(exist_ok=True)
    for f in files:
        src = Path(f)
        if not src.is_file():
            # Was a silent `continue`, while the body still said "attached".
            _fail(f"path not found: {f}")
            continue
        dst = outbox / f"{int(time.time())}-{src.name}"
        try:
            shutil.copy(src, dst)
            await wacli("send", "file", "--to", chat,
                        "--file", f"{DATA_CTR}/astryx-outbox/{dst.name}")
        except Exception as e:
            _fail(e)


# ---------------------------------------------------------------------- polls
async def send_poll(chat: str, agent: str, question: str, options: list[str], multi: int):
    args = ["--json", "send", "poll", "--to", chat, "--question", question]
    for o in options:
        args += ["--option", o]
    if multi != 1:
        args += ["--multi", str(multi)]
    pid = find_id(json.loads(await wacli(*args)))
    # GEMINI, msg 4669 (its hunk, kept verbatim in intent): a poll that lands but never
    # records is one whose votes can never come back to its author — the vote-return path
    # keys on the polls row, so `if pid:` silently conditioned the entire feedback loop on
    # a value that can be absent without error.
    if not pid:
        raise RuntimeError("wacli returned no message id for the poll — not recorded, "
                           "so its votes can never return to the sender")
    await record_poll(pool, pid, chat, agent, question, options, multi)


async def refresh_poll(chat: str, pid: str) -> tuple[dict, dict] | None:
    """Pull live state from wacli's store and persist it; returns
    (new_state, previous_votes) for delta reporting."""
    try:
        d = (json.loads(await wacli("--json", "poll", "show", "--to", chat,
                                    "--id", pid)) or {}).get("data")
    except Exception:
        d = None
    if not d:
        return None
    await pool.execute(
        """INSERT INTO polls (msg_id, chat, agent, question, options, multi, votes)
           VALUES ($1,$2,NULL,$3,$4,$5,'{}')
           ON CONFLICT (msg_id) DO UPDATE SET question=EXCLUDED.question,
             options=EXCLUDED.options, multi=EXCLUDED.multi""",
        pid, chat, d.get("question", ""), json.dumps(d.get("options", [])),
        d.get("selectable_count", 1) or 1)
    old = await update_poll_votes(pool, pid, d.get("aggregates", {}),
                                  d.get("voters", []))
    return d, old


# -------------------------------------------------------------------- inbound
app = FastAPI()


@app.get("/health")
async def health():
    return {"ok": True, "routes": len(routes()), "jobs": list(jobs)}


@app.post("/hook")
async def hook(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Wacli-Signature", "")
    want = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
    if not SECRET or not hmac.compare_digest(sig, want):
        return Response(status_code=403)
    try:
        m = json.loads(body)
    except json.JSONDecodeError:
        return Response(status_code=400)

    chat = jid_str(m.get("Chat"))
    route = next((r for r in routes() if r.get("chat") == chat), None)
    if route is None:
        return {"ok": True}                       # not a surface we serve

    msgid = m.get("ID") or ""
    now = time.time()
    for k in [k for k, t in seen_msgids.items() if now - t > 3600]:
        del seen_msgids[k]
    if msgid and msgid in seen_msgids:
        return {"ok": True}
    seen_msgids[msgid] = now

    # ---- polls: bookkeeping runs BEFORE the FromMe drop — a vote cast from the
    # linked phone itself arrives as FromMe and must still count.
    pv = m.get("PollVote") or {}
    if pv.get("PollMessageID"):
        pid = pv["PollMessageID"]
        res = await refresh_poll(chat, pid)
        if res:
            d, old = res
            rec = await pool.fetchrow("SELECT agent FROM polls WHERE msg_id=$1", pid)
            ask = (rec and rec["agent"]) or route["agent"]
            changes = vote_changes(old, d.get("voters", []))
            voter_jid = jid_str(m.get("SenderJID"))
            sender = "owner" if voter_jid in route.get("trusted_jids", []) \
                else f"wa-{''.join(c for c in voter_jid.split('@')[0] if c.isdigit()) or 'x'}"
            await wire_insert(pool, sender, "whatsapp", ask, f"wa:{chat}", "poll",
                              vote_body(d.get("question", "?"), changes,
                                        d.get("aggregates", {})))
        return {"ok": True}
    pc = m.get("Poll") or {}
    if pc.get("Question") and msgid:
        # record any poll posted on a routed surface, whoever created it
        await record_poll(pool, msgid, chat, None, pc.get("Question", ""),
                          pc.get("Options", []), pc.get("SelectableCount", 1) or 1)
        if m.get("FromMe"):
            return {"ok": True}
        # a human posted a poll at the agent: deliver it as readable chat
        sender_jid = jid_str(m.get("SenderJID"))
        await wire_insert(
            pool,
            "owner" if sender_jid in route.get("trusted_jids", []) else "wa-x",
            "whatsapp", route["agent"], f"wa:{chat}", "poll",
            f'posted a poll ({msgid}): "{pc.get("Question")}" — '
            + " | ".join(pc.get("Options", [])))
        return {"ok": True}

    if m.get("FromMe"):
        return {"ok": True}                       # our own sends echo back; drop

    text = (m.get("Text") or "").strip()
    # media rides as a nested object in the webhook payload: Media.Type
    media = ((m.get("Media") or {}).get("Type") or m.get("MediaType") or "").strip()
    if media and msgid:
        got = await fetch_media(chat, msgid, media)
        got = await describe_media(got, media) if isinstance(got, Path) else got
        text = f"{text}\n{got}" if text else got
    if not text:
        # Reactions arrive as non-text events; wacli's payload shape isn't confirmed
        # yet — log one so the handler can be wired to the real shape.
        blob = json.dumps(m)
        if "eact" in blob:
            print(f"wa reaction webhook — keys={list(m)} payload={blob[:400]}", flush=True)
        return {"ok": True}

    sender_jid = jid_str(m.get("SenderJID"))
    trusted = sender_jid in route.get("trusted_jids", [])
    if trusted:
        sender = "owner"
    else:
        if not route.get("open"):                 # closed surface: trusted only
            return {"ok": True}
        digits = "".join(c for c in sender_jid.split("@")[0] if c.isdigit())
        sender = f"wa-{digits or 'unknown'}"
        text = f"{m.get('PushName') or sender_jid}: {text}"

    agent, text = await route_target(pool, f"wa:{chat}", text, route["agent"])

    await wire_insert(pool, sender, "whatsapp", agent, f"wa:{chat}", "chat", text)

    if route.get("live_steps") and trusted:
        jobs[agent] = {"chat": chat, "thread": f"wa:{chat}", "opened": now,
                       "ph_id": None, "latest": "", "sent": "", "busy": False}
        asyncio.get_event_loop().create_task(typing(chat))
    return {"ok": True}


async def typing(chat: str):
    try:
        await wacli("presence", "typing", "--to", chat)
    except Exception:
        pass


# ------------------------------------------------------------------- progress
async def on_step(ev: dict):
    """A hook event landed for an agent with an open job. No clocks here: every
    event updates the target line and pokes the worker; the worker coalesces."""
    agent = ev.get("agent", "")
    job = jobs.get(agent)
    if not job:
        return
    if time.time() - job["opened"] > JOB_TIMEOUT:
        jobs.pop(agent, None)
        return
    line = await step_line(pool, int(ev.get("id", 0)), ev.get("kind", ""), agent)
    if not line:
        return
    job["latest"] = line
    if not job["busy"]:
        asyncio.get_event_loop().create_task(worker(agent))


async def worker(agent: str):
    """Serialized editor for one job: always pushes the latest line, skipping
    intermediates. WhatsApp round-trip time is the only rate limit."""
    job = jobs.get(agent)
    if not job or job["busy"]:
        return
    job["busy"] = True
    try:
        while job is jobs.get(agent) and job["latest"] != job["sent"]:
            line = job["latest"]
            await typing(job["chat"])
            try:
                if job["ph_id"] is None:
                    out = await wacli("--json", "send", "text",
                                      "--to", job["chat"], "--message", line)
                    try:
                        job["ph_id"] = find_id(json.loads(out))
                    except Exception:
                        pass
                else:
                    await wacli("messages", "edit", "--chat", job["chat"],
                                "--id", job["ph_id"], "--message", line)
            except Exception:
                pass
            job["sent"] = line
    finally:
        job["busy"] = False


# ------------------------------------------------------------------- outbound
_skipped_threads: set = set()

# The owner doorbell's HOME surface, pinned by NAME (forge, plan-2457 msg 13041). The
# un-routed fallback used to be `next(iter(routes()))` — the FIRST route positionally —
# so reordering routes-whatsapp.json (an edit that looks like formatting) would have
# silently moved every un-routed owner-bound message: both org-dark alarms redirecting
# to the career seat's direct number, or worse, the FAMILY group at index 2. Nothing
# pinned it. Same family as the 2026-07-25 name-fuzzy misdelivery documented above,
# arriving through ordering instead of matching. The seed route IS the designed owner
# surface (owner.md: he reads the org in the group); if it is ever absent, this
# REFUSES rather than guesses — a doorbell rotting pending is caught by
# doorbell_proof, a doorbell delivered to the family group is caught by nobody.
HOME_AGENT = "seed"


async def deliver(row):
    """Deliver a wire message to WhatsApp and record the outcome in the row's
    `delivery` field, so a send awaiting this result can read where it landed."""
    thread = row["thread"] or ""
    if thread[:3] in ("tg:", "dc:") or (row["to_agent"] or "")[:3] in ("tg-", "dc-"):
        return                       # another bridge's surface (telegram/discord)
    if thread.startswith("wa:"):
        chat = thread[3:]            # the thread carries the destination
        if not _is_addressable(chat):
            # REFUSE a name. wacli's --to accepts "recipient JID, phone, OR contact/group/
            # chat name" and FUZZY-MATCHES the last kind against the mutable contact store.
            # On 2026-07-25 `thread='wa:owner'` therefore resolved to a saved contact whose
            # name merely contained "owner", and a career-tier brief was delivered to a THIRD
            # PARTY. Everything upstream of this line is honest — the routes table matches
            # agents exactly — but this branch never consults it: the destination arrives
            # verbatim in the thread and went straight to the CLI unvalidated.
            # A JID or a bare phone number is a PURE FUNCTION of its input; a name is resolved
            # against a store that changes underneath us, so the same string can address a
            # different person tomorrow. Refusing here converts the org's worst outbound
            # failure from detection-after-the-fact into prevention, at the only place that
            # can see it. Fail CLOSED: we do not guess a destination for a message we cannot
            # address safely — a misdelivered tier-private message cannot be recalled.
            err = (f"unaddressable destination {chat!r}: not a JID or phone number. wacli "
                   f"would fuzzy-match it against saved contacts and could deliver to the "
                   f"wrong person (as it did 2026-07-25). Address explicitly — "
                   f"wa:<digits>@s.whatsapp.net or wa:<digits>@g.us — or send un-threaded "
                   f"to use the sending agent's home route.")
            print(f"whatsapp: REFUSED outbound msg {row['id']} — {err}", flush=True)
            await pool.execute(
                "UPDATE messages SET status=$2, delivered_at=now(), delivery=$3 WHERE id=$1",
                row["id"], "dead",
                json.dumps({"ok": False, "handle": f"whatsapp:{chat}",
                            "message_id": None, "rendered": None, "error": err}))
            return
    elif thread and not thread.startswith("t-"):
        # `t-…` is EXEMPT because it is not a named surface: the wire's send tool
        # auto-mints a t-thread when an agent names none, so "send to the owner,
        # un-threaded" arrives here AS a t-thread. The first cut of this fix skipped
        # those too — and the very message announcing the fix was refused by it (msg
        # 8125, caught by its own delivery probe): every owner escalation, org-news
        # drop and decision request would have silently stopped reaching his phone.
        # The doorbell to the owner's configured org surface (owner.md: he reads the
        # org in the group) is a DESIGNED route, not a guess.
        #
        # A NAMED thread that is not wa: is a conversation happening SOMEWHERE ELSE —
        # an internal wire thread (t-…), the observatory's estate chat (obs:estate-…),
        # a proposals thread. Delivering it here means INVENTING a destination for a
        # message that named none, and the destination this branch invents is a GROUP.
        #
        # memory proved the consequence (2026-08-14, msgs 7988/8123): its reply on
        # `memory-proposals` — addressed to nobody on WhatsApp — landed in the ASTRYX
        # group (delivery record on msg 7987), and every estate-chat answer would have
        # taken the same path. The other two bridges already refuse threads that are
        # not theirs (telegram.py:75, discord.py:107); this branch was the one
        # bridge that guessed. Measured before removing: 3 messages in 14 days rode
        # this fallthrough, every one an internal thread that had no business on a
        # multi-party surface.
        #
        # Fail CLOSED, same law as the name-refusal above: an actuator that delivers
        # to humans does not act on an unknown destination. The cost of refusing is a
        # skipped delivery with a reason; the cost of guessing is an unrecallable
        # broadcast to the wrong audience. The UNTHREADED doorbell below is untouched —
        # a message with no thread at all is the designed "reach the owner" path.
        # The watcher re-fetches ALL pending rows on every wire event, so without
        # memory this line would repeat for the row's whole life. Once per process is
        # enough for a human reading the log; the row itself stays pending because its
        # consumer is the observatory (which marks it on serve), not this bridge.
        if row["id"] not in _skipped_threads:
            _skipped_threads.add(row["id"])
            print(f"whatsapp: skipped outbound msg {row['id']} — thread {thread!r} names "
                  f"no WhatsApp destination (internal/other-surface thread; send "
                  f"un-threaded or wa:<jid> to reach WhatsApp)", flush=True)
        return
    else:                            # UNTHREADED: the owner doorbell, by design.
        route = next((r for r in routes() if r["agent"] == row["from_agent"]), None) \
            or next((r for r in routes() if r["agent"] == HOME_AGENT), None)
        chat = route and route["chat"]
        if not chat and row["id"] not in _skipped_threads:
            _skipped_threads.add(row["id"])
            print(f"whatsapp: REFUSED un-routed doorbell msg {row['id']} — no route for "
                  f"sender {row['from_agent']!r} and no {HOME_AGENT!r} home route in "
                  f"routes-whatsapp.json; refusing to guess a destination", flush=True)
    if not chat:
        return
    agent = row["from_agent"]
    text, files = split_files(row["body"])
    text, polls = split_polls(text, max_options=12)
    out = Outcome()
    try:
        job = jobs.pop(agent, None)
        while job and job["busy"]:                # let an in-flight edit finish
            await asyncio.sleep(0.2)
        sent = False
        if text and job and job["chat"] == chat and job["ph_id"] and len(text) < 3500:
            try:                                  # reuse the live progress bubble
                await wacli("messages", "edit", "--chat", chat,
                            "--id", job["ph_id"], "--message", text)
                out.sent(job["ph_id"])
                sent = True
            except Exception:
                pass                              # falls through to a normal send below
        if text and not sent:
            res = await PROVIDER.send(chat, text)
            if res.ok:
                out.sent(res.message_id)
            else:
                out.failed("text", res.error or "provider reported not-ok")
        await send_files(chat, files, out)
        for q, opts, multi in polls:
            try:
                await send_poll(chat, agent, q, opts, multi)
            except Exception as e:
                # GEMINI, msg 4669: was `except Exception: pass`, so a failed poll left
                # the group a question with no options and the row said delivered.
                out.failed("poll", e)
                # NO RETRACTION HERE, and the verb is not the reason — it exists.
                # `wacli messages revoke --chat <jid> --id <msgid>` is real (gemini
                # verified it against --help, msg 5981; confirmed independently here).
                # Two better reasons, both surface-specific:
                #  1. UNREACHABLE IN THIS FAILURE MODE. The trigger is find_id() returning
                #     nothing, and --id is required — so there is no id to revoke exactly
                #     when we would want to. Retraction is only reachable in the narrower
                #     case where the poll came back WITH an id and the DB write then
                #     failed, which is a different bug from the one this patch repairs.
                #  2. A REVOKE IS VISIBLE. It leaves a "This message was deleted"
                #     tombstone in the family group, in Umair's voice, in front of his
                #     family. A quietly orphaned poll is a strictly better failure on this
                #     surface than a tombstone they watch appear. Even where reachable,
                #     retraction stays OFF here by decision, not by omission.
                # Warn instead — best-effort, and its own failure must not mask the real
                # one above.
                try:
                    await PROVIDER.send(chat, (
                        f"⚠️ that poll did not register — votes on it cannot reach "
                        f"{agent}. Please reply in text instead. ({type(e).__name__})"))
                except Exception:
                    pass
        try:
            await wacli("presence", "paused", "--to", chat)
        except Exception:
            pass                                  # cosmetic only — never fails the row
    except Exception as e:
        out.failed("deliver", e)
    await pool.execute(
        "UPDATE messages SET status=$2, delivered_at=now(), delivery=$3 WHERE id=$1",
        row["id"], out.status, out.receipt(f"whatsapp:{chat}", text))


# ---------------------------------------------------------------------- app
@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    task = asyncio.create_task(listen(
        DSN, "(to_agent='owner' OR to_agent LIKE 'wa-%')", deliver, on_step))
    yield
    task.cancel()
    await pool.close()

app.router.lifespan_context = lifespan
