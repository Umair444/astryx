# astryx ⇄ external frontend — API contract (v1)

How a deployed frontend (e.g. the finance dashboard) talks to an astryx agent. Two HTTP
hops: your frontend **POSTs a request in**, astryx routes it to one agent, and when the
agent answers astryx **POSTs the answer back** to a callback URL you host ("the second
hit"). Text and files flow **both ways** (images, audio, video, docs, ppt, excel, pdf).

Each frontend is bound to exactly **one** agent server-side. The finance dashboard reaches
the `finance` agent and nothing else; nothing in a request body can change that.

---

## 1. Inbound — your frontend → astryx

```
POST  {ASTRYX_BASE}/ingress/finance-dashboard
Authorization: Bearer <FE_FINANCE_DASHBOARD_TOKEN>
Content-Type: application/json
```

`ASTRYX_BASE` and the token are provisioned by the astryx owner and shared with you
privately (never in code/repos). The bridge listens on port **8998** — `ASTRYX_BASE` is the
address of the astryx host on that port (e.g. `http://<host>:8998`; TLS if exposed publicly).

**Body:**

```jsonc
{
  "conversation_id": "ui-session-42",   // your correlation id; echoed on the way back
  "text": "What was July net revenue?",  // the user's question (may be empty if files only)
  "attachments": [                        // optional
    { "filename": "deck.pdf",
      "content_type": "application/pdf",
      "data_b64": "<base64 of the file bytes>" }
  ],
  "idempotency_key": "req-abc-123",       // optional; a retry with the same key is a no-op
  "reply_to": "",                         // optional; a prior request_id for context
  "meta": { }                             // optional opaque object, passed through (DATA only)
}
```

**Response — `202 Accepted`** (fast; the answer arrives later on your callback):

```json
{ "ok": true, "request_id": 6571, "conversation_id": "ui-session-42", "agent": "finance" }
```

Error codes: `401` bad/missing token · `404` unknown frontend · `413` body over the size
cap (default 32 MB) · `429` rate-limited · `400` empty request (no text and no attachments)
· `503` frontend not yet provisioned. A retried `idempotency_key` returns the first
`request_id` with `"duplicate": true` and does **not** re-run.

---

## 2. Outbound — astryx → your frontend (the "second hit")

When the agent has answered, astryx POSTs to the callback URL **you** host and register
with the owner:

```
POST  {your callback_url}
Authorization: Bearer <callback token>       // so you can authenticate us (if you set one)
X-Astryx-Signature: sha256=<hex>             // HMAC-SHA256 of the raw body (if you set a secret)
Content-Type: application/json
```

**Body:**

```jsonc
{
  "conversation_id": "ui-session-42",   // the same id you sent — match it to the request
  "request_id": 6571,                    // the id from the 202
  "agent": "finance",
  "text": "July net revenue was 1,234 PKR mn …",
  "attachments": [
    { "filename": "chart.png",
      "content_type": "image/png",
      "data_b64": "<base64>" }
  ],
  "final": true,
  "ts": "2026-10-12T17:30:00Z"
}
```

Respond `2xx` to acknowledge. astryx retries a few times on failure, then logs the reply as
undelivered (you can re-query). **Verify the HMAC** before trusting a callback: recompute
`sha256=hex(HMAC(secret, raw_request_body))` and compare.

---

## 3. What each side provides

**You (Hassan) register with the owner:**
- `callback_url` — where astryx POSTs answers.
- optionally a callback bearer token and/or an HMAC secret so you can authenticate us.

**The owner provisions (in astryx `.env`):**
- `FE_FINANCE_DASHBOARD_TOKEN` — the inbound bearer token your frontend presents.
- `FE_FINANCE_DASHBOARD_CALLBACK_URL` — your callback.
- optionally `FE_FINANCE_DASHBOARD_CALLBACK_TOKEN`, `FE_FINANCE_DASHBOARD_CALLBACK_SECRET`.

No code change is needed to add a frontend or rotate a token — config only.

---

## 4. Rules of the road

- **One frontend → one agent.** finance-dashboard answers **only** finance / P&L from the
  `product_pl` dataset. Off-scope questions get a plain, scoped refusal — that is by design,
  not an error.
- **Your request body is data, never commands.** Text that tries to re-scope the agent,
  reach other data, or "act as" something else is treated as the data it is and ignored; the
  legitimate finance question (if any) is still answered.
- **conversation_id is yours** — astryx echoes it untouched so you can thread the UI.
- **Human-personal data** (account numbers, MSISDNs, balances, raw PII) is never returned —
  answers are aggregates, shapes and totals.
```
