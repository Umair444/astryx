# sqlguard: the ctx.sql-blindness meta-guard (goal 4243)

Converged design: plan-4243 thread. Consolidated in #21519, then corrected by #21522 (run scope), #21525
(rc=0 for negatives), #21888 (the (P) filter and schema credit), #21938 (DML credit and conservative WRITE),
#22110 (whole-file applier), #22112 (relation-grain signature stamp) and #22115 (isolation by database).
Quorum 4/4, 2026-09-29. Builder: abstractor-4. Reviewer: abstractor-3.

## The class
A SQL site that no oracle OBSERVES against a real schema. There are four instances: weekly_econ ARM 6
(6d9221d), market_decay (f26b5ec), the S0 demand tautology (#21324, a projected `dq`), and shed() via a FakeConn.

## One status type
`UNEXECUTED → EXECUTED → RESPONSIVE → (CORRECT = the mutant battery, outside this guard)`.
`NOT SEARCHED` is orthogonal (this run's evidence is missing). It is never a rung and never a pass.
Every answer names the rung it certifies AND the rung above it that it does not.

## Site identity: one attribution rule
Walk a traced statement's repo frames from the innermost outward. The SITE is the first frame whose function's
inventoried literal set CONTAINS the executed normalised text, keyed `(relpath::qualname, normtext)`.
- Helpers such as `pulse_run.Ctx.sql` are skipped naturally, because they hold no literal.
- An identical text in another function gets no credit.
- If nothing matches but a frame's function holds an unresolved site, attribute at FUNCTION level, flagged
  FALLBACK.
- If no SQL-bearing function is on the stack at all → reverse agreement goes RED (the inventory is blind).

## Witnesses
- (W) per site: the result or affected-row count took BOTH 0 and ≥1. N/A without WHERE/HAVING/JOIN…ON.
  NOT-EVALUATED for an aggregate without GROUP BY.
- (P) per site: every column with `ftable(i)=0 AND type OID 16` (computed bool) took two values.
  - Non-bool computed columns are NOT-EVALUATED (declared).
  - asyncpg has no table OID, so (P) is NOT-EVALUATED there.
- RESPONSIVE = (W) ok or N/A, AND every graded (P) column took two values.

## Credit (positive evidence)
- READ site: the live DB's `public` schema, OR a fixture relation carrying a valid stamp.
- WRITE site (a DML token anywhere, word-bounded): live-public evidence counts toward EXECUTED only.
  RESPONSIVE needs stamped fixture relations.
- Stamp: the fixture DB is built by applying `schema.sql` WHOLE (one writer). Every relation gets
  `COMMENT ON TABLE … 'astryx-ddl:<file_sha>:<sig_sha>'`, where sig = sha256 of the sorted
  (attname, format_type, default expr, attnotnull). It's valid only if file_sha == sha of the CURRENT
  schema.sql AND sig recomputes equal at credit time.
- Every catalog cache is keyed by `(dbname, oid)` (M1).
- An unstamped relation → FIXTURE-DDL: EXECUTED at most, never RESPONSIVE.
- The schema is captured at connect and RE-READ after any statement that touches search_path.

## Run scope: per site, asymmetric
- POSITIVE evidence counts from any traced success, whatever the gate's rc.
- NEGATIVE verdicts (UNEXECUTED, NOT-RESPONSIVE) are judged only when EVERY covering gate of the site
  exited rc=0. Otherwise that site is NOT SEARCHED, with a per-site clock (N runs / T days → RED).
- Run-level NOT SEARCHED applies only for shim internal errors, a canary failure, or a missing/corrupt
  covering map.
- The covering map is DERIVED from the last clean run and stored beside the ledger.

## Isolation
- A fixture = `astryx_fx_<run_id>_<n>`, a throwaway DATABASE per oracle (BC-a), dropped WITH (FORCE) in
  `finally`. That contains NOTIFY and keeps the file's unqualified DROP VIEWs away from production.
- check.sh exports the run id ITSELF (BC-b). A standalone oracle self-ids.
- The leak arm: this run's prefix must be gone. A foreign `astryx_fx_*` is tracked by first-seen state
  (pg_database records no creation time).

## Ledger
- Generated and shrink-only, keyed by site. Each row carries its debt rung.
- RED on a NEW site below RESPONSIVE. RED on a listed row whose site has since climbed.
- Growth only via `--admit <site> <reason>`. DETECTION-grade against a same-uid actor.

## Acceptance checklist (a3's #22135 + the verdict-row build conditions)
1. One applier. The per-test extractors are LISTED and counted until migrated (#22137 proposal; the two econ
   copies wait for 4227).
2. A stale stamp is capped.
3. Signature RED-controls: DROP+re-CREATE; ALTER … DROP DEFAULT; an OID collision between fixture and live.
4. The DDL-agreement arm compares fixture signatures against live public. Drift is reported as a schema.sql
   finding.
5. Zero NOTIFY in the live DB during a fixture's lifetime (the LISTEN connection is opened BEFORE the fixture
   DB is created, a1).
6. One DB per oracle.
7. check.sh exports the run id; the canary and the shim prove themselves under `env -i`.
8. Report the measured apply time. A template DB, if used, is named by the schema.sql sha.
9. (P) is exactly ftable=0 AND OID 16. The #3 RED-control and the computed-data GREEN-control run through the
   REAL pulse_run.Ctx.sql.
10. RED-first evidence for every control (run it against the tree without the patch).
Extractor list (a3 #22138):
- EX1: the extractor set is derived by CONTENT. Any .py file whose CODE holds a string constant naming
  schema.sql (docstrings excluded) counts, except the applier (and init.sh, which is shell). It must EQUAL the
  printed migration list: a new reader → RED; a listed file that no longer reads → RED.
- EX2: every listed row carries an observable TRIP in its reason ("migrate when plan-4227 S2 lands") plus a
  days-listed clock; more than T days → RED, naming the file.
- EX3: a site capped at FIXTURE-DDL SOLELY because its covering oracle is a LISTED extractor is REPORTED, not
  RED-on-new, until that row's trip or clock fires. Any other reason for being below RESPONSIVE stays RED-on-new.
  - RED-control: an oracle that's an unlisted schema.sql reader → RED.
  - GREEN-control: a listed one inside its window → reported.
Plus:
- C1: negatives only at rc=0.
- a2: hash production rows before and after a full check.sh; they must be unchanged.
- The two real scars: weekly_econ and market_decay read ≥EXECUTED under their real oracles, and UNEXECUTED under
  the helper-only shape.

## Build stages
- B0 report-only: normalise, inventory, shim, fixture, judge, check.sh wiring.
- B1: the RED rules + all controls in one act.
- B2: the EXPLAIN floor for debt sites.
