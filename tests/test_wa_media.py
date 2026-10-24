"""Oracle: every inbound WhatsApp file reaches the agent as a readable path beside its caption, and a
file that never lands is SAID, never dropped (canopus #62888: a captioned PDF arrived as text only).

    venv/bin/python tests/test_wa_media.py         (also run by devtools/check.sh)
    WA_SRC=<path> …                                (the subject; default bridges/whatsapp.py)

The incident, from metadata only: a document sent with a caption. wacli's webhook carried the
caption but named no media, while its store held MediaType=document and the file at
store/media/<chat>/<msgid>/document/resume.pdf. The old /hook trusted the payload alone, and the old
fetch matched only message-* (a photo's store name), so even a named document was never found.

Hermetic: no DB, no wacli, no network, no real message. A temp dir stands in for wacli's store,
wacli's `messages show` is a fake over a dict, and fetch_media's one-second polls are scaled down.
  M1 the incident: captioned PDF, payload names no media, the store does → caption + the PDF's path
  M2 captioned PDF whose payload does name it → caption + path (no second read needed)
  M3 an uncaptioned video, its own filename → the path alone
  M4 control: a photo stored as message-* (the old shape) still arrives
  M5 the file never lands → the caption AND a line saying so, one row, nothing silent
  M6 control: plain text whose store row holds no media → one row, the text alone, no file line
  M7 control: an empty reaction reads nothing from the store
  M8 a message id is the SENDER's string (a1 #62931 R1): one carrying a quote and $(…) runs no
     shell and is refused in the body; a valid id's docker copy-out is argv, never `sh -c`
  M9 an id that walks (../../x) returns and writes nothing outside the store, and says it refused
"""
import asyncio
import hashlib
import hmac
import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("WA_SRC") or REPO / "bridges" / "whatsapp.py")
os.environ["WA_WEBHOOK_SECRET"] = "oracle-secret"           # synthetic: never the real one
os.environ["ASTRYX_DSN"] = "postgresql://oracle@127.0.0.1:1/none"   # never connected
os.environ["WA_CLI"] = "false"
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_wa_media", REPO, deps=("fastapi", "asyncpg"))   # a committed-only tree: 77, not an import crash
import bridges  # noqa: E402  (the package, so the subject's relative imports resolve)
from bridges.routing import Routes  # noqa: E402

spec = importlib.util.spec_from_file_location("bridges._wa_media_subject", SUBJECT)
wa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wa)

CHAT = "wa-test-group@g.us"               # fake-in-shape ids (no digit run: privacy_gate (c))
OWNER = "wa-test-owner@lid"
ROUTE = {"chat": CHAT, "agent": "seed", "enabled": True, "open": False, "trusted_jids": [OWNER]}
CAPTION = "synthetic caption: make this better"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if not ok and detail else ""))
    if not ok:
        fails.append(name)


class Req:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()
        self.headers = {"X-Wacli-Signature": "sha256=" + hmac.new(
            b"oracle-secret", self._b, hashlib.sha256).hexdigest()}

    async def body(self):
        return self._b


def event(msgid, text="", media=None, **kw):
    return {"Chat": CHAT, "ID": msgid, "SenderJID": OWNER, "FromMe": False, "Text": text,
            "Media": {"Type": media} if media else None, "Poll": None, "PollVote": None,
            "ReactionToID": "", "ReactionEmoji": "", "Revoked": False, **kw}


_real_sleep = asyncio.sleep
# fetch_media polls 20 times a second apart; the same 20 polls, 1/100 the wait (only this module's view)
wa.asyncio = types.SimpleNamespace(**{k: getattr(asyncio, k) for k in dir(asyncio) if not k.startswith("__")})
wa.asyncio.sleep = lambda s, *a, **k: _real_sleep(s / 100, *a, **k)


class World:
    """The fakes: wacli's store (rows + a media dir), and what reached the wire."""
    def __init__(self, root):
        self.root, self.rows, self.reads, self.store = Path(root), [], 0, {}

    def put(self, msgid, kind, name, text=""):
        d = self.root / "store" / "media" / CHAT.replace("@", "_") / msgid / kind
        d.mkdir(parents=True)
        (d / name).write_bytes(b"%PDF-synthetic" if name.endswith(".pdf") else b"synthetic")
        self.store[msgid] = {"Text": text, "MediaType": kind}
        return d / name

    def install(self, docker=""):
        wa.seen_msgids.clear()
        self.execs = []

        async def exec_(*argv, **kw):              # the docker copy-out: record argv, find no file
            self.execs.append(argv)

            class P:
                async def communicate(self):
                    return b"", b""
            return P()
        wa.asyncio.create_subprocess_exec = exec_
        wa.routes = lambda: Routes([ROUTE])
        self.root.mkdir(parents=True, exist_ok=True)
        wa.DATA_HOST, wa.WA_DOCKER = str(self.root), docker

        async def wacli(*args):
            self.reads += 1
            i = args.index("--id") + 1
            return json.dumps({"success": True, "data": self.store.get(args[i], {"Text": ""})})

        async def wire_insert(pool, frm, org, to, thread, intent, body, meta=None, route=None, said=None):
            self.rows.append(body)

        async def route_target(pool, thread, text, default):
            return default, text
        wa.wacli, wa.wire_insert, wa.route_target = wacli, wire_insert, route_target
        wa.stored_text.__defaults__ = ((0.02, 0.05, 0.12),)
        return self


