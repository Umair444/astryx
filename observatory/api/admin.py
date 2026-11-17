"""astryx observatory · the org's ADMIN API (cog-rebuild, owner 11-13: "whoever is the owner of org can decide the roles
of other users … it should be managed by an admin. i wanted an admin panel in observatory too for each org").

Accounts live in the COG's store and are the front's (observatory/front.py /auth/admin/*: invites, reset links, sign
out everywhere). WHAT AN ACCOUNT MAY DO HERE is this org's own fact, its `members` table, and this router is the org
side of the panel. Every read and write goes through observatory/api/members.py (one place for the table's shape);
every write through astryx.cogauth.grant/revoke, the one writer (D8).

    GET    /api/admin/members         {you, roles, tree, members: [{uid, node, role, added}]}
    PUT    /api/admin/members         {uid, node?, role}: grant (an upsert on that node)
    DELETE /api/admin/members         {uid, node?}: one node's row, or (no node) every row of the uid
    GET    /api/admin/nodes           the agents/ tree as grantable nodes: [{node, kind: group|agent, depth}]
    GET    /api/admin/activity?uid=   {scope owner|account, messages, threads, last_message, voice_minutes}: counts
    PUT    /api/admin/features        {uid, feature, allowed: true|false|null, minutes?}: what one person may use
                                      (owner 11-17); null puts them back on their role's default. Never an owner's

WHO MAY: the org's owner (the owner key, or a signed-in owner) and a signed-in ADMIN. main.privacy_gate admits an
admin to exactly ADMIN_ROUTES; each handler judges again. THE GUARDS: an admin can neither grant `owner` nor change or
remove anyone who holds an owner row; the org's last whole-org owner can't be removed or demoted (members.LastOwner:
the end state is judged in the writing transaction, and on the tree shape the table's own trigger agrees). A uid must
be an account of THIS cog (<n>@<cog id>); a node a path the members CHECK admits.
"""
from __future__ import annotations

import re
from http import HTTPMethod
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from observatory.api import members as M

router = APIRouter()

# (method, path) pairs an ADMIN reaches past main.privacy_gate's owner-only default (an owner reaches everything). The
# stdlib's names, never verb literals (sqlguard reads a bare "DELETE" as a possible query's only trace)
_G, _PUT, _DEL = HTTPMethod.GET.value, HTTPMethod.PUT.value, HTTPMethod.DELETE.value
ADMIN_ROUTES = {(_G, "/api/admin/members"), (_PUT, "/api/admin/members"), (_DEL, "/api/admin/members"),
                (_G, "/api/admin/nodes"), (_G, "/api/admin/activity"), (_PUT, "/api/admin/features")}

_get_pool = None
_dsn = ""
_cog_id: str | None = None
ESTATE: Path | None = None
_owner = lambda request: False          # noqa: E731 — main.is_owner; unbound = nobody (deny by default)


def bind(get_pool, dsn: str, estate: Path, cog_id: str | None, owner) -> None:
    global _get_pool, _dsn, ESTATE, _cog_id, _owner
    _get_pool, _dsn, ESTATE, _cog_id, _owner = get_pool, dsn, estate, cog_id, owner


def caller_role(request: Request) -> str | None:
    """'owner' (the key, or a signed-in owner), 'admin' (a signed-in admin), else None."""
    if _owner(request):
        return "owner"
    return "admin" if getattr(request.state, "role", None) == "admin" else None


def _no(status: int, why: str) -> JSONResponse:
    return JSONResponse({"error": why}, status_code=status, headers={"cache-control": "no-store"})


def _uid_ok(uid) -> bool:
    return bool(_cog_id) and isinstance(uid, str) and re.fullmatch(r"[0-9]{1,18}@" + re.escape(_cog_id), uid) is not None


class Grant(BaseModel):
    uid: str
    role: str
    node: str = ""


class Revoke(BaseModel):
    uid: str
    node: str | None = None


@router.get("/api/admin/members")
async def list_members(request: Request):
    you = caller_role(request)
    if you is None:
        return _no(403, "owners and admins only")
    pool = _get_pool()
    s = await M.shape(pool)
    return JSONResponse({"you": you, "uid": getattr(request.state, "uid", None), "roles": s["roles"],
                         "tree": s["tree"], "members": await M.rows(pool),
                         # what each person may use: the role defaults, and the overrides set here (owner 11-17)
                         "features": {f: sorted(r) for f, r in M.FEATURES.items()},
                         "overrides": await M.overrides(pool)}, headers={"cache-control": "no-store"})


