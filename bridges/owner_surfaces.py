"""Which owner-addressed rows a BRIDGE delivers: one predicate, so a surface that marks rows read on sight (the
observatory's thread pane, /api/thread/read) never pre-empts a bridge's delivery (a4 #57418).

Over rows with to_agent='owner' AND to_org='local' AND status='pending', a bridge owns the row when:
  - thread is NULL or ''        whatsapp.deliver: the un-threaded owner doorbell
  - thread LIKE 't-%'           whatsapp.deliver: the wire's auto-minted thread IS the "reach the owner" path
  - thread LIKE 'wa:%'          whatsapp.deliver: the thread names the destination
  - thread LIKE 'tg:%' / 'dc:%' telegram.py / discord.py listen predicates
  - thread LIKE 'cv:%'          canvas.py CLAIM
  - thread LIKE 'tier-%', or delivery carries a release   plan-9139 releases, delivered by the stamped bridge
  - thread LIKE 'ear-%'         ear.py's own sheet marks them (observatory:ear)
Every other named thread (thread 'owner', a proposals thread, obs:*) has no bridge: whatsapp.deliver skips it and
leaves it pending for the observatory. Dependency-free on purpose: the observatory imports it without the bridges'
runtime. A bridge that starts serving a new owner thread shape adds it HERE, or the pane marks its rows read first.
"""

OWNER_ROW_BRIDGED_SQL = (
    "(thread IS NULL OR thread = '' OR thread LIKE 't-%' OR thread LIKE 'wa:%' OR thread LIKE 'tg:%' "
    "OR thread LIKE 'dc:%' OR thread LIKE 'cv:%' OR thread LIKE 'tier-%' OR thread LIKE 'ear-%' "
    "OR delivery->'release' IS NOT NULL)"
)
