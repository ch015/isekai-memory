# M4: durable generation and approved-reference summaries

M4 adds an **offline, opt-in execution path**, not an LLM integration. Tencent's
bounded extraction batches, source attribution, shared write path and protected
manual corrections are adapted to Memory's PostgreSQL/lifecycle contracts. No
Tencent source or prompts are copied. The baseline quotes structured work results;
semantic distillation, inferred scenario segmentation and remote models remain
future provider work, not claimed capabilities.

## Workflow and boundaries

1. An admin calls `memory_generation_enqueue` with `kind: extract`. Each bounded
   scan adds up to `limit` (default 20, max 100) previously unseen project handoffs.
   Repeat while `has_more` is true. No work executes in this request.
2. An operator explicitly enables `generation.enabled` and runs the finite worker:

   ```bash
   ISEKAI_MEMORY_GENERATION_ENABLED=true isekai-memory \
     --run-generation --project-id my-project --max-jobs 20
   ```

   It processes only that project's queued/due work, then exits. Use an operator
   scheduler to repeat scans and worker invocations; no daemon, default hook,
   traffic recorder, network call or background task starts with the MCP server.
3. Generated experiences are always `pending`. Review them with existing
   `memory_experience_list/review`; only an admin's approval exposes them to M3.
4. Enqueue `kind: summary` for a project, optionally `phase_id` (the existing
   workflow phase, not an inferred semantic scene), `max_classification` and
   `source_lock_digest`. Run the worker, then use `memory_summary_read` with the
   same scope. Reads never enqueue work or call a generation provider.

Extraction scans the entire token-authorized project. Summary-only scope options
on extraction, and extraction `limit` on summaries, are rejected. Token project
authorization is mandatory; classification is an output filter, not token clearance.
No M4 Core changes or automatic summary injection are enabled.

## Durable source coverage, leases and retries

Migration `006` adds jobs, attempt receipts and summary manifests. It does not
alter existing handoff payloads, claims or experience rows. Job identity is
`(project, kind, source_key, source_watermark, recipe)`; extraction uses the retained
handoff ID and complete payload digest. A metadata binding separately checks
envelope digest, Lock, classification and phase. Summary watermarks bind the scope,
visible count and ordered bounded source manifest.

Scanning uses a missing-receipt anti-join, **not a timestamp high-water cursor**.
This covers late-committing sources whose timestamp precedes a previous scan.
Queued, running, completed and dead receipts all count as scheduled coverage;
coverage does not mean successful extraction. Delivery pending/claimed/acknowledged
states and handoff expiry do not change the retained source's extraction identity.
Handoff claim/ack is never called. Deleting a queued source results in a dead letter;
jobs deliberately do not retain the source through a foreign key.

Writes acquire the existing experience project advisory lock before row locks.
Claims atomically reserve an attempt and random lease token. Completion and failure
require the same attempt/token and an unexpired DB-time lease. Completion checks
again after potentially blocking writes; proposal and job receipt commit in **one
transaction**, or both roll back. Provider work holds neither a transaction nor a
handoff lease. Process loss leaves a recoverable lease; the next worker can reclaim
it after expiry. Old workers cannot commit or fail a newer attempt.

Default three attempts, exponential due-time backoff (2, 4, … capped at 300 seconds),
then `dead`. Expired final leases also become dead letters; each claim pass drains
at most 100 exhausted jobs. `memory_generation_list` is an admin-only keyset view
of queued/running/succeeded/dead jobs and recipe/source provenance, without lease
tokens or provider text. Attempt rows retain timestamps, safe outcome codes,
character usage and zero cost. They are inspectable in the operator's DB; there is
no public raw trace/log endpoint.

`memory_generation_retry` requires the dead job's `job_id` and `expected_version`.
It adds three allowed attempts, with a hard lifetime cap of 30. Same-actor replay
of the most recent redrive returns its receipt; stale/different-actor requests do
not reset newer work. Source-change failures need a new enqueue for the current
watermark, not repeated execution of an obsolete recipe/input. Successful and
protected/duplicate/empty jobs are not redriven. Retain receipts for deduplication.

## Extraction, governance and budgets