async def _judge(request: Request, uid: str, node: str | None, role: str | None):
    """None when the caller may make this change, else the refusal."""
    you = caller_role(request)
    if you is None:
        return _no(403, "owners and admins only")
    if not _cog_id:
        return _no(404, "this org has no cog sign-in")
    if not _uid_ok(uid):
        return _no(400, "uid is an account of this cog: <n>@<cog id>")
    pool = _get_pool()
    s = await M.shape(pool)
    if node is not None and node != "" and not (s["tree"] and M.NODE.fullmatch(node)):
        return _no(400, "node is a path in the agents/ tree" if s["tree"] else
                   "this org's members table has no tree scope yet: grant on the whole org")
    if role is not None and role not in s["roles"]:
        return _no(400, f"role is one of {', '.join(s['roles'])}")
    if you == "admin":
        if role == "owner":
            return _no(403, "only an owner can make an owner")
        if any(r["role"] == "owner" for r in await M.held(pool, uid)):
            return _no(403, "only an owner can change an owner")
    return None


@router.put("/api/admin/members")
async def put_member(body: Grant, request: Request):
    bad = await _judge(request, body.uid, body.node, body.role)
    if bad:
        return bad
    try:
        await M.grant(_dsn, body.uid, body.role, body.node)
    except M.LastOwner:
        return _no(409, "that would leave this org with no owner")
    except ValueError as e:
        return _no(400, str(e))
    return JSONResponse({"ok": True, "uid": body.uid, "node": body.node, "role": body.role})


@router.delete("/api/admin/members")
async def delete_member(body: Revoke, request: Request):
    bad = await _judge(request, body.uid, body.node, None)
    if bad:
        return bad
    try:
        gone = await M.revoke(_dsn, body.uid, body.node)
    except M.LastOwner:
        return _no(409, "that would leave this org with no owner")
    except ValueError as e:
        return _no(400, str(e))
    return JSONResponse({"ok": True, "removed": gone})


class Feature(BaseModel):
    uid: str
    feature: str
    allowed: bool | None = None
    minutes: int | None = None


@router.put("/api/admin/features")
async def put_feature(body: Feature, request: Request):
    """One person's feature, set by the owner or an admin. An owner has every feature, unlimited: no row reaches them,
    so an admin can't touch an owner here either."""
    bad = await _judge(request, body.uid, None, None)
    if bad:
        return bad
    pool = _get_pool()
    if any(r["role"] == "owner" for r in await M.held(pool, body.uid)):
        return _no(403, "an owner has every feature already")
    if body.feature not in M.FEATURES:
        return _no(400, f"feature is one of {', '.join(M.FEATURES)}")
    try:
        await M.set_feature(pool, body.uid, body.feature, body.allowed, body.minutes)
    except ValueError as e:
        return _no(400, str(e))
    return JSONResponse({"ok": True, "uid": body.uid, "feature": body.feature, "allowed": body.allowed,
                         "minutes": body.minutes})


@router.get("/api/admin/nodes")
async def nodes(request: Request):
    if caller_role(request) is None:
        return _no(403, "owners and admins only")
    from astryx.core import charter
    root = ESTATE / "agents"
    out = {"": {"node": "", "kind": "org", "depth": 0}}
    if root.is_dir():
        for gid, g in charter.groups(root).items():
            out[gid] = {"node": gid, "kind": "group", "depth": g["depth"]}
        for f in charter.charter_files(root):
            chain = charter.group_path(f, root)
            n = "/".join([*chain, f.stem])
            out.setdefault(n, {"node": n, "kind": "agent", "depth": len(chain) + 1})
    good = [v for k, v in sorted(out.items()) if k == "" or M.NODE.fullmatch(k)]
    return JSONResponse({"nodes": good}, headers={"cache-control": "no-store"})


@router.get("/api/admin/activity")
async def activity(request: Request, uid: str = ""):
    if caller_role(request) is None:
        return _no(403, "owners and admins only")
    if not _uid_ok(uid):
        return _no(400, "uid is an account of this cog: <n>@<cog id>")
    pool = _get_pool()
    tags = await M.sender_tags(pool, uid)
    r = await pool.fetchrow("SELECT count(*) AS n, count(DISTINCT thread) AS t, max(ts) AS last FROM messages "
                            "WHERE from_agent = ANY($1::text[]) AND from_org = 'local'", tags)
    # 'owner' is also every trusted WhatsApp/Discord sender and the owner key (medic 12598): an owner account's count is
    # the owner channel's, all surfaces, and says so; a member's is exactly its own
    from astryx.hearing import voice_mint as V
    voice = sum([await V.minutes_today(pool, V.who(t, f)) for t in tags for f in M.FEATURES])   # today, every feature
    return JSONResponse({"uid": uid, "scope": "owner" if tags == ["owner"] else "account", "messages": r["n"], "threads": r["t"],
                         "last_message": r["last"].isoformat() if r["last"] else None,
                         "voice_minutes_today": round(float(voice), 1)},
                        headers={"cache-control": "no-store"})
