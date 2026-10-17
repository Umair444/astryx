"""bridges/embed_root.py: a [[file:]] embed reaches a human only from the SENDER's roots (plan-9139; a1 #49775,
a4 #49789, steward #49904). Three parts:
  RULE    hermetic, stdlib only: a scratch repo tree (homes/, media/, tier/, a scratch base) with the module's roots
          pointed at it; every arm a1/a4/steward named, plus the swap and the /proc re-judge.
  WIRING  each bridge's outbound file loop reads ONLY through read_checked(f, agent, owner_only(<channel>, route)),
          with agent = row["from_agent"], and no raw read of the path is left.
  CENSUS  `--census`, live host only (rc 77 NOT SEARCHED without a DSN): every [[file:]] ever sent to a human on a BRIDGE
          surface up to msg 49134, through the rule. Refused: a /tmp path outside the sender's scratchpad (msg 933),
          a tier/ file delivered to a WhatsApp GROUP (msg 19814; the leak class this closes), and 2 embeds under a
          home dot-dir (the dot rule). Canvas rows (cv:) are out of scope: the canvas has its own viewer-keyed gate.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from bridges import embed_root as E  # noqa: E402  (stdlib only)


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)

fails = 0


def arm(name, ok):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    fails += not ok


def refused(path, agent="alpha", owner=False):
    try:
        E.read_checked(str(path), agent, owner)
        return False
    except E.Refused:
        return True


# ── RULE ─────────────────────────────────────────────────────────────────────────────────────────────────────────
tmp = Path(tempfile.mkdtemp(prefix="embedroot-"))
repo = tmp / "repo"
E.HOMES, E.MEDIA, E.TIER = repo / "homes", repo / "media", repo / "tier"
E.SCRATCH_BASE = tmp / "claude-uid"
for d in (E.HOMES / "alpha" / "out", E.HOMES / "alpha" / ".people", E.HOMES / "beta", E.MEDIA, E.TIER):
    d.mkdir(parents=True, exist_ok=True)
own_scratch = E.scratch_root(E.HOMES / "alpha") / "sess-1" / "scratchpad"
beta_scratch = E.scratch_root(E.HOMES / "beta") / "sess-2" / "scratchpad"
for d in (own_scratch, beta_scratch):
    d.mkdir(parents=True)
secret = repo / ".env"
secret.write_text("ASTRYX_DSN=secret\n")
files = {
    "home": E.HOMES / "alpha" / "out" / "shot.png", "scratch": own_scratch / "cv.pdf",
    "media": E.MEDIA / "pic.jpg", "tier": E.TIER / "plan.docx", "beta": E.HOMES / "beta" / "x.pdf",
    "beta_scratch": beta_scratch / "y.pdf", "people": E.HOMES / "alpha" / ".people" / "p.json",
    "home_env": E.HOMES / "alpha" / ".env.local", "elsewhere": tmp / "elsewhere.txt",
}
for f in files.values():
    f.write_bytes(b"data:" + f.name.encode())

name, data = E.read_checked(str(files["home"]), "alpha", False)
arm("the sender's own home: allowed, and the bytes come back", name == "shot.png" and data == b"data:shot.png")
arm("the sender's own scratchpad (any session under its home's scratch root): allowed", not refused(files["scratch"]))
arm("media/: allowed", not refused(files["media"]))
arm("tier/ toward a non-owner audience: refused", refused(files["tier"], owner=False))
arm("tier/ toward the owner alone: allowed", not refused(files["tier"], owner=True))
arm("the repo .env: refused", refused(secret, owner=True))
arm("an .env* inside the sender's own home: refused", refused(files["home_env"], owner=True))
arm("another agent's home: refused", refused(files["beta"], owner=True))
arm("another agent's scratchpad: refused", refused(files["beta_scratch"], owner=True))
arm("the sender's own .people graph: refused", refused(files["people"], owner=True))
arm("a path outside every root: refused", refused(files["elsewhere"], owner=True))
arm("a relative path: refused", refused("out/shot.png"))
arm("a missing file in an allowed root: refused (never silently skipped)", refused(E.HOMES / "alpha" / "gone.png"))
arm("a directory in an allowed root: refused", refused(E.HOMES / "alpha" / "out"))
arm("a sender that is not an agent name: refused", refused(files["media"], agent="../alpha"))
arm("…nor an empty sender", refused(files["media"], agent=""))

link = E.HOMES / "alpha" / "out" / "innocent.png"
link.symlink_to(secret)
arm("a symlink planted in the sender's home pointing at .env: refused (judged by its target)", refused(link, owner=True))
link2 = E.HOMES / "alpha" / "out" / "to-beta.pdf"
link2.symlink_to(files["beta"])
arm("a symlink in the sender's home pointing into another agent's home: refused", refused(link2, owner=True))
dlink = E.HOMES / "alpha" / "repo-link"
dlink.symlink_to(repo)
arm("a directory symlink in the home leading back to the repo root's .env: refused", refused(dlink / ".env", owner=True))
arm("…and through it to another agent's home: refused", refused(dlink / "homes" / "beta" / "x.pdf", owner=True))

# The swap: the check passed on a path whose last component then became a symlink. Simulate it by disabling the
# realpath step (as if resolved before the swap): O_NOFOLLOW refuses to open the symlink.
real_fn = E._real
E._real = lambda p: Path(os.path.abspath(p))
arm("swap: an unresolved final symlink is not followed at open (O_NOFOLLOW)", refused(link, owner=True))
# A swapped PARENT directory: the path names an allowed root but the open lands elsewhere; /proc says where.
E.HOMES.joinpath("alpha", "swapdir").symlink_to(E.HOMES / "beta")
arm("swap: a parent that resolves elsewhere is re-judged by what /proc says was opened",
    refused(E.HOMES / "alpha" / "swapdir" / "x.pdf", owner=True))
E._real = real_fn

# Each layer ALONE (the /proc re-judge would otherwise mask the other two; a mutant of either survived without these):
opened_fn = E._opened
E._opened = lambda fd, _r=None: E.HOMES / "alpha" / "out" / "shot.png"      # /proc says "fine" whatever was opened
arm("realpath alone: a PARENT-directory symlink into another agent's home is refused with /proc blinded "
    "(O_NOFOLLOW covers only the last component)", refused(dlink / "homes" / "beta" / "x.pdf", owner=True))
E._real = lambda p: Path(os.path.abspath(p))
arm("O_NOFOLLOW alone: an unresolved final symlink is not opened with realpath and /proc both blinded",
    refused(link, owner=True))
E._real, E._opened = real_fn, opened_fn

big = E.HOMES / "alpha" / "out" / "big.bin"
with open(big, "wb") as f:
    f.truncate(E.MAX_BYTES + 1)
arm("over the size limit: refused", refused(big))

route_dm_owner = {"enabled": True, "chat": "1@s.whatsapp.net", "counterpart": "owner"}
route_dm_undeclared = {"enabled": True, "chat": "1@s.whatsapp.net"}
route_group = {"enabled": True, "chat": "2@g.us", "counterpart": "owner"}
arm("owner_only: a WhatsApp DM route declaring counterpart owner", E.owner_only("whatsapp", route_dm_owner))
arm("owner_only: a DM with no declared counterpart is not", not E.owner_only("whatsapp", route_dm_undeclared))
arm("owner_only: a group is not, whatever it declares", not E.owner_only("whatsapp", route_group))
arm("owner_only: a Telegram private chat declaring owner", E.owner_only("telegram", {"enabled": True, "chat": "7", "counterpart": "owner"}))
arm("owner_only: a Telegram group is not", not E.owner_only("telegram", {"enabled": True, "chat": "-100123", "counterpart": "owner"}))
arm("owner_only: a Discord channel is not (channels are groups)", not E.owner_only("discord", {"enabled": True, "chat": "1", "counterpart": "owner"}))
arm("owner_only: a disabled or missing route is not", not E.owner_only("whatsapp", {**route_dm_owner, "enabled": False}) and not E.owner_only("whatsapp", None))

# Dot-paths and tier homes (steward #49918 F1):
prof = E.HOMES / "alpha" / ".browser-profile" / "Default"
prof.mkdir(parents=True)
(prof / "Cookies").write_bytes(b"session")
(E.HOMES / "alpha" / ".mcp.json").write_text("{}")
arm("a .browser-profile file in the home: refused, even toward the owner", refused(prof / "Cookies", owner=True))
arm("a dot-file directly in the home (.mcp.json): refused", refused(E.HOMES / "alpha" / ".mcp.json", owner=True))
arm("control: a plain non-dot file in the sender's home goes to a group", not refused(files["home"], owner=False))

# ── WIRING ───────────────────────────────────────────────────────────────────────────────────────────────────────
for ch, extra_bad in (("discord", ("path.read_bytes()", "discord.File(str(p))")),
                      ("telegram", ("p.read_bytes()",)),
                      ("whatsapp", ("shutil.copy(src", "src.is_file()"))):
    src = (REPO / "bridges" / f"{ch}.py").read_text()
    call = f'read_checked(f, agent, owner_only("{ch}", route))'
    arm(f"{ch}.py: the file loop reads through {call}", call in src)
    arm(f"{ch}.py: no raw read of the embed path remains", not any(b in src for b in extra_bad))
    arm(f"{ch}.py: imports the shared rule from bridges/embed_root.py",
        "from .embed_root import Refused, owner_only, read_checked" in src)
    if ch == "whatsapp":
        arm("whatsapp.py: send_files takes the sender as a REQUIRED keyword", "*, agent: str)" in src)
        arm("whatsapp.py: deliver passes agent=agent", "send_files(chat, files, out, agent=agent)" in src)
        dl = src[src.index("async def deliver(row)"):]
    else:
        dl = src[src.index("async def deliver(row)"):]
    use = "send_files(chat, files" if ch == "whatsapp" else "for f in files"
    arm(f"{ch}.py: agent is the row's from_agent, bound before the files are read",
        dl.find('agent = row["from_agent"]') != -1 and dl.find('agent = row["from_agent"]') < dl.find(use))
    arm(f"{ch}.py: a refusal is reported on the receipt", 'out.failed("file", f"refused: {e}")' in src
        or '_fail(f"refused: {e}")' in src)

# ── CENSUS (live host) ───────────────────────────────────────────────────────────────────────────────────────────
DOT_AND_TWO = 4   # measured 2026-10-12: 933, 19814, and 2 embeds under a home dot-dir (.playwright-mcp)


def live_root(repo: Path) -> Path:
    """The MAIN working tree, which holds the estate (homes/, media/, tier/, the routes), from any linked worktree of it.
    merge_check's tree links .env in but NOT homes/ or media/ (its ESTATE_EXCLUDE), so a census judging against REPO
    there found the DSN, ran, and refused every home and scratchpad embed: red in every merge_check, green live (seed
    #57615). A clone (CI) is its own main tree, so it stays REPO, and with no .env it reads NOT SEARCHED."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return repo
    common = Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    return common.parent if common is not None and common.name == ".git" else repo


LIVE = Path(os.environ.get("ASTRYX_LIVE_REPO") or live_root(REPO))


def census():
    try:                     # the LIVE org's DSN through the ONE resolver (astryx.config.dsn), its .env only as before
        dsn = _astryx("config", "dsn", LIVE / ".env", None, False)
    except LookupError:
        dsn = ""
    try:
        import psycopg
    except ImportError:
        return None
    if not dsn:
        return None
    with psycopg.connect(dsn) as c:
        rows = c.execute(
            "SELECT id, from_agent, coalesce(thread,''), to_agent, body FROM messages "
            "WHERE id <= 49134 AND body LIKE '%[[file:%' AND (to_agent='owner' OR to_agent ~ '^(wa|tg|dc)-') "
            "AND coalesce(thread,'') NOT LIKE 'cv:%' ORDER BY id").fetchall()
    R = {}
    for ch in ("discord", "telegram", "whatsapp"):
        f = LIVE / "bridges" / f"routes-{ch}.json"
        R[ch] = json.loads(f.read_text()) if f.is_file() else []
    def route(ch, chat):
        return next((r for r in R[ch] if str(r.get("chat")) == str(chat) and r.get("enabled")), None)
    out, n, allowed_n = set(), 0, 0
    for mid, frm, thread, to, body in rows:
        if thread.startswith("dc:") or to.startswith("dc-"):
            ch, chat = "discord", thread[3:] if thread.startswith("dc:") else to[3:]
        elif thread.startswith("tg:") or to.startswith("tg-"):
            ch, chat = "telegram", thread[3:] if thread.startswith("tg:") else to[3:]
        else:
            ch = "whatsapp"
            chat = thread[3:] if thread.startswith("wa:") else to[3:] if to.startswith("wa-") else \
                (next((r for r in R["whatsapp"] if r.get("agent") == frm and r.get("enabled")), {}) or {}).get("chat")
        for p in re.findall(r"\[\[file:([^\]]+)\]\]", body):
            n += 1
            real, _ = E.allowed(p, frm, E.owner_only(ch, route(ch, chat)))
            if real is None:
                out.add(mid)
            else:
                allowed_n += 1
    return n, out, allowed_n

# live_root, hermetic: a scratch repo and a linked worktree of it (the shape of merge_check's tree)
_g = Path(tempfile.mkdtemp(prefix="embed_live."))
_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
_run = lambda *a: subprocess.run(["git", *a], cwd=_g, env=_env, capture_output=True, text=True)  # noqa: E731
_run("init", "-q", "main")
(_g / "main" / "f").write_text("x")
_run("-C", "main", "-c", "user.email=t@t", "-c", "user.name=t", "add", "f")
_run("-C", "main", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x")
_run("-C", "main", "worktree", "add", "-q", "--detach", str(_g / "wt"))
_main, _wt = (_g / "main").resolve(), (_g / "wt").resolve()
arm("live_root: a linked worktree (merge_check's tree) resolves to the MAIN tree, which holds homes/ and media/",
    _wt.is_dir() and live_root(_wt).resolve() == _main)
arm("…the main tree is its own live root, and a directory outside any repo stays itself",
    live_root(_main).resolve() == _main and live_root(_g) == _g)
shutil_ = __import__("shutil")
shutil_.rmtree(_g, ignore_errors=True)

searched = True
if "--census" in sys.argv:            # its own check.sh line, so a no-DSN tree reads only the CENSUS as NOT SEARCHED
    E.HOMES, E.MEDIA, E.TIER = LIVE / "homes", LIVE / "media", LIVE / "tier"
    E.SCRATCH_BASE = Path(f"/tmp/claude-{os.getuid()}")
    res = census()
else:
    res = "skip"
if res is None:
    print("  NOT SEARCHED  census: no DSN or no psycopg here (a committed-only tree)")
    searched = False
elif res != "skip":
    n, ids, ok_n = res
    arm(f"census: of {n} real embeds, refused exactly 933 (/tmp), 19814 (tier/ to a group) and the dot-path "
        f"screenshots ({sorted(ids)})", {933, 19814} <= ids and ok_n == n - DOT_AND_TWO and n >= 35)

import shutil  # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)
print(f"FAIL ({fails})" if fails else "ALL PASS")
sys.exit(1 if fails else (0 if searched else 77))
