"""astryx observatory · the chat workspace's ARTIFACT STORE (feat/chat-workspace, iterations 2/3;
contract: homes/seed/chat-rebuild/ARTIFACTS_API.md).

An artifact is a file that reached a thread (an owner upload, an agent's [[file:]] embed), imported into a git repo on
first open so every version stays readable and attributed: an agent re-sending the same name is a commit authored by
that agent, an owner edit or restore is a commit by owner. History is never rewritten; a restore is a NEW commit.

    POST /api/ws/artifacts/open                {path, thread, author?, label?, msg_id?, msg_ts?}  import / re-import
    POST /api/ws/artifacts/create              {thread, name, text, author}  a NEW text artifact from words (no file)
    GET  /api/ws/artifacts?thread=             the thread's artifacts, newest first
    GET  /api/ws/artifacts                     THE LIBRARY: every artifact, newest first, + title/author/updated
    POST /api/ws/artifacts/{id}/export         a path an agent (and chat.readable) can read holding the head's bytes
    GET  /api/ws/artifacts/{id}                artifact
    GET  /api/ws/artifacts/{id}/content?rev=   the raw bytes of a version (head by default)
    POST /api/ws/artifacts/{id}/save           {text, message?}  text/table/code only; 409 when unchanged
    POST /api/ws/artifacts/{id}/restore        {rev, message?}  a new commit holding that version's bytes
    GET  /api/ws/artifacts/{id}/annotations    {etag, items}
    PUT  /api/ws/artifacts/{id}/annotations    If-Match: <etag>; [annotation...]; 412 when stale
    GET  /api/ws/media?thread=                 every [[file:]] embed in the thread, oldest first
    GET  /api/ws/media                         every embed in every owner conversation, newest first, + artifact id

THE STORE is <estate>/data/workspace (data/ is gitignored: private to the org), or $ASTRYX_WS_STORE (a dev API points
it at a scratch dir). `git init` on first write; never a remote. Each commit names its author with -c user.name /
-c user.email; global git config is never touched. Writes are serialized by one lock (two saves never interleave);
every git call has a timeout. Files land through hostfile.atomic_write (the observatory's one host writer).

    <store>/.index.json                    {id: {thread, name, path}}: how an id finds its file
    <store>/.sources.json                  {id: {source path: sha256}}: what each source held when last imported
    <store>/<thread dir>/<name>            the artifact (thread ':' -> '_', unsafe chars stripped)
    <store>/<thread dir>/<name>.annotations.json

PROVENANCE (iteration 7, the differentials loop). A version imported from a message's [[file:]] carries git trailers
naming where its bytes came from: `Astryx-Source: <resolved path>`, `Astryx-Msg: <message id>`, `Astryx-Msg-Ts: <the
message's ts>`. Every version shape answers them as `source`, `msg`, `msg_ts` (null when not recorded: an owner edit, a
store made before this), so the chat can open an OLD message's chip at THAT message's version and mark a newer one
"v3 · updated". Ids are the wire's, monotonic: an import attributed to a message OLDER than one a version already
records never becomes the head (history can't be reordered) and answers `superseded: true` instead. Since iteration 12
a version's SUBJECT is that message's headline (workspace.headline, looked up by id in the import's own owner thread),
so the version menu says what the agent said when it sent it; the generic "import x" stays when no message names it.

SAFETY. A source is read ONLY through chat.readable, the gate /api/chat/file uses (the media dir and the agents'
homes, resolved, never a dot-path or an .env); anything else is 403. Ids are 16 hex chars (sha1 of thread + name)
and names are reduced to a safe charset, so no request can name a path. Content is served with the bytes' SNIFFED
type (an agent's .html is text/plain, never a document), nosniff and the CSP sandbox, like serve_untrusted; a ?key=
never authenticates it. OWNER-ONLY BY OMISSION: none of these paths is in main.PUBLIC.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import threading
from pathlib import Path, PurePosixPath
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, ValidationError

from astryx.security.serve import CSP, SVG_CSP, SVG_TYPE, is_svg, sniff
from observatory.api import chat as _chat
from observatory.api import workspace as _ws     # human_sql: the one "a human wrote this" (no import cycle: workspace imports us lazily)
from observatory.api.hostfile import atomic_write, etag

router = APIRouter()

MAX_BYTES = 50 * 1024 * 1024                       # 50 MB per file (the contract's cap)
GIT_TIMEOUT = 30                                   # seconds per git call
INDEX = ".index.json"
SOURCES = ".sources.json"                          # {id: {resolved source path: sha256 of its bytes at last import}}
ANN = ".annotations.json"
OWNER = "owner"
HEADLINE_MAX = 80                                  # a version's subject from its message's first line (iteration 12)

_get_pool = None
ESTATE: Path | None = None

KINDS = {**{e: "text" for e in ("md", "markdown", "txt")},
         **{e: "table" for e in ("csv", "tsv")},
         **{e: "code" for e in ("json", "sql", "py", "ts", "tsx", "js", "sh", "yaml", "yml", "html", "css")},
         **{e: "image" for e in ("png", "jpg", "jpeg", "gif", "webp", "svg")},
         "pdf": "pdf", "docx": "docx", "xlsx": "sheet"}
EDITABLE = ("text", "table", "code")
OOXML = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
TEXT_TYPES = {"csv": "text/csv", "tsv": "text/tab-separated-values", "md": "text/markdown",
              "markdown": "text/markdown"}

# the client's FILE_EMBED (observatory/web/src/chat/model.ts), the same semantics: a path, then an optional label
FILE_EMBED = re.compile(r"\[\[file:([^\]\n]+)\]\](?: \(([^)\n]{1,120})\))?")
ID_RE = re.compile(r"[0-9a-f]{16}")
REV_RE = re.compile(r"[0-9a-f]{4,40}")
AUTHOR_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,40}")


def bind(get_pool, estate: Path) -> None:
    """The host app hands over its pool getter and its estate (the store's default home)."""
    global _get_pool, ESTATE
    _get_pool, ESTATE = get_pool, Path(estate)


class StoreError(Exception):
    """An answer the routes return as {error} with this status."""

    def __init__(self, status: int, error: str):
        super().__init__(error)
        self.status, self.error = status, error


# ------------------------------------------------------------------------------------------------ pure naming
def kind_of(name: str) -> str:
    return KINDS.get(PurePosixPath(name or "").suffix.lower().lstrip("."), "binary")


def safe_name(raw: str) -> str:
    """A display name reduced to [A-Za-z0-9 ._()-], no leading dot, at most 120 chars (the extension kept), never one
    that could pass for an annotations sidecar."""
    s = re.sub(r"[^A-Za-z0-9 ._()-]+", "-", PurePosixPath((raw or "").replace("\\", "/")).name)
    s = re.sub(r"\s+", " ", re.sub(r"-{2,}", "-", s)).strip(" .-") or "file"
    if len(s) > 120:
        stem, dot, ext = s.rpartition(".")
        s = (stem[: 119 - len(ext)].rstrip(" .-") + "." + ext) if dot and 0 < len(ext) <= 10 else s[:120].rstrip(" .-")
    if s.lower().endswith(ANN):
        s += "-"
    return s


def artifact_name(path: str, label: str | None = None) -> str:
    """The artifact's name: the embed's label (an upload's display name) or the source's basename. A label without
    an extension takes the source's (an upload is stored as <uuid>.<sniffed ext>), so the kind is never lost."""
    src = PurePosixPath((path or "").strip())
    if label and label.strip():
        name = safe_name(label.strip())
        if not PurePosixPath(name).suffix and src.suffix:
            name = safe_name(name + src.suffix.lower())
        return name
    return safe_name(src.name)


def artifact_id(thread: str, name: str) -> str:
    return hashlib.sha1(f"{thread}\n{name}".encode()).hexdigest()[:16]


def thread_dir(thread: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._@-]+", "", (thread or "").replace(":", "_")).lstrip(".")
    return s[:100] or "_"


def valid_thread(thread: str) -> bool:
    return bool(thread) and len(thread) <= 200 and not re.search(r"[\x00-\x1f]", thread)


def parse_media(rows: list[dict]) -> list[dict]:
    """GET /api/ws/media from message rows (id, ts, from_agent, body), oldest first: one entry per embed."""
    out = []
    for r in sorted(rows, key=lambda r: r["id"]):
        for m in FILE_EMBED.finditer(r.get("body") or ""):
            path, label = m.group(1).strip(), m.group(2)
            name = artifact_name(path, label)
            ts = r.get("ts")
            out.append({"path": path, "label": label, "name": name, "kind": kind_of(name), "from": r.get("from_agent"),
                        "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts, "msg_id": r["id"]})
    return out


def content_type(name: str, data: bytes) -> str:
    """The served type: the BYTES decide (serve.sniff), the extension only refines a type the bytes already proved —
    a text file is shown as text (csv/markdown named as such, html never a document), an .svg that IS one as
    image/svg+xml (served under SVG_CSP), an OOXML zip as itself."""
    ext = PurePosixPath(name).suffix.lower().lstrip(".")
    if ext in OOXML and data[:4] == b"PK\x03\x04":
        return OOXML[ext]
    kind = sniff(data[:4096])
    if ext == "svg" and is_svg(data[:4096]):
        return SVG_TYPE
    if kind and kind.startswith("text/"):
        return f"{TEXT_TYPES.get(ext, 'text/plain')}; charset=utf-8"
    return kind or "application/octet-stream"


# ------------------------------------------------------------------------------------------------- annotations
class Anchor(BaseModel):
    quote: str = Field(max_length=20000)
    prefix: str = Field("", max_length=400)
    suffix: str = Field("", max_length=400)
    start: int | None = None
    end: int | None = None
    page: int | None = None


class Reply(BaseModel):
    author: str = Field(max_length=80)
    body: str = Field(max_length=20000)
    ts: str = Field(max_length=40)


class Annotation(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal["highlight", "comment", "suggest"]
    color: Literal["yellow", "green", "blue", "pink"] | None = None
    anchor: Anchor
    body: str | None = Field(None, max_length=20000)
    author: str = Field(max_length=80)
    ts: str = Field(max_length=40)
    replies: list[Reply] | None = None
    resolved: bool | None = None


MAX_ANNOTATIONS = 2000


def clean_annotations(raw) -> list[dict]:
    """Validate a PUT body; raises StoreError(400). Unset optional fields are dropped, so a round trip is stable."""
    if not isinstance(raw, list):
        raise StoreError(400, "annotations must be a list")
    if len(raw) > MAX_ANNOTATIONS:
        raise StoreError(413, f"at most {MAX_ANNOTATIONS} annotations")
    try:
        items = [Annotation.model_validate(a).model_dump(exclude_none=True) for a in raw]
    except ValidationError as e:
        raise StoreError(400, f"not an annotation: {e.errors()[0].get('msg', 'invalid')}") from None
    if len({a["id"] for a in items}) != len(items):
        raise StoreError(400, "two annotations share an id")
    return items


# ------------------------------------------------------------------------------------------------- provenance
TRAILERS = ("Astryx-Source", "Astryx-Msg", "Astryx-Msg-Ts")
# one version per record: rev, short, author, time, subject, then the three trailers (empty when absent)
LOG_FMT = "%x1e%H%x1f%h%x1f%an%x1f%aI%x1f%s" + "".join(f"%x1f%(trailers:key={k},valueonly,separator=%x1d)" for k in TRAILERS)


def provenance(msg: dict | None, source: str | None) -> str:
    """The trailer block a version's commit message ends with ('' when there is nothing to record). Values are one
    line each; a message id is an int, its ts at most 40 printable chars."""
    out = []
    if source:
        out.append("Astryx-Source: " + re.sub(r"[\x00-\x1f]", "", source)[:1024])
    if msg and isinstance(msg.get("id"), int) and msg["id"] > 0:
        out.append(f"Astryx-Msg: {msg['id']}")
        ts = re.sub(r"[^0-9A-Za-z:+.\- ]", "", str(msg.get("ts") or ""))[:40]
        if ts:
            out.append(f"Astryx-Msg-Ts: {ts}")
    return ("\n\n" + "\n".join(out)) if out else ""


def version_rows(chunks: list[str]) -> list[dict]:
    """LOG_FMT records (newest first) -> version shapes, numbered oldest = 1."""
    rows = [c.split("\x1f") for c in chunks]
    rows = [r for r in rows if len(r) == 5 + len(TRAILERS)]
    out = []
    for i, (h, s, a, t, m, src, mid, mts) in enumerate(rows):
        out.append({"rev": h, "short": s, "n": len(rows) - i, "author": a, "ts": t, "message": m,
                    "source": src.split("\x1d")[0] or None,
                    "msg": int(mid.split("\x1d")[0]) if mid.split("\x1d")[0].isdigit() else None,
                    "msg_ts": mts.split("\x1d")[0] or None})
    return out


# ----------------------------------------------------------------------------------------------------- the store
class Store:
    """The git repo. Every write holds self.lock (re-entrant) for its whole read-modify-commit."""

    def __init__(self, root: Path, max_bytes: int = MAX_BYTES, timeout: float = GIT_TIMEOUT):
        self.root, self.max_bytes, self.timeout = Path(root), max_bytes, timeout
        self.lock = threading.RLock()

    # -- git
    def git(self, *args: str, author: str | None = None, ok=(0,)) -> subprocess.CompletedProcess:
        cmd = ["git", "--literal-pathspecs", "-c", "core.quotepath=off", "-c", "core.autocrlf=false",
               "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]
        if author:
            cmd += ["-c", f"user.name={author}", "-c", f"user.email={author}@astryx.local"]
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                  "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
            env.pop(k, None)
        try:
            r = subprocess.run(cmd + list(args), cwd=self.root, capture_output=True, timeout=self.timeout, env=env)
        except subprocess.TimeoutExpired:
            raise StoreError(504, f"the store timed out ({args[0]})") from None
        if r.returncode not in ok:
            raise StoreError(500, f"the store failed ({args[0]}): {r.stderr.decode(errors='replace').strip()[:200]}")
        return r

    def ready(self) -> bool:
        return (self.root / ".git").is_dir()

    def ensure(self) -> None:
        with self.lock:
            if self.ready():
                return
            self.root.mkdir(parents=True, exist_ok=True)
            os.chmod(self.root, 0o750)
            self.git("init", "-q")
            atomic_write(self.root / ".gitattributes", "* -text\n", mode=0o640)   # bytes in, bytes out
            atomic_write(self.root / INDEX, "{}\n", mode=0o640)
            self.git("add", "--", ".gitattributes", INDEX)
            self.git("commit", "-q", "-m", "workspace store", author="astryx")

    def commit(self, paths: list[str], message: str, author: str) -> bool:
        """Stage `paths` and commit them as `author`; False (nothing committed) when they are unchanged."""
        self.git("add", "--", *paths)
        if self.git("diff", "--cached", "--quiet", "--", *paths, ok=(0, 1)).returncode == 0:
            return False
        self.git("commit", "-q", "-m", message, "--", *paths, author=author)
        return True

    # -- index
    def index(self) -> dict:
        try:
            raw = json.loads((self.root / INDEX).read_text())
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            return {}

    def entry(self, aid: str) -> dict:
        e = self.index().get(aid) if ID_RE.fullmatch(aid or "") else None
        if not e:
            raise StoreError(404, "no such artifact")
        return e

    # -- reads
    def versions(self, path: str) -> list[dict]:
        out = self.git("log", f"--format={LOG_FMT}", "--", path).stdout.decode(errors="replace")
        return version_rows([c.rstrip("\n") for c in out.split("\x1e")[1:]])

    def artifact(self, aid: str) -> dict:
        e = self.entry(aid)
        vs = self.versions(e["path"])
        try:
            size = (self.root / e["path"]).stat().st_size
        except OSError:
            size = 0
        return {"id": aid, "thread": e["thread"], "name": e["name"], "kind": kind_of(e["name"]),
                "path_in_store": e["path"], "size": size, "head": vs[0]["rev"] if vs else None, "versions": vs}

    def list(self, thread: str) -> list[dict]:
        if not self.ready():
            return []
        arts = [self.artifact(aid) for aid, e in self.index().items() if e.get("thread") == thread]
        order = {h: i for i, h in enumerate(self.git("log", "--format=%H").stdout.decode().split())}
        return sorted(arts, key=lambda a: order.get(a["head"], len(order)))   # newest head first (ts ties in a second)

    def list_all(self) -> list[dict]:
        """Every artifact (the library), newest head first, from ONE git log (not a log per artifact), each with
        `author` (who made v1), `updated` (the head's time) on top of the artifact shape."""
        if not self.ready():
            return []
        out = self.git("log", f"--format={LOG_FMT}", "--name-only").stdout.decode(errors="replace")
        by: dict[str, list[str]] = {}
        order: dict[str, int] = {}
        for chunk in out.split("\x1e")[1:]:
            head, _, files = chunk.partition("\n")
            if head.count("\x1f") != 4 + len(TRAILERS):
                continue
            order.setdefault(head.split("\x1f")[0], len(order))
            for f in files.splitlines():
                if f.strip():
                    by.setdefault(f.strip(), []).append(head)
        arts = []
        for aid, e in self.index().items():
            if not (ID_RE.fullmatch(aid) and isinstance(e, dict) and e.get("path")):
                continue
            vs = version_rows(by.get(e["path"], []))
            try:
                size = (self.root / e["path"]).stat().st_size
            except OSError:
                continue                            # indexed but gone from the tree: not a file anyone can open
            arts.append({"id": aid, "thread": e.get("thread", ""), "name": e.get("name", ""), "kind": kind_of(e.get("name", "")),
                         "path_in_store": e["path"], "size": size, "head": vs[0]["rev"] if vs else None, "versions": vs,
                         "author": vs[-1]["author"] if vs else None, "updated": vs[0]["ts"] if vs else None})
        return sorted(arts, key=lambda x: order.get(x["head"], len(order)))

    def export(self, aid: str, media: Path) -> dict:
        """A readable path holding the head's bytes, for a [[file:]] embed an AGENT will read (a project's pinned
        files ride a project chat's first message). The source it was imported from, while that still holds exactly
        these bytes; else a snapshot under <media>/upload/ named by the bytes' hash (the same head -> the same file,
        written once), with the artifact's own extension. Nothing outside the store and the media dir is touched."""
        e = self.entry(aid)
        data, name, _ = self.content(aid)
        sha = hashlib.sha256(data).hexdigest()
        srcs = self.sources().get(aid)
        for src, h in (srcs.items() if isinstance(srcs, dict) else ()):
            p = _chat.readable(src) if h == sha else None
            try:
                if p is not None and hashlib.sha256(p.read_bytes()).hexdigest() == sha:
                    return {"id": aid, "name": name, "path": str(p)}
            except OSError:
                continue
        ext = PurePosixPath(e["name"]).suffix.lower()
        ext = ext if re.fullmatch(r"\.[a-z0-9]{1,5}", ext) else ".bin"
        dest = Path(media) / "upload" / f"{sha[:32]}{ext}"
        with self.lock:
            if not dest.is_file():
                atomic_write(dest, data, mode=0o640)
        return {"id": aid, "name": name, "path": str(dest.resolve())}

    def version(self, path: str, rev: str | None) -> dict:
        vs = self.versions(path)
        if not vs:
            raise StoreError(404, "no versions")
        if rev is None:
            return vs[0]
        rev = rev.strip().lower()
        hit = [v for v in vs if REV_RE.fullmatch(rev) and v["rev"].startswith(rev)]
        if len(hit) != 1:
            raise StoreError(404, "no such version of this artifact")
        return hit[0]

    def content(self, aid: str, rev: str | None = None) -> tuple[bytes, str, dict]:
        e = self.entry(aid)
        v = self.version(e["path"], rev)
        return self.git("show", f"{v['rev']}:{e['path']}").stdout, e["name"], v

    # -- writes
    def sources(self) -> dict:
        try:
            raw = json.loads((self.root / SOURCES).read_text())
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            return {}

    def put(self, thread: str, name: str, data: bytes, author: str, message: str | None = None,
            source: str | None = None, msg: dict | None = None) -> dict:
        """Import bytes as (thread, name): new artifact -> v1 by `author`. Re-importing adds a version ONLY when the
        SOURCE changed since it was last imported (its sha256 is recorded per artifact and source path), never because
        the head differs: an owner edit stays current when the owner reopens an untouched source. A source path not
        seen before for this artifact is new only if its bytes match no source this artifact ever imported (an upload
        of the same file again is not news). Without `source`, identical-to-head bytes are the only no-op.
        `msg` ({id, ts}: the message whose embed carried these bytes) is recorded as provenance; bytes from a message
        older than one a version already records never become the head: the artifact answers `superseded: true`."""
        if len(data) > self.max_bytes:
            raise StoreError(413, f"the file is over {self.max_bytes // (1024 * 1024)} MB")
        aid = artifact_id(thread, name)
        sha = hashlib.sha256(data).hexdigest()
        with self.lock:
            self.ensure()
            idx = self.index()
            e = idx.get(aid)
            new = e is None
            srcs = self.sources()
            seen = srcs.get(aid) if isinstance(srcs.get(aid), dict) else {}
            if not new and source and seen:
                if (seen.get(source) or sha) == sha and sha in seen.values():
                    if seen.get(source) != sha:          # the same bytes from a new path: remember it, no version
                        srcs[aid] = {**seen, source: sha}
                        atomic_write(self.root / SOURCES, json.dumps(srcs, indent=1, sort_keys=True) + "\n", mode=0o640)
                        self.commit([SOURCES], f"source of {name}", author)
                    return self.artifact(aid)
            if not new and msg and isinstance(msg.get("id"), int):
                newest = max((v["msg"] or 0 for v in self.versions(e["path"])), default=0)
                if newest > msg["id"] and hashlib.sha256((self.root / e["path"]).read_bytes()).hexdigest() != sha:
                    return {**self.artifact(aid), "superseded": True}
            if new:
                taken = {x.get("path") for x in idx.values()}
                path = f"{thread_dir(thread)}/{name}"
                if path in taken or path.lower().endswith(ANN):   # two threads that sanitize alike: keep both
                    path = f"{thread_dir(thread)}/{aid[:8]}-{name}"
                e = idx[aid] = {"thread": thread, "name": name, "path": path}
            atomic_write(self.root / e["path"], data, mode=0o640)
            paths = [e["path"]]
            if new:
                atomic_write(self.root / INDEX, json.dumps(idx, indent=1, sort_keys=True) + "\n", mode=0o640)
                paths.append(INDEX)
            if source:
                srcs[aid] = {**seen, source: sha}
                atomic_write(self.root / SOURCES, json.dumps(srcs, indent=1, sort_keys=True) + "\n", mode=0o640)
                paths.append(SOURCES)
            subject = message or (f"import {name}" if new else f"new version of {name}")
            self.commit(paths, subject + provenance(msg, source), author)
            return self.artifact(aid)

    def save(self, aid: str, text: str, message: str | None = None) -> dict:
        e = self.entry(aid)
        if kind_of(e["name"]) not in EDITABLE:
            raise StoreError(415, "only text, table and code artifacts are edited here")
        data = text.encode()
        if len(data) > self.max_bytes:
            raise StoreError(413, f"the file is over {self.max_bytes // (1024 * 1024)} MB")
        with self.lock:
            atomic_write(self.root / e["path"], data)
            if not self.commit([e["path"]], (message or "").strip()[:200] or "edit", OWNER):
                raise StoreError(409, "unchanged")
            return self.artifact(aid)

    def restore(self, aid: str, rev: str, message: str | None = None) -> dict:
        """A new commit by owner holding `rev`'s bytes; `message` names why (a revert of an agent's change says whose),
        else `restore <short> (v<N>)`."""
        e = self.entry(aid)
        with self.lock:
            v = self.version(e["path"], rev or "")
            data = self.git("show", f"{v['rev']}:{e['path']}").stdout
            atomic_write(self.root / e["path"], data)
            subject = re.sub(r"\s+", " ", message or "").strip()[:200] or f"restore {v['short']} (v{v['n']})"
            if not self.commit([e["path"]], subject, OWNER):
                raise StoreError(409, "unchanged")
            return self.artifact(aid)

    def create(self, thread: str, name: str, text: str, author: str, msg: dict | None = None) -> dict:
        """A NEW text artifact holding `text` (a turn opened as a document, or a table in a turn as CSV: no file anywhere
        but the store), v1 by `author` (whose words they are). The name is made a text name (.md unless it already
        names a text or table kind); if
        the thread already has that name with other bytes, the next free "name (2).md". The same words under the same
        name are the existing artifact, not a copy."""
        if not valid_thread(thread):
            raise StoreError(400, "a thread is required")
        if not AUTHOR_RE.fullmatch(author or ""):
            raise StoreError(400, "author must be an agent name or owner")
        if not (text or "").strip():
            raise StoreError(400, "there is no text to keep")
        data = text.encode()
        if len(data) > self.max_bytes:
            raise StoreError(413, f"the text is over {self.max_bytes // (1024 * 1024)} MB")
        base = safe_name(name or "answer")
        if kind_of(base) not in ("text", "table"):     # words stay .md; a table (a turn's, as CSV) keeps .csv/.tsv
            base = safe_name(base + ".md")
        stem, ext = (base[: -len(PurePosixPath(base).suffix)], PurePosixPath(base).suffix)
        with self.lock:
            idx = self.index() if self.ready() else {}
            for i in range(1, 100):
                cand = base if i == 1 else safe_name(f"{stem[:110]} ({i}){ext}")
                aid = artifact_id(thread, cand)
                if aid not in idx:
                    return self.put(thread, cand, data, author, f"open as document: {cand}", msg=msg)
                if self.content(aid)[0] == data:
                    return self.artifact(aid)
                # the words it STARTED from (v1, by the same author): the owner edited it since, so opening the same
                # turn again opens that edited document, never a fresh "(2)" copy of the original words (iteration 11)
                first = self.versions(idx[aid]["path"])[-1:]
                if first and first[0]["author"] == author and self.content(aid, first[0]["rev"])[0] == data:
                    return self.artifact(aid)
            raise StoreError(409, "too many documents by that name")

    def annotations(self, aid: str) -> dict:
        p = self.root / (self.entry(aid)["path"] + ANN)
        try:
            items = json.loads(p.read_text())
        except (OSError, ValueError):
            items = []
        return {"etag": etag(p), "items": items if isinstance(items, list) else []}

    def put_annotations(self, aid: str, raw, if_match: str) -> dict:
        e = self.entry(aid)
        items = clean_annotations(raw)
        rel = e["path"] + ANN
        with self.lock:
            if etag(self.root / rel) != if_match:
                raise StoreError(412, "the annotations changed since you loaded them")
            text = json.dumps(items, indent=1, ensure_ascii=False) + "\n"
            atomic_write(self.root / rel, text, mode=0o640)
            self.commit([rel], "annotate", OWNER)
            return self.annotations(aid)


def import_source(store: Store, path: str, thread: str, author: str = OWNER, label: str | None = None,
                  msg: dict | None = None, subject: str | None = None) -> dict:
    """POST open's body: the source is read ONLY if chat.readable (the /api/chat/file gate) admits it. `subject` (the
    carrying message's headline) names the version when it makes one; else "import x" / "new version of x"."""
    if not valid_thread(thread):
        raise StoreError(400, "a thread is required")
    if not AUTHOR_RE.fullmatch(author or ""):
        raise StoreError(400, "author must be an agent name or owner")
    p = _chat.readable(path or "")
    if p is None:
        raise StoreError(403, "that file can't be opened here")
    if p.stat().st_size > store.max_bytes:
        raise StoreError(413, f"the file is over {store.max_bytes // (1024 * 1024)} MB")
    return store.put(thread, artifact_name(str(path), label), p.read_bytes(), author, subject, source=str(p), msg=msg)


# ------------------------------------------------------------------------------------------------------ routes
_stores: dict[str, Store] = {}


def store_root() -> Path:
    env = os.environ.get("ASTRYX_WS_STORE", "").strip()
    return Path(env) if env else ESTATE / "data" / "workspace"


def store() -> Store:
    root = str(store_root())
    if root not in _stores:
        _stores[root] = Store(Path(root))
    return _stores[root]


async def _run(fn, *args):
    """One store call off the event loop; a StoreError becomes its JSON answer."""
    try:
        return await asyncio.to_thread(fn, *args)
    except StoreError as e:
        return JSONResponse({"error": e.error}, status_code=e.status)


class Open(BaseModel):
    path: str = Field(max_length=4096)
    thread: str = Field(max_length=200)
    author: str | None = None
    label: str | None = Field(None, max_length=120)
    msg_id: int | None = Field(None, ge=1)          # the message whose embed carried the bytes (provenance)
    msg_ts: str | None = Field(None, max_length=40)


class Create(BaseModel):
    thread: str = Field(max_length=200)
    name: str = Field(max_length=200)
    text: str
    author: str = Field(max_length=41)
    msg_id: int | None = Field(None, ge=1)
    msg_ts: str | None = Field(None, max_length=40)


def _msg(msg_id: int | None, msg_ts: str | None) -> dict | None:
    return {"id": msg_id, "ts": msg_ts} if msg_id else None


class Save(BaseModel):
    text: str
    message: str | None = Field(None, max_length=200)


class Restore(BaseModel):
    rev: str = Field(max_length=40)
    message: str | None = Field(None, max_length=200)


# a human's conversation (the owner's or a member's, 11-15: workspace.human_sql), or any chat:
HEADLINE_SQL = ("SELECT body FROM messages WHERE id = $1 AND thread = $2 "
                f"AND ({_ws.human_sql('from_agent')} OR {_ws.human_sql('to_agent')} OR thread LIKE 'chat:%')")


async def msg_headline(request: Request, msg_id: int | None, thread: str) -> str | None:
    """The commit subject a version imported from a message carries (iteration 12): that message's headline (its first
    meaningful line, cleaned, ≤80 chars), so the version menu reads "v3 · Db · Active wallets 6.4% after the close"
    instead of "new version of x". Looked up server-side by id, and only in the owner conversation the import names
    (an id from another thread, or a thread that isn't the owner's, names nothing). None = the generic subject."""
    from observatory.api import workspace as _ws
    if not msg_id or not _ws.surface_of(thread):
        return None
    try:
        pool = _get_pool() if _get_pool else request.app.state.pool
        row = await pool.fetchrow(HEADLINE_SQL, msg_id, thread)
    except Exception:                               # noqa: BLE001 — no database: the generic subject stands
        return None
    return (_ws.headline(row["body"], HEADLINE_MAX) or None) if row else None


@router.post("/api/ws/artifacts/open")
async def art_open(body: Open, request: Request):
    subject = await msg_headline(request, body.msg_id, body.thread)
    return await _run(import_source, store(), body.path, body.thread, body.author or OWNER, body.label,
                      _msg(body.msg_id, body.msg_ts), subject)


@router.post("/api/ws/artifacts/create")
async def art_create(body: Create):
    return await _run(store().create, body.thread, body.name, body.text, body.author, _msg(body.msg_id, body.msg_ts))


def _pool_of(request: Request):
    return _get_pool() if _get_pool else request.app.state.pool


async def _thread_ok(request: Request, thread: str) -> bool:
    """A member given part of the agents/ tree reads only the threads whose every message is theirs (scope.py)."""
    from observatory.api import scope
    return scope.of(request) is None or thread in await scope.threads_ok(_pool_of(request), request, [thread])


async def _aid_ok(request: Request, aid: str) -> bool:
    from observatory.api import scope
    if scope.of(request) is None:
        return True
    try:
        thread = (await asyncio.to_thread(store().entry, aid))["thread"]
    except Exception:                               # noqa: BLE001 — no such artifact: the handler's own 404 says so
        return True
    return await _thread_ok(request, thread)


NOT_YOURS = JSONResponse({"error": "that conversation is outside the agents you were given"}, status_code=403)


@router.get("/api/ws/artifacts")
async def art_list(request: Request, thread: str | None = None):
    """?thread= -> that thread's artifacts; no thread -> THE LIBRARY: every artifact, each with its conversation's
    `title` (a project's knowledge, thread project:<id>, is titled by the project)."""
    if thread is not None:
        if not valid_thread(thread):
            return JSONResponse({"error": "a thread is required"}, status_code=400)
        if not await _thread_ok(request, thread):
            return NOT_YOURS
        return await _run(store().list, thread)
    arts = await _run(store().list_all)
    if isinstance(arts, Response):
        return arts
    from observatory.api import scope
    if scope.of(request) is not None:
        ok = await scope.threads_ok(_pool_of(request), request, {a["thread"] for a in arts})
        arts = [a for a in arts if a["thread"] in ok]
    titles = await thread_titles(request, {a["thread"] for a in arts})
    return [{**a, "title": titles.get(a["thread"]) or a["thread"]} for a in arts]


async def thread_titles(request: Request, threads: set[str]) -> dict[str, str]:
    """Each conversation's name as the sidebar shows it (workspace.derive_title over the same inputs), a project's
    knowledge thread named by its project. Best effort: a thread the database can't name keeps its id."""
    from observatory.api import workspace as _ws
    out: dict[str, str] = {}
    projects = {p.get("id"): p.get("name") for p in _ws._projects() if isinstance(p, dict)}
    for t in threads:
        if t.startswith("project:") and projects.get(t[8:]):
            out[t] = projects[t[8:]]
        elif t.startswith("wa:"):                   # a WhatsApp file opened from the briefing: never the group's id
            out[t] = "A WhatsApp chat"
    convo = sorted(t for t in threads if _ws.surface_of(t))
    if not convo:
        return out
    try:
        pool = _get_pool() if _get_pool else request.app.state.pool
        rows = await pool.fetch(
            "SELECT thread, (array_agg(left(" + _ws._BODY + ", 400) ORDER BY id) FILTER (WHERE " + _ws.human_sql("from_agent") + "))[1] "
            "AS first_owner, array_agg(DISTINCT from_agent) || array_agg(DISTINCT to_agent) AS parties "
            "FROM messages WHERE thread = ANY($1::text[]) GROUP BY thread", convo)
    except Exception:                               # noqa: BLE001 — no database: ids stand in for titles
        return out
    meta, roster = _ws.read_meta(), set(_ws._roster())
    for r in rows:
        t = r["thread"]
        agents = _ws.agents_of(t, list(r["parties"] or []), roster)
        out[t] = _ws.derive_title(t, (meta.get(t) or {}).get("title"), r["first_owner"], None, agents)
    return out


@router.post("/api/ws/artifacts/{aid}/export")
async def art_export(aid: str):
    if _chat.MEDIA is None:
        return JSONResponse({"error": "no media dir"}, status_code=503)
    return await _run(store().export, aid, _chat.MEDIA)


@router.get("/api/ws/artifacts/{aid}")
async def art_get(aid: str, request: Request):
    if not await _aid_ok(request, aid):
        return NOT_YOURS
    return await _run(store().artifact, aid)


@router.get("/api/ws/artifacts/{aid}/content")
async def art_content(aid: str, request: Request, rev: str | None = None):
    if "key" in request.query_params:               # like /api/chat/file: a navigation never authenticates this
        return Response(status_code=403)
    if not await _aid_ok(request, aid):
        return NOT_YOURS
    got = await _run(store().content, aid, rev)
    if isinstance(got, Response):
        return got
    data, name, _ = got
    ascii_name = re.sub(r'[^A-Za-z0-9 ._()-]', "_", name)
    ctype = content_type(name, data)
    return Response(data, media_type=ctype, headers={
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": SVG_CSP if ctype == SVG_TYPE else CSP,
        "Content-Disposition": f'inline; filename="{ascii_name}"',
        "Cache-Control": "private, max-age=31536000, immutable" if rev else "no-store"})


@router.post("/api/ws/artifacts/{aid}/save")
async def art_save(aid: str, body: Save):
    return await _run(store().save, aid, body.text, body.message)


@router.post("/api/ws/artifacts/{aid}/restore")
async def art_restore(aid: str, body: Restore):
    return await _run(store().restore, aid, body.rev, body.message)


@router.get("/api/ws/artifacts/{aid}/annotations")
async def art_annotations(aid: str, request: Request):
    if not await _aid_ok(request, aid):
        return NOT_YOURS
    got = await _run(store().annotations, aid)
    if isinstance(got, Response):
        return got
    return JSONResponse(got, headers={"ETag": f'"{got["etag"]}"'})


@router.put("/api/ws/artifacts/{aid}/annotations")
async def art_annotations_put(aid: str, request: Request):
    # an absent If-Match means "I saw none": accepted only while none exist, so a blind write never clobbers
    tag = (request.headers.get("if-match") or "").strip().removeprefix("W/").strip('"')
    try:
        raw = json.loads(await request.body() or b"null")
    except ValueError:
        return JSONResponse({"error": "the body is not JSON"}, status_code=400)
    got = await _run(store().put_annotations, aid, raw, tag)
    if isinstance(got, Response):
        return got
    return JSONResponse(got, headers={"ETag": f'"{got["etag"]}"'})


def library_media(rows: list[dict], index: dict) -> list[dict]:
    """GET /api/ws/media without a thread: every embed in the owner's conversations, newest first, ONE entry per
    (thread, file) at its newest mention, each with `thread` and `artifact` (its id when the store already holds it,
    else None: the library offers it as not opened yet)."""
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r["id"], reverse=True):
        for m in parse_media([r]):
            key = (r.get("thread"), m["path"])
            if key in seen:
                continue
            seen.add(key)
            aid = artifact_id(r.get("thread") or "", m["name"])
            out.append({**m, "thread": r.get("thread"), "artifact": aid if aid in index else None})
    return out


MEDIA_ALL_SQL = ("SELECT id, ts, from_agent, to_agent, thread, body FROM messages "
                 "WHERE (thread LIKE 'chat:%' OR thread LIKE 'obs:%' OR thread LIKE 'cv:%') AND body LIKE '%[[file:%' "
                 f"AND ({_ws.human_sql('from_agent')} OR {_ws.human_sql('to_agent')} OR thread LIKE 'chat:%') "
                 "ORDER BY id DESC LIMIT 2000")


@router.get("/api/ws/media")
async def ws_media(request: Request, thread: str | None = None):
    from observatory.api import scope
    pool = _pool_of(request)
    if thread is None:
        rows = [dict(r) for r in await pool.fetch(MEDIA_ALL_SQL)]
        if scope.of(request) is not None:          # only a file a message the member may read attached
            rows = [r for r in rows if scope.message_ok(request, r)]
        idx = await asyncio.to_thread(lambda: store().index() if store().ready() else {})
        return library_media(rows, idx)
    if not valid_thread(thread):
        return JSONResponse({"error": "a thread is required"}, status_code=400)
    if not await _thread_ok(request, thread):
        return NOT_YOURS
    rows = await pool.fetch("SELECT id, ts, from_agent, body FROM messages WHERE thread = $1 AND body LIKE '%[[file:%' "
                            "ORDER BY id LIMIT 5000", thread)
    return parse_media([dict(r) for r in rows])
