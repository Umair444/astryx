#!/usr/bin/env python3
"""astryx · org MCP server — the org's own operations, as tools.

The reference implementation for the tool-first culture (goal 3408): every org
operation an agent used to reach for raw SQL or a throwaway script to do is a tool
here. Caller identity is ASTRYX_AGENT (set per home by spawn.sh); every write is
attributed to it.

These tools MUTATE the org, so they fail LOUD — a write that cannot complete
returns an "error: ..." string, never a silent success (a silent success is a
forged receipt). Only the read path (economy) fails soft, returning what it has.
Config from .env (ASTRYX_DSN); secrets are never echoed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

mcp = FastMCP("org")

# cross-agent charter edits are a governance act; self-edits are open to everyone.
GOVERNANCE = {"seed", "nova", "steward", "polaris", "sirius"}
PY = str(REPO / "venv/bin/python")


def _dsn() -> str:
    for line in (REPO / ".env").read_text().splitlines():
        if line.startswith("ASTRYX_DSN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("ASTRYX_DSN not in .env")


def _me() -> str:
    return os.environ.get("ASTRYX_AGENT", "unknown")


def _conn():
    import psycopg
    return psycopg.connect(_dsn(), connect_timeout=5)


def _charter_path(agent: str) -> Path | None:
    """Resolve a charter by name at any depth through the ONE shared resolver."""
    cp = subprocess.run([PY, str(REPO / "nucleus/charter.py"), agent],
                        capture_output=True, text=True, timeout=10)
    if cp.returncode != 0 or not cp.stdout.strip():
        return None
    return Path(cp.stdout.strip())


@mcp.tool()
def propose_goal(title: str, scope_note: str = "", epoch_hours: int = 24) -> str:
    """File a goal onto the board as 'proposed' — the state the plan pipeline gates.
    You become the goal's owner; budget stays 0 until steward prices it. Returns the
    goal id and the next ritual step. Use this instead of raw INSERT INTO goals — this
    is the tool-first door for filing work."""
    title = (title or "").strip()
    if not title:
        return "error: title is required"
    me = _me()
    try:
        with _conn() as conn:
            gid = conn.execute(
                "INSERT INTO goals (title, owner, state, budget_tokens, epoch_hours, scope_note) "
                "VALUES (%s, %s, 'proposed', 0, %s, %s) RETURNING id",
                (title, me, int(epoch_hours), scope_note or None)).fetchone()[0]
            conn.commit()
        return (f"goal {gid} filed (proposed, owner={me}). Next: open plan-{gid} and route it to "
                f"abstractor-1 with `send` — it activates only on all-four-abstractor approval.")
    except Exception as exc:
        return f"error filing goal: {type(exc).__name__}: {exc}"


@mcp.tool()
def goals(state: str = "active", id: str = "") -> list[dict]:
    """Read the goal board — the read-back for propose_goal, and what an agent used to reach
    for `psql SELECT ... FROM goals` to see. Read-only (fails soft, returns what it has).
    `state` filters (active|proposed|hibernated|done|refused|all; default active); a non-empty
    `id` returns just that goal — WITH its scope_note (the plan frame) — and overrides `state`.
    Newest first; timestamps as strings."""
    base = ["id", "state", "owner", "title", "budget_tokens", "spent_tokens",
            "last_progress", "done_at"]
    try:
        with _conn() as conn:
            if id.strip():
                # lossless single read: include scope_note — the verified diagnosis + design
                # hypothesis a plan verdict is cast against — so reviewing a plan through the
                # tool never forces a raw genesis-superuser psql session (a down-payment on the
                # NOSUPERUSER migration, not just ergonomics). List view stays lean; mirrors
                # query_thread(scan)/read_message(lossless). a1 night-review.
                where, args, cols = "WHERE id = %s", (id.strip(),), base + ["scope_note"]
            elif state and state != "all":
                where, args, cols = "WHERE state = %s", (state,), base
            else:
                where, args, cols = "", (), base
            rows = conn.execute(
                f"SELECT {', '.join(cols)} FROM goals {where} ORDER BY ts DESC", args).fetchall()
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            for k in ("last_progress", "done_at"):
                if d[k] is not None:
                    d[k] = str(d[k])
            out.append(d)
        return out
    except Exception as exc:
        return [{"error": f"{type(exc).__name__}: {exc}"}]


@mcp.tool()
def announce(body: str) -> str:
    """Post a line to the org-news thread — the shipping log every agent reads at
    nightly review. For capabilities shipped, laws ratified, state that changes what
    others can do next. Not for chatter; silence is the default."""
    body = (body or "").strip()
    if not body:
        return "error: body is required"
    me = _me()
    try:
        with _conn() as conn:
            mid = conn.execute(
                "INSERT INTO messages (from_agent, to_agent, thread, intent, body) "
                "VALUES (%s, 'steward', 'org-news', 'milestone', %s) RETURNING id",
                (me, body)).fetchone()[0]
            conn.commit()
        return f"announced to org-news (msg {mid}, from {me})."
    except Exception as exc:
        return f"error announcing: {type(exc).__name__}: {exc}"


@mcp.tool()
def economy() -> dict:
    """The org's economic picture + your own standing + your usage, in one read, with a
    one-line glossary so the numbers are legible without econ knowledge. The per-agent
    STANDING metric is being designed under goal 3407; until it lands, 'you' reports your
    raw 7-day burn and how much of it was goal-attributed (work) vs unattributed (heat)."""
    out = {"glossary": {
        "G": "grow ratio = W / (flux * self-bytes): value earned per token burned per byte of org; higher = leaner",
        "W": "work = sum of budgets of goals VERIFIED in the window; value enters ONLY when a goal ships",
        "Q": "heat = flux - goal-attributed flux: tokens burned that shipped nothing (both flux, so never negative)",
        "flux": "billable tokens spent in the window (the org's energy in)",
    }}
    me = _me()
    try:
        from nucleus.econ import BILL
        with _conn() as conn:
            r = conn.execute("SELECT day, metrics FROM econ ORDER BY day DESC LIMIT 1").fetchone()
            if r:
                day, m = r[0], r[1]
                th = m.get("thermo", {})
                phi, w, phi_goal = th.get("phi"), th.get("W"), th.get("phi_goal_attributed")
                # Q = heat = flux MINUS goal-attributed flux (both flux → can't go negative).
                # NOT phi - W: W is a sum of BUDGETS (a price), phi is billable flux (a cost);
                # subtracting mixes bases and goes negative when shipped-goal budgets exceed
                # window flux. phi_goal_attributed is the flux-based attributable spend, already
                # in the same thermo dict (econ.py:112). (abstractor-1, plan-3408 msg 16134.)
                q = (phi - phi_goal) if (phi is not None and phi_goal is not None) else None
                out["org"] = {"day": str(day), "G": m.get("G"), "W": w, "Q": q,
                              "flux": phi, "eta_W_over_flux": th.get("eta")}
            else:
                out["org"] = {"note": "no econ row yet — the rollup has not run"}
            s = conn.execute(
                f"SELECT COALESCE(SUM({BILL}),0)::bigint, "
                f"COALESCE(SUM({BILL}) FILTER (WHERE goal_id IS NOT NULL),0)::bigint, COUNT(*) "
                f"FROM turns WHERE agent=%s AND ended_at > now() - interval '7 days'", (me,)).fetchone()
            burn, attributed, turns = int(s[0]), int(s[1]), int(s[2])
            out["you"] = {"agent": me, "burn_7d": burn, "attributed_7d": attributed,
                          "attributed_frac": round(attributed / burn, 4) if burn else None,
                          "turns_7d": turns,
                          "note": "single standing metric pending goal 3407"}
            g = conn.execute(
                "SELECT usage_five_hour_pct, usage_seven_day_pct FROM turns "
                "WHERE usage_state='fresh' ORDER BY ended_at DESC LIMIT 1").fetchone()
            if g and g[0] is not None:
                out["usage"] = {"plan_5h_pct": g[0], "plan_7d_pct": g[1]}
        return out
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out


@mcp.tool()
def amend_charter(agent: str, directive: str, section: str = "Standing directives (governance-set)") -> str:
    """Append a directive to an agent's charter under a managed section. You may always
    amend your OWN charter; amending another's requires a governance role
    (seed/nova/steward/polaris/sirius). Does NOT respawn — a running agent only loads its
    charter at spawn, so this returns the refresh command for you to apply deliberately
    (restart-sweep law: never yank an agent mid-task). For self-editing on the wire,
    self_edit also exists."""
    me = _me()
    agent, directive = (agent or "").strip(), (directive or "").strip()
    if not agent or not directive:
        return "error: agent and directive are required"
    if agent != me and me not in GOVERNANCE:
        return f"refused: {me} may not amend {agent}'s charter (cross-agent edits are governance-only)."
    try:
        charter = _charter_path(agent)
        if charter is None:
            return f"error: no charter resolves for '{agent}'"
        text = charter.read_text()
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        bullet = f"- ({stamp}, set by {me}) {directive}"
        header = f"## {section}"
        if header in text:
            i = text.index("\n", text.index(header) + len(header)) + 1
            text = text[:i] + bullet + "\n" + text[i:]
        else:
            text = text.rstrip() + f"\n\n{header}\n{bullet}\n"
        rel = str(charter.relative_to(REPO / "agents"))
        commit = subprocess.run([PY, str(REPO / "nucleus/identity_commit.py"), agent, rel],
                                input=text, capture_output=True, text=True, timeout=30)
        if commit.returncode != 0:
            return f"error committing charter: {commit.stderr.strip()[:300]}"
        return (f"{agent}'s charter amended under '{section}' and committed. Takes effect on next "
                f"respawn — run `nucleus/refresh.sh {agent}` when it is safe (not auto-respawned).")
    except Exception as exc:
        return f"error amending charter: {type(exc).__name__}: {exc}"


@mcp.tool()
def set_persona(avatar_path: str = "", blurb: str = "") -> str:
    """Set your OWN persona: a profile picture and/or a short blurb. avatar_path is a path
    to an image file, copied into your home as avatar.<ext> and served by the observatory at
    /api/agents/<you>/avatar. blurb is saved to persona.md. Self only — you shape your own
    face, not another's."""
    me = _me()
    if me == "unknown":
        return "error: caller identity (ASTRYX_AGENT) is not set"
    if not avatar_path and not blurb:
        return "error: provide avatar_path and/or blurb"
    try:
        charter = _charter_path(me)
        if charter is None:
            return f"error: no charter resolves for '{me}'"
        home = charter.parent
        done = []
        if avatar_path:
            src = Path(avatar_path).expanduser()
            if not src.is_file():
                return f"error: avatar file not found: {avatar_path}"
            ext = src.suffix.lower().lstrip(".") or "png"
            if ext not in {"png", "jpg", "jpeg", "gif", "webp", "svg"}:
                return f"error: unsupported image type .{ext} (png/jpg/jpeg/gif/webp/svg)"
            for old in home.glob("avatar.*"):
                old.unlink()
            dst = home / f"avatar.{ext}"
            shutil.copyfile(src, dst)
            done.append(f"avatar -> {dst.relative_to(REPO)} (served at /api/agents/{me}/avatar)")
        if blurb:
            (home / "persona.md").write_text(blurb.strip() + "\n")
            done.append(f"blurb -> {(home / 'persona.md').relative_to(REPO)}")
        return "persona updated: " + "; ".join(done)
    except Exception as exc:
        return f"error setting persona: {type(exc).__name__}: {exc}"


if __name__ == "__main__":
    mcp.run()