Only provider `local_structured`, model/algorithm `extractive-v1`, prompt/recipe
`result-summary-v1` is supported. The provider interface is internal, not a remote
endpoint or public provider selector. It reads `ResultEnvelope.summary` and at most
201 objective characters, emits one `fact` with a 200-character title, and preserves
the normalized result summary as reported evidence. It does not turn failures into
success, infer reusable procedures or independently establish the claim's truth.
Empty summaries produce a successful `empty` receipt. Obvious credential markers
produce `sensitive_source`; this is a conservative heuristic, **not comprehensive
secret detection**. Admin review/classification remain necessary.

No raw output/full transcript is loaded into the provider or duplicated in job
parameters, snapshots, receipts or logs. Input/output limits are pinned at enqueue
and can only be tightened by current worker settings. Defaults:

| Setting | Default / supported range |
| --- | --- |
| `generation.enabled` | false |
| `generation.max_input_chars` | 8192 / 256–16384 |
| `generation.max_output_chars` | 4296 / 256–4296, title + content |
| `generation.timeout_seconds` | 10 / 1–30 |
| `generation.lease_seconds` | 60 / 10–300; must exceed timeout by >5 seconds |
| CLI `--max-jobs` | 20 / 1–100 |
| Per-attempt monetary budget and cost | 0 micro-USD; no paid provider supported |

The worker timeout covers source load, provider execution and completion. Individual
summary reads have a 2.5-second total / 2-second SQL budget. Database failure
recovery/lease cleanup is separate from provider execution time. Providers must
cooperate with asyncio cancellation; a future blocking or paid provider requires
new isolation, durable monetary reservation/accounting and transport tests.

Generation calls the same normalization, source/classification inheritance and
suppression-aware proposal path as manual submissions. Its actor is
`generation:<job-id>`; the job separately records the authenticated enqueue actor.
The job outcome records the resulting experience ID. No producer-controlled actor,
status, source classification or approval is accepted.

In addition to M2's exact fingerprint suppression, automatic extraction is blocked
for **any unreleased suppression or any manual correction on the same payload**.
This conservatively protects paraphrases and human corrections. Same-source
normalized kind/body duplicates in any lifecycle state are not reproposed. Automatic
generation never overwrites a correction. Releasing an M2 fingerprint is not an
automatic regenerate command; use explicit manual proposals when justified.
This baseline does not promise semantic deduplication across unrelated sources.

## Snapshot freshness and forgetting

A summary is a deterministic **projection of already-approved references**, not
newly synthesized knowledge needing a second approval. It stores only scope,
visible count, source IDs/versions/citation digests and timestamps; no prose copies.
At most 50 eligible experiences (newest updated first) form a manifest. The response
reports total eligible source count, returned count and truncation; it is not a
claim of comprehensive project understanding.

Read-time canonical hydration applies project, active state, validity interval,
classification, optional phase/Lock and retained source digest/metadata matching
before ordering or limits. It then compares the current manifest watermark with a
stored snapshot in a repeatable-read transaction. Correction, forgetting, archive,
source drift, expiry, eligibility changes or new approvals that change this bounded
view invalidate it. Changes solely to omitted sources do not rewrite the 50-source
projection unless its count/order/selection changes. Consistency is at the DB read
snapshot, not a promise that another transaction cannot retire a source immediately
afterward.

`memory_summary_read` returns `ready`, `missing`, or `stale`. Missing/stale returns
no text and never falls back to cached old prose. Ready returns M3-compatible
citations and `usage: reference_only`, with the serialized `items` budget bounded
by `max_chars` (default 8000, 1000–16000); complete citations are never cut. Too-small
budgets can return zero items with `truncated: true`. There is no persistent
plaintext copy to resurrect after forgetting. Original handoffs, backups and prior
exports remain under their independent retention policies.

## Migration and validation

M4 introduced revision `006`; the current server also requires M5's `007` (run
`alembic upgrade head`). Downgrade from `006` to `005` is allowed only
when **no generation job receipts exist**; otherwise the entire downgrade fails
transactionally. This avoids silently discarding work, source coverage and audit
history. An operator must explicitly plan any export/retention change first.

Tests: `test_generation.py`, `test_generation_postgres.py`, the real HTTP + worker
CLI `generation_e2e_smoke.py` (included in `run_local_e2e.py`), and populated
`migration_generation_e2e_smoke.py`. All database checks require an explicitly
selected disposable PostgreSQL database; migration smoke scripts require an empty
schema. See the [work ledger](memory-expansion-progress.md) for measured results.
