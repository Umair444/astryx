# Hearing — S1, the ear (plan-8674)

The observatory gets an always-on ear. In-browser VAD cuts speech segments, a local STT backend transcribes them on
this host, and each transcript becomes one row in a separate database with short retention. S1 has **no agents**: nothing
hears an utterance yet, and nothing acts on one. The design of record is #42048, with #42059 as the binding set.

## What S1 ships

| piece | where |
|---|---|
| D1, the ear store: `astryx_ear`, born zero-window. Day partitions, retention by `DROP` | `nucleus/ear_store.py` (`apply`, `maintain`) |
| Catalog-only TTL arm | `ear_store.ttl_findings` (runs as the audit role, which has no privilege on `utterances`) |
| D2 reader census: a login event trigger writes `login_audit`, graded on `session_user` | `ear_store.reader_census`, `owner_report` |
| Copier census and snapper arm. Physical tokens are derived from the DSN's container | `nucleus/ear_census.py`, `nucleus/ear_census_reviewed.json` |
| D4 lease seam (main db `leases`): EAR/MUTED, one ear per room | `nucleus/ear_lease.py`, `nucleus/schema.sql` |
| The ear service: owner-gated upload, pluggable STT, drop-oldest queue | `bridges/ear.py`, `bridges/ear_stt.py` |
| Observatory: mic indicator plus one-tap mute, browser VAD, `/ear/` proxy | `observatory/web/src/components/EarControl.tsx`, `src/ear/vad.ts`, `observatory/api/main.py` |
| Upkeep and the owner-only census on the pulse | `nucleus/shipped_triggers/ear_census.py` |
| Unit `astryx-ear.service`, generated only when `EAR_ENABLED=1` | `init.sh` `units()` |

## The claim sheet (S1). Every line is graded, and none is rounded up

| party / path | grade | evidence (RED arm) |
|---|---|---|
| **Outside party, via the ear upload** | **PREVENTION.** Every `/ear/api/*` route except health needs the observatory owner key, sent in the `x-obs-key` header only. A query-string key, a cookie or CORS gets nothing, and a foreign `Origin` gets a 403. | `tests/test_ear_service.py`: an unauthenticated POST → **401, 0 rows**. A wrong key, a key in the query and a foreign origin are refused. The same checks pass through the observatory proxy, which adds no authority. |
| **Outside party, via the database** | **Reachable from the LAN with credentials**, not host-only. genesis-pg publishes 5432 on 192.168.1.9 as well as 127.0.0.1. `astryx_ear` inherits that exposure until the plan-5497 LAN unbind lands. Its roles authenticate with SCRAM passwords that live only in `~/.pgpass`. | Measured with `docker ps`: `127.0.0.1:5432->5432/tcp, 192.168.1.9:5432->5432/tcp`. |
| Outside party, via speech ("seed, push") | **Nothing to prevent in S1.** No agent receives any utterance. From S2 on this is detection plus an authenticated confirm (D5). | (S2) |
| Outside party, via DoS | **Bounded.** Only the owner can post. A segment is capped at 30 s or 2 MB. The STT queue is bounded and drops the OLDEST segment, and drops, backlog or a backend failure show as "degraded". | `test_ear_service.py` queue arms: 2 of 5 dropped, the newest survive, DEGRADED with the reason. |
| Resident accident: a new copier | **Safe by construction (D1)**: both existing copiers dump one database by name. The **copier census** is a detection arm on top. | `tests/test_ear_census.py`: 15 planted RED controls cover tar, rsync, cp, docker cp and copytree of the source or an ancestor; a non-literal or missing `pg_dump` database; `pg_dumpall`; `pg_basebackup`; any site naming `astryx_ear`; crontab; a unit; a volume. If the container can't be resolved the census exits **77 BLIND, never GREEN**. Live: GREEN, with 6 reviewed pins whose binding is re-verified on every run. |
| Resident accident: a snapshot | **GREEN for a real reason.** Snapper's only config is `root` → `/`, and the data sits on `@home`, a separate mount. | `test_ear_census.py`: a config on `/home` or on an ancestor is RED, and a nested subvolume counts as a boundary. Unreadable configs → BLIND. Other snapshotters (timeshift, btrbk) are **not graded**. |
| Resident accident: psql'ing `astryx_ear` (also an ad-hoc `pg_dump astryx_ear`) | **DETECTION only.** The residents' role is SUPERUSER (M2). Every login writes a `login_audit` row through a login event trigger (enabled ALWAYS). The census grades `session_user` against the declared doors, reports `application_name` as claimed, and reports to the **owner only**. A superuser can disable the trigger, which the census reports as LOUD. A superuser can also delete audit rows, and **that is not detected**. | `tests/test_ear_store.py`: a spoofing outsider (`application_name='astryx-ear-svc'`) is reported. Trigger disabled or dropped → LOUD. Re-apply restores it. |
| The checker reading text | **PREVENTION** (a privilege). The TTL and census role has SELECT on `login_audit` only. | `test_ear_store.py`: the audit role is refused SELECT on `utterances`. |
| Text in the ear service's logs | **PREVENTION by construction.** No print or log carries text, errors are named by exception TYPE only, and audio is decoded in memory and never written to disk. | `test_ear_service.py`: the real service on real whisper transcribes a known clip. The row carries its words, and the whole stdout+stderr (what journald receives) carries **0** of them. Red control: a sink that `print()`s the text is caught by the same grep. Postgres-side: `log_statement=none`, and a failing statement logs placeholders, not parameters (`log_parameter_max_length_on_error=0`), as measured. |
| Retention | **LOGICAL erasure at the TTL** by `DROP` of the day partition, never `DELETE`. The default TTL is 3 days (`EAR_TTL_DAYS`, floor 1). A partition is dropped once its START passes the TTL, so text is kept for at most TTL days. **Physical erasure is NOT claimed**: dropped tuples survive in recycled WAL until overwritten (M3). | `test_ear_store.py`: a partition planted 1 day past the TTL is RED and `maintain` DROPs it. A DEFAULT (unbounded) partition is RED. |
| Mic state is never hidden (d) | The header pill is always present for the owner. MUTED is enforced **server-side**, not only in the page. | `test_ear_service.py`: while MUTED the holder's upload → **423, 0 rows**. `tests/test_ear_lease.py`: MUTED has no TTL, can't be claimed, and only unmute ends it. |
| The page is never blocked (e) | Fail-open: the ear down → "ear offline". | `test_ear_service.py`: through the proxy with the ear down → 502 "ear offline". |
| Speaker attribution | Every S1 row says `speaker='unknown'`. There is no attribution at all, and it is never used for authority. | (row arm) |
| Only speech leaves the page | The browser's energy VAD; the server runs silero as a second filter. | `tests/test_ear_vad.py` runs the exact `vad.ts` under node: 5 s of room noise → **0 segments**, and the known clip → 1 segment. |

