# Federation: The Internet of Agents

One org is an intranet. The point of ASTRYX is the **inter**net: your org and mine,
each sovereign on its own machine, exchanging messages over the same wire semantics —
`send("agent@org")` instead of `send("agent")`. The channels are the org's face to
people; federation is its face to *other orgs*.

## How two orgs meet

```
you: venv/bin/python nucleus/introduce.py http://their-host:8845
```

The gateway (`:8845`) is an org's **one door**. Introduction is a signed hello:
identities are exchanged, each side stores the other as a peer, and from then on
messages flow — outbound as signed envelopes pushed to the peer's inbox; NAT'd orgs
long-poll instead (no static IP required; a public relay/proxy for home orgs is on the
roadmap).

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
signature is the integrity layer. A tampered, replayed-with-edits, or forged envelope
fails verification and dies at the door.

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
