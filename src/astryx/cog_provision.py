"""astryx · THE ONE SEAM that turns an approved org request into an org (cog-rebuild Phase 3, owner 11-13).

    provision_org(key, owner_uid) -> dict

Called by the cog's front when a cog admin approves a sign-up (observatory/front.py POST /auth/cog/requests/{id}/approve,
off the event loop), after the request row is already `approved` with its budget. The front records what happened in
that row (org_requests.provision / provision_note), so a deferred or failed provisioning is never lost: it is the
queue a provisioner works from once one exists.

NOT BUILT HERE, ON PURPOSE. The org model is being rebuilt on feat/cog-rls2 (DESIGN.md "DECIDED" + "CORRECTIONS
11-13"): an org is a ROW in astryx.orgs plus a per-org non-superuser role in ONE shared schema under row-level security,
not a database per org. The old provisioner, devtools/cog_add_org.py, makes a database, a HOME and a registry file per
org; it needs a superuser DSN and root (for /etc/astryx/cog.json and the org's units), so it is neither the target
shape nor safe to run from the front's process. Until feat/cog-rls2 lands its devtools/cog_roles.py, this raises
ProvisionUnavailable before touching anything, and the front leaves the request approved with provision 'deferred'.

THE CONTRACT the real implementation (feat/cog-rls2's devtools/cog_roles.py) must satisfy when it replaces _create:
  1. INSERT the org into astryx.orgs (tenant = key) and CREATE ROLE org_<key> LOGIN NOSUPERUSER NOBYPASSRLS, with
     astryx_org's grants; its agent-authored DDL lives in schema org_<key>. Idempotent: a re-run for the same key and
     owner is a no-op that returns the same answer; a key held by another org raises ValueError.
  2. Give `owner_uid` (the account's sub, "<n>@<cog id>") the org's whole-org owner row: cogauth.grant(conn, owner_uid,
     "owner", "") on a connection AS org_<key>, so the members row carries that org's tenant.
  3. Write the new org's HOME .env with ASTRYX_ORG_BUDGET_TOKENS=<the approved budget> (scripts/spawn.sh refuses to
     spawn a non-primary org's residents without one: src/astryx/core/runtime_env.py budget_gate) and NO login of the
     host owner's: the org brings its own (CLAUDE_CODE_OAUTH_TOKEN, or an opted-in key).
  4. Public sign-up orgs run their agents in the per-org SANDBOX (container on demand, no host sudo, only their own DB
     role). DESIGN.md's GATE: public sign-up must not be opened (ASTRYX_COG_SIGNUP) before that sandbox exists.
  5. Never run with the front's credentials: the privileged step (CREATE ROLE, the registry) belongs to a host
     provisioner (a root-owned helper or a cog-scoped unit) that the front only ASKS, e.g. by this row.
  Returns {"state": "done", "org": key, "role": "org_<key>"}.
"""
from __future__ import annotations

import re

KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")          # orgs.NAME, restated so this module imports nothing
OWNER = re.compile(r"[0-9]{1,18}@[a-z0-9][a-z0-9-]{7,63}")  # cogauth.sub: <account id>@<cog id> (orgs.COG_ID)
WAITING_ON = "feat/cog-rls2 (devtools/cog_roles.py)"


class ProvisionUnavailable(NotImplementedError):
    """No provisioner exists yet: the request stays approved, its provision 'deferred' (nothing was created)."""


def provision_org(key: str, owner_uid: str) -> dict:
    """Make org `key` with `owner_uid` as its owner, per the module's CONTRACT. Arguments are checked first: a bad one
    is a ValueError (the front's bug, never a deferral)."""
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise ValueError("key is not an org name (orgs.NAME)")
    if not isinstance(owner_uid, str) or not OWNER.fullmatch(owner_uid):
        raise ValueError("owner_uid is not an account of a cog (<n>@<cog id>)")
    return _create(key, owner_uid)


def _create(key: str, owner_uid: str) -> dict:
    # feat/cog-rls2: replace this body with devtools/cog_roles.py's provisioner (the CONTRACT above), reached through
    # the host provisioner (item 5), never by giving this process a superuser DSN.
    raise ProvisionUnavailable(f"org provisioning waits on {WAITING_ON}: nothing was created")