def attached(body):
    """The path a body's file line names, or None."""
    for line in body.splitlines():
        if line.startswith("<file attached: ") and line.endswith(">"):
            return Path(line[len("<file attached: "):-1])
    return None


async def main(tmp):
    # M1: the incident shape
    w = World(f"{tmp}/m1").install()
    pdf = w.put("ID-M1", "document", "resume.pdf", CAPTION)
    await wa.hook(Req(event("ID-M1", CAPTION)))
    body = w.rows[0] if len(w.rows) == 1 else ""
    p = attached(body)
    check("M1 the incident: a captioned PDF the payload doesn't name → ONE row", len(w.rows) == 1, f"{w.rows}")
    check("M1 ...carrying the caption", body.startswith(CAPTION), body)
    check("M1 ...and a readable path to the PDF itself",
          p == pdf and p.is_file() and p.read_bytes().startswith(b"%PDF"), body)

    # M2: payload names the document
    w = World(f"{tmp}/m2").install()
    pdf = w.put("ID-M2", "document", "resume.pdf", CAPTION)
    await wa.hook(Req(event("ID-M2", CAPTION, media="document")))
    body = w.rows[0] if len(w.rows) == 1 else ""
    check("M2 a captioned PDF its payload names → caption + its path",
          body.startswith(CAPTION) and attached(body) == pdf, f"{w.rows}")
    check("M2 ...with no store read (the payload already said)", w.reads == 0, f"{w.reads} reads")

    # M3: uncaptioned video, its own name
    w = World(f"{tmp}/m3").install()
    vid = w.put("ID-M3", "video", "clip one.mp4")
    await wa.hook(Req(event("ID-M3", media="video")))
    check("M3 an uncaptioned video with its own filename → its path",
          len(w.rows) == 1 and attached(w.rows[0]) == vid, f"{w.rows}")

    # M4: control, the old message-* shape
    w = World(f"{tmp}/m4").install()
    img = w.put("ID-M4", "image", "message-ID-M4.jpg")
    await wa.hook(Req(event("ID-M4", media="image")))
    check("M4 control: a photo stored as message-* still arrives",
          len(w.rows) == 1 and attached(w.rows[0]) == img, f"{w.rows}")

    # M5: the file never lands
    w = World(f"{tmp}/m5").install()
    w.store["ID-M5"] = {"Text": CAPTION, "MediaType": "document"}
    await wa.hook(Req(event("ID-M5", CAPTION)))
    body = w.rows[0] if len(w.rows) == 1 else ""
    check("M5 a file that never lands → ONE row, the caption and a line SAYING so",
          body.startswith(CAPTION) and "document attached" in body and "never landed" in body, f"{w.rows}")

    # M6: control, plain text
    w = World(f"{tmp}/m6").install()
    w.store["ID-M6"] = {"Text": "synthetic text six", "MediaType": ""}
    await wa.hook(Req(event("ID-M6", "synthetic text six")))
    check("M6 control: plain text → one row, the text alone",
          w.rows == ["synthetic text six"], f"{w.rows}")

    # M7: control, an empty reaction
    w = World(f"{tmp}/m7").install()
    await wa.hook(Req(event("ID-M7", ReactionToID="ID-M6", ReactionEmoji="")))
    check("M7 control: an empty reaction reads nothing from the store", w.reads == 0, f"{w.reads} reads")

async def hostile(tmp):
    # M8a: a hostile id on the docker branch
    w = World(f"{tmp}/m8").install(docker="wacli-sync")
    bad = "IDx'; echo INJECTED-$(id -u) >&2; echo '"
    await wa.hook(Req(event(bad, CAPTION, media="document")))
    body = w.rows[0] if len(w.rows) == 1 else ""
    check("M8 a hostile id (quote, $(…)) → ONE row: the caption and a line saying it was REFUSED",
          body.startswith(CAPTION) and "refused" in body, f"{w.rows}")
    check("M8 ...and nothing was executed for it (no copy-out, no store read)",
          w.execs == [] and w.reads == 0, f"{w.execs} {w.reads} reads")
    # M8b: a valid id's copy-out is argv (no file lands: the fake finds none)
    w = World(f"{tmp}/m8b").install(docker="wacli-sync")
    got = await wa.fetch_media(CHAT, "IDM8b", "document")
    flat = [a for argv in w.execs for a in argv]
    check("M8b a valid id's docker copy-out is argv: `find <path> -type f`, never `sh -c`",
          bool(w.execs) and "sh" not in flat and "-c" not in flat
          and all(argv[3] == "find" and argv[4].endswith("/IDM8b") for argv in w.execs), f"{w.execs[:1]}")
    check("M8b ...and when no file lands the body says so", "never landed" in str(got), str(got))

    # M9: an id that walks out of the store
    w = World(f"{tmp}/m9").install()
    leak = w.root / "store" / "x"
    leak.mkdir(parents=True)
    (leak / "secret.txt").write_bytes(b"synthetic secret")
    await wa.hook(Req(event("../../x", CAPTION, media="document")))
    body = w.rows[0] if len(w.rows) == 1 else ""
    check("M9 an id that walks (../../x) → no path outside the store reaches the body",
          "secret.txt" not in body and attached(body) is None, body)
    check("M9 ...and the body says it was refused", "refused" in body, body)


with tempfile.TemporaryDirectory(prefix="wa-media-") as tmp:
    asyncio.run(main(tmp))
    asyncio.run(hostile(tmp))
print()
print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else "/hook: every inbound file arrives as a path beside its caption, or says why not")
sys.exit(1 if fails else 0)
