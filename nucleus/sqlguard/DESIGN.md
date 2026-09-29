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

## Stated property (a3 D-C)
The shim's side work is BOUNDED and can never block or abort the gate under test. Its observer runs on a
separate connection with lock_timeout 250ms and statement_timeout 2s, and a timeout or error means NO CREDIT.
A caller whose open transaction blocked the observer is memoised as "no credit" until the transaction ends (a
client-side status read). It never runs a statement on the caller's connection.
Controls:
- an uncommitted ALTER in the caller's transaction completes in <5s, with the post-ALTER SELECT stamped=False;
- 50 statements in that transaction take <2s;
- the fixture DB is gone afterwards.

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
B0 review (a3 #22252), for B1:
- D-A: stamp validity is recomputed per statement, NO cache (an ALTER keeps the OID). RED-control: SELECT, ALTER
  … DROP DEFAULT, then the same SELECT → the second record is stamped=False.
- D-B: DML without RETURNING and computed-only SELECTs fall back to "EVERY relation in the fixture DB is stamp-valid
  NOW". GREEN: an UPDATE at 1 row and at 0 rows in a stamped fixture → RESPONSIVE. RED: after a hand CREATE
  TABLE → not credited.
- F-a: untraced children → NOT SEARCHED, cause named, on the per-site clock. The opt-in is ONE helper in
  nucleus/sqlguard/, never a per-test copy.
- F-b: the extractor list is derived at RUNTIME ("builds an unstamped fixture"). A listed extractor drops off
  ONLY when its gate completed rc=0 without building one, so a skip never silently "migrates" it. EX2/EX3 unchanged.
- C3: the seed run is a clean worktree with the estate COPIED in. Record sha + count + an ESTATE MANIFEST HASH
  beside the seed stamp.
Plus:
- C1: negatives only at rc=0.
- a2: hash production rows before and after a full check.sh; they must be unchanged.
- The two real scars: weekly_econ and market_decay read ≥EXECUTED under their real oracles, and UNEXECUTED under
  the helper-only shape.

## Build stages
- B0 report-only: normalise, inventory, shim, fixture, judge, check.sh wiring.
- B1: the RED rules + all controls in one act.
- B2: the EXPLAIN floor for debt sites.

## B1 as built (abstractor-4, for a3's review)
- check.sh runs `enforce` as a real gate, last (rc 0 / 1 / 77). The judge is report-only when run alone.
- tests/test_sqlguard.py builds a TEMP REPO (package copy + subjects + drivers, `ASTRYX_SQLGUARD_ROOT`) and
  runs every control above for real: shim → judge → enforce, state in a fixture DB, never the live table.
  - `--against <rev>` runs today's arms against an older package (RED-first).
  - `--mutants [name]` breaks one property per mutant in the copy; each must be killed by the arm it NAMES.
- The ledger's covering map (the last clean run, digest-keyed) is UNIONED into the judge's, so a gate that
  crashed before reaching a site still covers it (NOT SEARCHED, never a false UNEXECUTED).
- `ledger admit <trace_dir> <handle> '<reason>'` is the only growth path; R-NEW prints the handle, and every
  admitted row's reason prints on every run.
- Extractor derivation matches CREATE TABLE ANYWHERE in a statement (a batch that leads with a comment or a
  DROP was invisible), which also makes the applier exclusion load-bearing by structure.
- test_reachability learned the dotted edges (`-m`, dotted imports, package `__init__`, PYTHONPATH →
  sitecustomize), each with GREEN and RED fixtures. nucleus/__init__.py's hand exemption is now derived.
- test_market_decay_sql_surface uses fixture_db(), so its extractor row shrinks.
- The unanchored derivation found two more extractors, both now listed with trip goal 4243: test_funded_by
  (applies schema.sql whole to an unstamped throwaway) and test_memgraph (memgraph.write_pg runs its kg DDL
  against the LIVE DB, so the oracle also rewrites live kg on every run; byte-identical to the nightly
  compile from the same memory/, but it is a prod write from a test).
- An exemption goes stale only when a TRACKED surface reaches its file. An edge found only in the gitignored
  estate keeps it, because the entry exists for the host without that estate (pr_review.py, hit on the
  first live run of the dotted-import parser).
Residuals (declared, not closed):
- M1: an OID collision can't be FORCED (the OID counter is cluster-wide). The arm proves that no credit
  carries from one fixture DB to a hand relation in another, and there is no cache to collide in.
- The stored covering map is written only at seed/admit. A RENAMED check.sh gate label is absent from
  gates.tsv and reads as rc 0 (complete). That's the loud direction (a negative verdict → R-NEW or listed
  debt, never a false RESPONSIVE), but the map has no refresh verb yet.
- enforce's own SQL runs AFTER its judge, and each check.sh run has a fresh trace dir, so enforce.py's sites
  can never climb in-check. They stay listed debt. Re-judging a finished trace dir sees them (a false
  R-STALE, from re-judging only).
- (a3 #22780, closed) A function rename used to reset an untraced site's NOT-SEARCHED clock, and `shrink` deleted
  the moved rows. Now the clock and every row carry text_key (path + normalized SQL, no qualname), and `shrink`
  re-keys a vanished row when exactly one UNLISTED live site shares its text. A changed statement is a new site,
  so its clock legitimately restarts (e87eac9's nudge dedup: `'nudge:%%'` became a parameter). Deploying the
  text_key clock restarts every NOT-SEARCHED clock ONCE (the live table dates from 09-29).
- asyncpg is credited through the D-B DB-grain stamp (forge #23806). The shim used to hard-code
  stamped=None for asyncpg, which capped every asyncpg site at FIXTURE-DDL. Only (P) stays NOT-EVALUATED on
  asyncpg, because its Attribute has no table OID.
- Driver-internal SQL (drivers.py) is decided by TEXT provenance, not frames. Frames can't separate repo
  `conn.execute(q)` from `pool.release()`: both reach the wrapped method from inside the driver. The order is:
  1. a repo literal owns the text;
  2. an unresolved repo site is on the stack (FALLBACK);
  3. EVERY ;-statement is a constant in the driver's installed source, AST-derived per version → counted,
     printed as name@version, and given no credit;
  4. otherwise it's R-BLIND.
  The first rule I ruled (immediate caller inside the driver) would have swallowed nearly all repo SQL; see
  #23984. Declared residual: a repo caller the inventory doesn't see as SQL-bearing whose runtime text equals a
  driver constant also reads driver-internal, so the count is not proof that only the driver spoke.
- fixture_db() yields `url` (postgresql://) beside the key=value `dsn`, for asyncpg and node-pg.
