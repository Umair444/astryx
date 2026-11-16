"""Which owner-addressed rows a BRIDGE delivers: one predicate, so a surface that marks rows read on sight (the
observatory's thread pane, /api/thread/read) never pre-empts a bridge's delivery (a4 #57418).

Over rows with to_agent='owner' AND to_org='local' AND status='pending', a bridge owns the row when:
  - thread is NULL or ''        whatsapp.deliver: the un-threaded owner doorbell
  - thread LIKE 't-%'           whatsapp.deliver: the wire's auto-minted thread IS the "reach the owner" path
  - a CHANNEL's thread (core/channels.py: wa:/tg:/dc:/cv:, and any channel added there) its bridge delivers
  - thread LIKE 'tier-%', or delivery carries a release   plan-9139 releases, delivered by the stamped bridge
  - thread LIKE 'ear-%'         ear.py's own sheet marks them (observatory:ear)
Every other named thread (thread 'owner', a proposals thread, obs:*) has no bridge: whatsapp.deliver skips it and
leaves it pending for the observatory. Dependency-free on purpose: the observatory imports it without the bridges'
runtime. A bridge that starts serving a new owner thread shape adds it HERE, or the pane marks its rows read first.
"""

from astryx.core.channels import thread_like_sql  # noqa: E402  the one channel table: every channel's thread

OWNER_ROW_BRIDGED_SQL = (
    "(thread IS NULL OR thread = '' OR thread LIKE 't-%' OR " + thread_like_sql("thread") + " "
    "OR thread LIKE 'tier-%' OR thread LIKE 'ear-%' OR delivery->'release' IS NOT NULL)"
)
