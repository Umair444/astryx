"""astryx · THE ONE SEAM that turns an approved org request into an org (cog-rebuild Phase 3, owner 11-13).

    provision_org(key, owner_uid, allowance_tokens) -> dict

Called by the cog's front when a cog admin approves a sign-up (observatory/front.py POST /auth/cog/requests/{id}/approve,
off the event loop), after the request row is already `approved` with its budget. The front records what happened in
that row (org_requests.provision / provision_note), so a deferred or failed provisioning is never lost: it is the
queue a provisioner works from once one exists.

NOT BUILT HERE, ON PURPOSE. The org model is being rebuilt on feat/cog-rls2 (DESIGN.md "DECIDED" + "CORRECTIONS
11-13"). The old provisioner, devtools/cog_add_org.py, makes a database, a HOME and a registry file per org with a
superuser DSN and root: neither the target shape nor safe from the front's process. Until feat/cog-rls2 lands its
devtools/cog_roles.py, this raises ProvisionUnavailable before touching anything, and the front leaves the request
approved with provision 'deferred'.

THE CONTRACT (owner ruling 11-13: an org is ONE row in astryx.orgs + ONE login role, NOTHING else). The real
implementation (feat/cog-rls2's devtools/cog_roles.py) replaces _create and does exactly:
  1. INSERT the org's row into astryx.orgs (tenant = key).
  2. CREATE the org's ONE login role (NOSUPERUSER, NOBYPASSRLS), with the shared grants; row-level security maps the
     role to its org. NO per-org schema and NO per-org database: agent-authored tables live in the shared `store`
     schema under the org-key prefix `<key>__…`, a rule the RLS branch's event trigger enforces (not this seam).
  3. Write the org's .env: its DSN (that role, the shared database) and ASTRYX_ORG_BUDGET_TOKENS=<allowance_tokens>
     (scripts/spawn.sh refuses a non-primary org's residents without a budget: runtime_env.py budget_gate) and NO login
     of the host owner's: the org brings its own (CLAUDE_CODE_OAUTH_TOKEN, or an opted-in key).
  4. Give `owner_uid` (the account's sub, "<n>@<cog id>") the org's whole-org owner row (cogauth.grant, as that role).
  Idempotent: a re-run for the same (key, owner) is a no-op returning the same answer; a key held by another org is a
  ValueError. Never run with the front's credentials: the privileged step (the role) belongs to a host provisioner the
  front only ASKS (this row is the ask). And DESIGN.md's GATE stands: public sign-up (ASTRYX_COG_SIGNUP) is not opened
  before the per-org sandbox exists.
  Returns {"state": "done", "org": key, "role": <the role's name>}.
"""
from __future__ import annotations

import re

KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")          # orgs.NAME, restated so this module imports nothing
OWNER = re.compile(r"[0-9]{1,18}@[a-z0-9][a-z0-9-]{7,63}")  # cogauth.sub: <account id>@<cog id> (orgs.COG_ID)
WAITING_ON = "feat/cog-rls2 (devtools/cog_roles.py)"


class ProvisionUnavailable(NotImplementedError):
    """No provisioner exists yet: the request stays approved, its provision 'deferred' (nothing was created)."""


def provision_org(key: str, owner_uid: str, allowance_tokens: int) -> dict:
    """Make org `key` (its orgs row + its one login role + its .env/DSN with the budget) with `owner_uid` as its owner,
    per the module's CONTRACT. Arguments are checked first: a bad one is a ValueError (the front's bug, never a
    deferral)."""
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise ValueError("key is not an org name (orgs.NAME)")
    if not isinstance(owner_uid, str) or not OWNER.fullmatch(owner_uid):
        raise ValueError("owner_uid is not an account of a cog (<n>@<cog id>)")
    if type(allowance_tokens) is not int or allowance_tokens <= 0:
        raise ValueError("allowance_tokens is a positive whole number")
    return _create(key, owner_uid, allowance_tokens)


def _create(key: str, owner_uid: str, allowance_tokens: int) -> dict:
    # feat/cog-rls2: replace this body with devtools/cog_roles.py's provisioner (the CONTRACT above: orgs row + one role + .env;
    # nothing per-org in the schema), reached through
    # the host provisioner (item 5), never by giving this process a superuser DSN.
    raise ProvisionUnavailable(f"org provisioning waits on {WAITING_ON}: nothing was created")
