// cog-who (cog-rebuild P2, option (a)): the asker's ROLE for an inbound's <channel> attributes. from= already names
// WHO asked (owner, cv-<label>.<uid> a signed-in member, cv-<name> a canvas guest, wa-<n>); role is the one fact
// from= can't carry, read from the stamp the observatory writes on a member's row (delivery.role, the
// {surface, display_name} shape bridges/canvas.py already writes). Only a known role on a non-owner row: the owner's
// rows carry none (his notifications are unchanged), and no stamp can mint 'owner'. Its own module so
// tests/test_who_asked.py can EXECUTE it (as address.mjs), not grep server.mjs.
const ROLES = new Set(['member', 'admin', 'viewer'])

export function asker(row) {
  const r = row?.delivery?.role
  return typeof r === 'string' && ROLES.has(r) && row.from_agent !== 'owner' ? r : ''
}
