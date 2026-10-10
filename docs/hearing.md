# Hearing — S1, the ear (plan-8674)

The observatory gets an always-on ear. In-browser VAD cuts speech segments, a local STT backend transcribes them on
this host, and each transcript becomes one row in `utterances` with short retention. S1 has **no agents**: nothing
hears an utterance yet, and nothing acts on one. The design of record is #42048/#42059, re-scoped by the owner's
ruling of 2026-10-10 (seed #42311): **one database for every agent; information in astryx is shared and usable by
every other agent.** There is no separate ear database.

## What S1 ships

| piece | where |
|---|---|
| `utterances` in the org's one database, partitioned by UTC day | `nucleus/schema.sql` |
| Retention: day partitions made ahead, an expired day `DROP`ped whole; the catalog-only TTL arm | `nucleus/ear_store.py` (`maintain`, `ttl_findings`) |
| Retention on schedule (the pulse, every 15 min) | `nucleus/shipped_triggers/ear_retention.py` |
| D4 lease seam (`leases`): EAR/MUTED, one ear per room | `nucleus/ear_lease.py`, `nucleus/schema.sql` |
| The ear service: owner-gated upload, pluggable STT, drop-oldest queue | `bridges/ear.py`, `bridges/ear_stt.py` |
| Observatory: mic indicator plus one-tap mute, browser VAD, `/ear/` proxy | `observatory/web/src/components/EarControl.tsx`, `src/ear/vad.ts`, `observatory/api/main.py` |
| Unit `astryx-ear.service`, generated only when `EAR_ENABLED=1` | `init.sh` `units()` |

## The claim sheet (S1). Every line is graded, and none is rounded up

| party / path | grade | evidence (RED arm) |
|---|---|---|
| **Who can read utterances** | **Every agent, by design** (owner ruling 2026-10-10): `utterances` is an ordinary table in the shared astryx database, readable like every other table. What bounds it is TIME, not access: partition retention. | `nucleus/schema.sql`. |
| **Outside party, via the ear upload** | **PREVENTION.** Every `/ear/api/*` route except health needs the observatory owner key, sent in the `x-obs-key` header only. A query-string key, a cookie or CORS gets nothing, and a foreign `Origin` gets a 403. | `tests/test_ear_service.py`: an unauthenticated POST → **401, 0 rows**. A wrong key, a key in the query and a foreign origin are refused. The same checks pass through the observatory proxy, which adds no authority. |
| The upload gate's strength | **The gate is exactly as strong as `OBS_KEY`'s exposure.** The ear takes it from the `x-obs-key` header only. But the observatory's pre-existing `eventsUrl()` puts the same key in `?key=` for SSE (EventSource can't send headers), so it can land in access logs and proxy or browser history. Stated, NOT fixed in S1. | `observatory/web/src/api.ts` `eventsUrl()`. |
| **Outside party, via the database** | **Host-only.** genesis-pg binds 127.0.0.1:5432 only, persisted in `/home/umair/genesis/services/pg/docker-compose.yml`. | Measured 2026-10-10: `ss -ltn` shows LISTEN 127.0.0.1:5432 only; `docker inspect` PortBindings HostIp is 127.0.0.1 (container created 09:52Z). |
| Outside party, via speech ("seed, push") | **Nothing to prevent in S1.** No agent receives any utterance. From S2 on, see the S2 sheet below. | (S2) |
| Outside party, via DoS | **Bounded.** Only the owner can post. A segment is capped at 30 s or 2 MB. The STT queue is bounded and drops the OLDEST segment, and drops, backlog or a backend failure show as "degraded". | `test_ear_service.py` queue arms: 2 of 5 dropped, the newest survive, DEGRADED with the reason. |
| **The raw transcript is never on the WIRE** | **The ear service never writes it to the wire: PREVENTION by construction.** The ear service has no code path that writes `messages`, calls `wire_insert` or NOTIFYs. A transcript is a row in `utterances`, nothing else. **Scope:** that construction covers the ear's own write paths only. `utterances` is readable by every agent (the ruling above), so an agent that SELECTs a row and quotes it in a `send` is outside it. That case is **convention-grade, not prevented**. | `test_ear_service.py`: after the fake and the real-whisper uploads no `messages` row carries the text and the wire count is unchanged; a static arm finds no wire write in `bridges/ear.py`. Red control: a planted `messages` row carrying the text IS seen by the same check. |
| Text in the ear service's logs | **PREVENTION by construction.** No print or log carries text, errors are named by exception TYPE only, and audio is decoded in memory and never written to disk. | `test_ear_service.py`: the real service on real whisper transcribes a known clip. The row carries its words, and the whole stdout+stderr (what journald receives) carries **0** of them. Red control: a sink that `print()`s the text is caught by the same grep. Postgres-side: `log_statement=none`, and a failing statement logs placeholders, not parameters (`log_parameter_max_length_on_error=0`), as measured. |
| Retention (the live window) | **LOGICAL erasure at the TTL** by `DROP` of the day partition, never `DELETE`. The default TTL is 3 days (`EAR_TTL_DAYS`, clamped to [1, 7]: 3650 in `.env` reads as 7, so a longer window is a reviewed code change, never an `.env` edit). A partition is dropped once its START passes the TTL, so the live table keeps text for at most TTL days. There is no DEFAULT partition: a row with no day to land in is refused. Run by the ear service (start, before writes) and by the pulse every 15 minutes, so an idle week still expires. A pass DROPs first and runs each statement alone, so one bad partition (an overlapping hand-made or restored table) never stops erasure. Its failure is returned, and the pulse reports it. | `tests/test_ear_store.py` (fixture DB): a partition planted 1 day past the TTL is RED and `maintain` DROPs it; a DEFAULT partition is RED; a row with no partition is refused; with retention broken the trigger reports the RED once and re-nags daily. a4's arm: an expired day plus a hand-made partition overlapping tomorrow; the expired words are gone after `maintain`, the other days are made, and the create failure is reported by the trigger (red control: the drop-after-create code raised and kept the words). The knob's clamp has its own arm. |
| **Retention beyond the live window** | **Two copiers of the whole database, stated.** (1) `nucleus/backup.sh` dumps it nightly, `utterances` included, and keeps the last N dumps (default 14). So a word can outlive the TTL for as long as **the last 14 nightly dumps** go back. That is about 14 days when every night runs. Rotation is by COUNT, not age (backup.sh:254), so a skipped night makes the oldest kept dump older; org_runners' 48 h staleness alarm reports a skipped run. (2) A branch-check run base (`nucleus/branch_check_prep.build_base`) pg_dumps the whole database too, so it **excludes `utterances` data** (`DUMP_EXCLUDE`, `--exclude-table-data-and-children`; plain `--exclude-table-data` misses the partitions). A killed run's leftover base then holds the table but no words. Physical erasure is not claimed either: dropped tuples survive in recycled WAL until overwritten. | `nucleus/backup.sh` (`KEEP=${1:-14}`). `tests/test_ear_store.py` R2: a dump with `DUMP_EXCLUDE` on the fixture keeps the table and none of its rows; red control: the same dump without it carries the words. |
| Mic state is never hidden (d) | The header pill is always present for the owner. MUTED is enforced **server-side**, not only in the page. | `test_ear_service.py`: while MUTED the holder's upload → **423, 0 rows**. `tests/test_ear_lease.py`: MUTED has no TTL, can't be claimed, and only unmute ends it. |
| The page is never blocked (e) | Fail-open: the ear down → "ear offline". | `test_ear_service.py`: through the proxy with the ear down → 502 "ear offline". |
| Speaker attribution | Every S1 row says `speaker='unknown'`. There is no attribution at all, and it is never used for authority. | (row arm) |
| Only speech leaves the page | The browser's energy VAD; the server runs silero as a second filter. | `tests/test_ear_vad.py` runs the exact `vad.ts` under node: 5 s of room noise → **0 segments**, and the known clip → 1 segment. |

