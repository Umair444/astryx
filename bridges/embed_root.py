"""astryx · embed_root — WHICH files a [[file:]] embed may carry to a human surface (plan-9139; a1 #49775/#49782,
a4 #49789, steward #49904).

The bridges are a confused deputy for [[file:]]: they read any path that is_file() as the BRIDGE's uid and send it
to the chat, so a sender needed no read capability to exfiltrate a file — naming it was enough. On an open route
(a group, a guest) a body the outside steered ("attach /…/.env") shipped the file. The boundary is HERE, at the
reader, and it is derived from the sender's IDENTITY (the row's from_agent), never from the body or the thread:

  allowed roots   homes/<from_agent>/                     the sender's own home, minus every dot-path under it
                                                          (.people, .browser-profile, .claude: state, credentials)
                  /tmp/claude-<uid>/<home-encoded>/         the sender's own Claude scratchpads, every session
                  media/                                  the org's shared, deliberately-placed media
                  tier/                                   ONLY when the audience is the owner alone
  never           a basename starting ".env", whatever root it sits in

`read_checked` resolves the path (realpath, so a symlink planted in an allowed root is judged by its TARGET), checks
the root, opens the resolved path O_NOFOLLOW, and re-checks the OPENED file through /proc/self/fd, so a swap between
check and open is judged by what was actually opened. The caller sends the returned bytes, never the path.
channel/embeds.mjs mirrors this rule as early feedback in the sender's turn; this module is the enforcement.
Stdlib only, so a no-venv checkout can test it.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOMES = REPO / "homes"
MEDIA = REPO / "media"
TIER = REPO / "tier"
AGENT_NAME = re.compile(r"[a-z][a-z0-9_-]*")
SCRATCH_BASE = Path(f"/tmp/claude-{os.getuid()}")   # Claude Code's per-uid temp root
MAX_BYTES = 100 * 1024 * 1024          # the largest attachment any of the three surfaces accepts is below this


class Refused(Exception):
    """A [[file:]] embed this sender may not carry to this audience; str() is the reason, safe to show."""


def _real(p: Path) -> Path:
    return Path(os.path.realpath(p))


def _opened(fd: int) -> Path:
    """The file a descriptor actually refers to, from the kernel (Linux /proc)."""
    return Path(os.readlink(f"/proc/self/fd/{fd}"))


def scratch_root(home: Path) -> Path:
    """Claude Code's scratchpad root for sessions started in `home`: /tmp/claude-<uid>/<home, non-alnum → '-'>."""
    return SCRATCH_BASE / re.sub(r"[^A-Za-z0-9]", "-", str(home))


def roots(from_agent: str, audience_is_owner: bool) -> list[Path]:
    """The resolved directories `from_agent` may attach from, toward this audience. [] for a non-agent name.
    roots[0] is the home and roots[1] the scratch root."""
    if not isinstance(from_agent, str) or not AGENT_NAME.fullmatch(from_agent):
        return []
    home = HOMES / from_agent
    out = [_real(home), _real(scratch_root(home)), _real(MEDIA)]
    if audience_is_owner:
        out.append(_real(TIER))
    return out


def _judge(real: Path, from_agent: str, audience_is_owner: bool) -> str | None:
    """None if `real` (already resolved) may be sent; else the reason."""
    if real.name.startswith(".env"):
        return f"{real.name}: an .env file is never attached"
    rs = roots(from_agent, audience_is_owner)
    if not rs:
        return f"sender {from_agent!r} is not an agent name"
    home = rs[0]
    if real.is_relative_to(home) and any(part.startswith(".") for part in real.relative_to(home).parts):
        # .people (the people graph), .browser-profile (cookies, sessions), .claude, .mcp.json: state and
        # credentials, never attachments (steward #49918 F1a). A file meant for a human lives in a plain path.
        return "a dot-path in the sender's home (state or credentials) is never attached"
    if any(real.is_relative_to(r) for r in rs):
        return None
    if not audience_is_owner and real.is_relative_to(_real(TIER)):
        return "tier/ files go only to an owner-only audience"
    return (f"outside {from_agent}'s attachable roots (its home, its scratchpad, media/"
            f"{', tier/' if audience_is_owner else ''})")


def allowed(path: str, from_agent: str, audience_is_owner: bool) -> tuple[Path | None, str]:
    """(resolved path, '') if the embed may be sent, else (None, reason). Judges only; read with read_checked."""
    p = Path(str(path).strip())
    if not p.is_absolute():
        return None, f"{path}: not an absolute path"
    real = _real(p)
    why = _judge(real, from_agent, audience_is_owner)
    return (None, why) if why else (real, "")


def read_checked(path: str, from_agent: str, audience_is_owner: bool) -> tuple[str, bytes]:
    """(filename, bytes) of an embed that may be sent; raises Refused(reason) otherwise. The ONE way a bridge reads
    a [[file:]] path: the bytes come from the opened descriptor, re-judged by what /proc says was opened."""
    real, why = allowed(path, from_agent, audience_is_owner)
    if real is None:
        raise Refused(why)
    try:
        fd = os.open(real, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        raise Refused(f"{Path(path).name}: path not found") from None
    except OSError as e:                        # ELOOP: the last component became a symlink after the check
        raise Refused(f"{Path(path).name}: could not be opened safely ({e.strerror})") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Refused(f"{Path(path).name}: not a regular file")
        opened = _opened(fd)
        why = _judge(opened, from_agent, audience_is_owner)
        if why:
            raise Refused(f"{Path(path).name}: changed during the check ({why})")
        if st.st_size > MAX_BYTES:
            raise Refused(f"{Path(path).name}: {st.st_size} bytes is over the {MAX_BYTES} limit")
        with os.fdopen(fd, "rb", closefd=False) as f:
            data = f.read()
        return opened.name, data
    finally:
        os.close(fd)


def owner_only(channel: str, route: dict | None) -> bool:
    """Is this route's audience the owner alone? Today: an enabled DM route whose declared counterpart is 'owner'
    (astryx.security.release.chat_kind decides DM vs group). Discord routes are channels, so never. When plan-9139 S1c lands,
    its door passes release.audience(...) == {owner} into read_checked instead, and this helper retires."""
    from astryx.security.release import OWNER, chat_kind
    return (isinstance(route, dict) and bool(route.get("enabled"))
            and chat_kind(channel, route.get("chat")) == "dm" and route.get("counterpart") == OWNER)
