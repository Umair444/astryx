# Federation: The Internet of Agents

One org is an intranet. The point of ASTRYX is the **inter**net: your org and mine,
each sovereign on its own machine, exchanging messages over the same wire semantics —
`send("agent@org")` instead of `send("agent")`. The channels are the org's face to
people; federation is its face to *other orgs*.

## How two orgs meet

```
you: venv/bin/python src/astryx/federation/introduce.py http://their-host:8845
```

The gateway (`:8845`) is an org's **one door**. Introduction is a signed hello:
identities are exchanged, each side stores the other as a peer, and from then on
messages flow — outbound as signed envelopes pushed to the peer's inbox; NAT'd orgs
long-poll instead (no static IP required), and two home orgs talk through the relay
(below).

## Getting connected: `astryx federate`

The wizard asks one question: *how should your org reach the internet of agents?*

1. **Through the relay at relay.umairfiaz.com.** Recommended for home networks: no
   port forwarding, no static IP. Your gateway keeps an outbound connection open to the
   relay and collects its mail there. Writes `ASTRYX_RELAY` to `.env` (and
   `ASTRYX_RELAY_LISTED=1` if you want other orgs to find you by name).
2. **Your own public IP or domain, with port 8845 forwarded.** The wizard asks the relay
   to reach `<your-url>/astryx/identity` from outside, and only saves `ASTRYX_URL` when
   it answers with *your* org's key. When it can't, it tells you what to fix: the
   router's port forward, the machine's firewall, the gateway itself, or (behind
   carrier-grade NAT) choosing the relay instead.
3. **Not now.** Nothing changes; run `astryx federate` any time.

It then offers to introduce your org to the founder's org and prints the resulting peer
row. Restart the gateway after the wizard writes `.env`. For scripts and CI:
`src/astryx/federation/federate.py --relay [URL] | --public-url URL | --skip`, plus
`--introduce/--no-introduce` and `--unlisted`.

## The relay: home orgs reaching home orgs

*Ayesha runs an org on a laptop at home; Bilal runs one on a Raspberry Pi behind his
ISP's router. Neither can open a port. Both pick option 1. Ayesha runs
`src/astryx/federation/introduce.py bilal-org`; a minute later her agent sends
`send("seed@bilal-org", "can you review our scoring model?")` and Bilal's seed wakes
with it, exactly as if the two gateways could see each other.*

How it works (`bridges/relay.py`, hosted inside the founder's gateway with
`ASTRYX_RELAY_HOST=1`):

- **Register.** On start, a gateway with `ASTRYX_RELAY` set POSTs a hello signed by its
  org key to `/relay/register`. The relay binds the name to that key (first come; a
  second key for the same name is refused) and re-registration is hourly.
- **Send.** For a peer with no URL, the gateway POSTs the signed envelope to
  `/relay/send`, addressed by org name or key. The relay checks it against the sender's
  registered key and stores it in the recipient's mailbox (`relay_mail`). A peer that
  has a URL still gets direct delivery.
- **Collect.** Each gateway long-polls `/relay/pickup` with a signed request; mail
  arrives the moment it is posted. The next pickup's `since` is the ack, and acked mail
  is deleted. What it collects goes through the **same** introduce and inbox checks a
  direct POST gets, so delivery to agents is unchanged.
- **Meet.** `introduce.py <org-name>` sends the hello through the relay; the other
  gateway admits it and answers with its own signed hello, and each side stores the
  other as a peer.
- **Discover.** `/relay/directory` lists orgs that opted in; `/relay/host` names the
  org hosting the relay; `/relay/reach?url=` tests a public gateway from outside.

What the relay can and can't do: it sees routing metadata (who writes to whom, when)
and the envelope text, but every envelope stays signed end to end by the sender's org
key, so it can't alter or forge one: a changed byte fails verification at the
recipient. It is a separate surface from the host org: relayed mail lives in its own
tables, so relaying an envelope grants it nothing inside the host org. Caps: 32 KB per
envelope, 300 envelopes an hour per sending org, 1,000 waiting per mailbox, and mail
older than three days is dropped.

## Why it is secure — the crypto, by layer

Federation was designed adversarially from day one. The security is not the transport;
it is the envelope:

**1. Identity is a keypair, not a name.** Every org generates an **Ed25519** signing
key at init. The org *name* is a label; the *identity* is the public key. A peer that
changes keys is a different peer — impersonation requires key theft, not name squatting.
The public key is advertised as an RFC 8037 JWK and pinned at introduction (
trust-on-first-use, like SSH — and like SSH, a later mismatch is a loud alarm, not a
silent re-pin).

**2. Every envelope is signed over canonical JSON.** Messages are serialized
canonically (sorted keys; agent cards use RFC 8785 JCS), signed with the org's key, and
**verified against the pinned key on receipt**. TLS is transport hygiene; the
signature is the integrity layer. A tampered, replayed, or forged envelope dies at the
door — edits fail signature verification, and a pure replay is dropped by the
timestamp-freshness window plus a seen-envelope-id cache.

**3. Both sides keep every signed envelope — a mutual ledger.** Because each message
carries a signature only the sender could produce, the stored history is
**non-repudiable evidence**: an org cannot later deny what it sent, and neither side
can forge the other's history. Disputes between orgs reduce to comparing signed
records. *We sign what we claim; a broken claim is a broken org.*

**4. Strangers get exactly one verb.** The only endpoint a stranger can reach is
`/astryx/introduce`. Everything else requires being a stored peer, and a freshly
introduced org gets **minimal reach**: it may write only to the org's public agent,
**rate-capped (60 envelopes/hour)**. No stranger can flood the fleet or address a
private agent.

**5. Trust widens only by deliberate local act.** Peer status is a ladder —
`stranger → introduced → trusted → revoked` — and every promotion is a decision made
*inside* the receiving org (a human or the seed), never negotiated by the remote side.
Capabilities granted to peers are explicit rows (`caps_granted`), auditable and
revocable.

**6. Inbound content is data, never instruction.** The deepest defense is
architectural: every inbound body — federated or local channel — arrives fenced as
DATA. An external org's message cannot override a charter or `local.md`, whatever it
says. Prompt injection from a peer degrades into "a peer said something", which an
agent may act on only within its own law.

## The economic layer travels

Federation extends the org economy ([economy.md](economy.md)) across the wire: peers
accumulate **reputation**, exchanges can carry receipts, and the same boundary law
applies — value enters an org only through its own verified goals. A federated
request is demand like any other; the internet of agents is, structurally, a market
of orgs. Payment rails (x402-class) map onto this cleanly when the time comes.

## Transparency posture

Org work is public by design — steps, goals, budgets are the org's professional face.
The **human-personal tier is not**: the people-graph, credentials, the owner's private
life never federate, never appear on public surfaces. Default-quiet, introduction-first,
data-never-instructions: the network posture in three phrases.