**Not claimable, stated:** physical erasure (M3). Anything a superuser resident does that deletes audit rows. Copiers assembled from strings at run time, relative paths against an unknown cwd, and a copy of `/` itself are outside the census's grade.

## Measured: the real-time factor (the GPU baseline)

Host: 4 cores, CPU only, shared with the residents. Backend `faster-whisper:small:cpu:int8` (`EAR_STT_BACKEND=cpu`), greedy decoding (beam 1), silero VAD filter on. Clip: 10.03 s of English speech (alsa-utils' test voices).

| run | load avg (1 min) | wall | RTF |
|---|---|---|---|
| best observed | 12.2 | 10.13 s | **1.01** |
| typical | 9–12 | 11–21 s | 1.1–2.1 |
| under heavy load (two whisper processes plus residents) | 13.7–18 | 27–37 s | 2.7–3.9 |
| beam 5, for comparison | 9.4 | 15.4 s (best) | 1.53 |

Model load is 3–10 s. **On this CPU the ear is never faster than real time.** Continuous speech outruns it, and the drop-oldest queue and the "degraded" indicator are what keep it current. The `cuda` backend (float16, beam 5) is one config line away when the GPUs arrive. Re-measure with `tests/test_ear_service.py`, which prints the numbers.

## Deploying S1 (owner)

1. `venv/bin/python -m nucleus.ear_store apply`. This creates `astryx_ear`, its roles and the trigger, and writes the role passwords to `~/.pgpass`.
2. `./init.sh` applies `schema.sql`, which adds `leases`, once this branch is committed on main.
3. Add `EAR_ENABLED=1` to `.env`, then run `./init.sh` again to generate `units/astryx-ear.service`.
4. Install the units (sudo, in the final report) and restart the observatory so it picks up the `/ear/` proxy. Rebuild the web with `nucleus/deploy.sh`.
5. Install the upkeep and census trigger: `printf 'from nucleus.shipped_triggers.ear_census import ear_retention, ear_census  # noqa: F401\n' > triggers/seed/ear_census.py`.
6. Verify the arms: `venv/bin/python -m nucleus.ear_store ttl`, `... readers`, `venv/bin/python -m nucleus.ear_census`.