**Not claimable, stated:** physical erasure (WAL); erasure from backups before the backup's own retention ends (the last 14 nightly dumps, about 14 days past the TTL when every night runs); that an agent which reads `utterances` never quotes it on the wire (convention, not prevention).

## Measured: the real-time factor (the GPU baseline)

Host: 4 cores, CPU only, shared with the residents. Backend `faster-whisper:small:cpu:int8` (`EAR_STT_BACKEND=cpu`), greedy decoding (beam 1), silero VAD filter on. Clip: 10.03 s of English speech (alsa-utils' test voices).

| run | load avg (1 min) | wall | RTF |
|---|---|---|---|
| best observed | 12.2 | 10.13 s | **1.01** |
| typical | 9–12 | 11–21 s | 1.1–2.1 |
| under heavy load | 13.7–20 | 27–68 s | 2.7–5.8 |
| beam 5, for comparison | 9.4 | 15.4 s (best) | 1.53 |

Model load is 3–12 s. **On this CPU the ear is never faster than real time.** Continuous speech outruns it, and the drop-oldest queue and the "degraded" indicator are what keep it current. The `cuda` backend (float16, beam 5) is one config line away when the GPUs arrive. Re-measure with `tests/test_ear_service.py`, which prints the numbers.

## Deploying S1 (owner)

1. `./init.sh` applies `schema.sql` (adds `utterances` and `leases`) once this branch is committed on main.
2. `venv/bin/python -m nucleus.ear_store maintain` makes the first day partitions (the service and the trigger also do).
3. Add `EAR_ENABLED=1` to `.env`, then run `./init.sh` again to generate `units/astryx-ear.service`.
4. Install the units (sudo) and restart the observatory so it picks up the `/ear/` proxy. Rebuild the web with `nucleus/deploy.sh`.
5. Install the retention trigger: `printf 'from nucleus.shipped_triggers.ear_retention import ear_retention  # noqa: F401\n' > triggers/seed/ear_retention.py`.
6. Verify: `venv/bin/python -m nucleus.ear_store ttl`.

## S2: one agent hears its name (a4 #42048 D3 + D5)

An agent opts in by having `sensors/<agent>/hear.py` (`def hear(utt) -> {"decision": "pass"|"ignore", "matched_name"}`;
the contract is in `nucleus/hear_worker.py`). Each stored utterance goes to each opted-in agent's worker. A validated
pass becomes a `hearings` row, a POINTER with no text, and, under the agent's hourly wake cap, one wake on the wire from
`ear`, intent `hearing`. The agent reads what was said to it with `nucleus/ear_fetch.py <id>`.

| piece | where |
|---|---|
| bwrap'd hear() workers: deadline, kill + respawn, bench after 3 overruns, hot reload on mtime | `nucleus/hear_pool.py`, `nucleus/hear_worker.py` |
| The dispatcher's validation (its own name, present in the text, span ≤30 words from it) | `nucleus/hear_pool.validate` |
| The pointer: `hearings` (no text column; typed `speaker_verified`, CHECKed false) | `nucleus/schema.sql` |
| Wake + cap, its own thread and drop-oldest queue; `attending`/`caught` in status | `bridges/ear.py` `Hearing` |
| Span-fetch (door 2), fenced | `nucleus/ear_fetch.py`, `nucleus/ear_fence.py` |
| Fence redaction before every turns/steps write | `hooks/step.py` `cleaner()` |

| party / path | grade | evidence (RED arm), all in `tests/test_hearing.py` unless named |
|---|---|---|
| A hear() that hangs (a TV chooses the text, a catastrophic regex) | **Bounded.** Killed at `EAR_HEAR_MS` (200 ms) after a ready handshake; 3 overruns in a row bench it for 60 s; counted per agent in status. Other agents still hear the same utterance. | a `while True` hear() is killed and seed still passes; benched after 3; a benched worker is skipped. |
| A hear() that prints the utterance | **PREVENTION.** The worker's stdout and stderr are /dev/null; its one way out is the answer pipe. | 0 bytes of the text on the parent's stdout+stderr. RED control: the same hear() in-process prints it. |
| What a hear() can reach | **PREVENTION by sandbox.** bwrap: no network, no /home (no `.env`, no repo), env of PATH and LANG only. Without bwrap the pool runs no hear() at all and attends nobody (fail closed for agents, open for the room). | the worker's env has no DSN although the parent's does; /home absent; a socket to 127.0.0.1:5432 fails; no-bwrap arm. |
| A hear() lying about what it caught | **PREVENTION.** The dispatcher accepts a pass only for the agent's OWN name, present in the text; it sets the span itself (≤30 words from the name). Hearings' CHECKs repeat the bound. | another name, an absent name, gist, junk → no pass; a 99-word span → 30 from the name; a 31-word span row refused. |
| The raw transcript on the WIRE (ear side) | **PREVENTION by construction, narrowed.** The ear's ONE `messages` write is the wake, and its body is `wake_body(hid)`, a function of the hearing id only. | the wake bodies carry no word of the utterance (RED control: the row does); `test_ear_service.py` static arm: exactly one site, body `wake_body(hid)`, no NOTIFY. |
| The fetched copy in the org's tables | **PREVENTION for the fenced copy.** `hooks/step.py` redacts every `{{ear h<id>}}…{{/ear}}` to its pointer before turns/steps are written; an unterminated fence redacts to the end. This holds for the tool's output as printed; a copy the agent transforms (piped through `tail`, `sed`, `tr`, which can drop the opener or rewrite the braces) is unfenced and stored, so it is **convention-grade**, like a restatement in the agent's own words. | the cleaner drops the words and keeps the pointer; RED control: the secret redaction alone keeps them. |
| A restatement outside the fence (the agent quotes it in its own words or a send) | **Not prevented; detection is S3** (the reconciler). | (S3) |
| Who may fetch | **Detection grade.** `ear_fetch` serves only the hearing's own agent (`ASTRYX_AGENT`, same uid), stamps `fetched_at`. It is not an access boundary: `utterances` is readable by every agent by the owner's ruling. | another agent → exit 2, no words; `fetched_at` stamped. |
| The pointer after retention | The pointer outlives the day; a fetch says **expired**. | the day's partition dropped → exit 3. |
| Outside party, via speech ("seed, push") | **Typed provenance, no authority.** The wake comes from `ear`, never `owner`; its body and every fetch say the speaker is UNVERIFIED, and `hearings.speaker_verified` is CHECKed false. A hearing-origin wake carries no authority: it is typed UNVERIFIED and comes from `ear`, and an agent acting on it does so under local.md's data-never-instructions, which is **convention-grade**. D5's authenticated confirm is **withdrawn by its author** (a4 #43916) until a single owner-authority actuator exists to key it on: merges, sends and trigger_set are separate doors today. | test_hearing POINTER: an INSERT with speaker_verified=true is refused by the CHECK; the wake body and fetch output say UNVERIFIED. |
| Fan-out / wake flood | **Bounded.** `EAR_WAKE_CAP` wakes per agent per hour (default 6); over the cap the pointer is kept with `woke=false`, no wake, counted in status. The dispatcher's queue is 16, drop-oldest, counted. | cap 2: three passes → two wakes, the third pointer woke=false with no message. |
