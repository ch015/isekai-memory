# Memory expansion work ledger

Design: [memory-expansion.md](memory-expansion.md).

Core baseline update: the initial M3–M6 Core checks below are historical. After
the user's latest-remote concern, Core was reconciled onto `3fb6480`; see
[Core latest-remote reconciliation](core-latest-reconciliation.md) for the
**333-pass current Core unit suite**, preserved state and remaining optional
fixture-coverage limitation.
The reconciled Core integration was subsequently committed as `f4dfa11` and
pushed to both Core remotes on `master`, excluding the pre-existing state DB.

| Unit | State | Deliverable / next action |
| --- | --- | --- |
| M0 | complete | Architecture, Tencent capability mapping, trust boundaries, acceptance criteria |
| M1 | complete | Source-backed experience schema, governance and lexical search/read; acceptance checks passed |
| M2 | complete | [Lifecycle contract](memory-lifecycle.md): revisions, suppression, validity, forgetting and cursor pagination; acceptance checks passed |
| M3 | complete | [Retrieval contract](memory-retrieval.md), evaluated lexical providers, citations and opt-in Core integration; vector/RRF remains deferred |
| M4 | complete (local baseline) | [Generation contract](memory-generation.md): durable offline extraction and approved-reference project/phase snapshots; remote semantic generation remains deferred |
| M5 | complete (local baseline) | [Native Skill contract](memory-skills.md): source-bound scaffolds, authored revisions, review and deterministic export accepted by existing Core verifier |
| M6 | complete (local baseline) | [Team asset contract](memory-team-assets.md): exact-version grants, pushed Wiki snapshots, quarantined native exchange and explicit outcome feedback |

## M1 implementation checklist

- [x] Additive migration and readiness check.
- [x] Proposal idempotency and source/classification inheritance.
- [x] Admin review queue and atomic, replayable lifecycle transitions.
- [x] Bounded project-scoped search and read of approved experiences.
- [x] MCP/REST catalog, dispatcher and authorization.
- [x] Unit/contract tests and PostgreSQL integration tests.
- [x] Updated usage documentation and validation results.

## M1 validation — 2026-09-10

- `ruff check src migrations tests` and `git diff --check`: passed.
- Full pytest suite with `MEMORY_TEST_DATABASE_URL`: **84 passed**, including nine
  PostgreSQL integration tests, on Python 3.14 and PostgreSQL 16. Existing
  pytest-asyncio/Python deprecation warnings remain; no tests were skipped.
- `python tests/run_local_e2e.py`: real HTTP and stdio entry points passed;
  14 tools, project/scope rejection, handoff round trip, and experience
  propose/review/search/read/archive.
- `python -m tests.migration_e2e_smoke`: populated `003 → 004 → 003 → 004`
  passed in a separate empty disposable database. Original handoff payload,
  status, claim digest and generation were unchanged.
- Python wheel build passed and included the new experience module.
- Docker image `isekai-memory:m1-verification`: build passed. The same real HTTP
  and stdio E2E runner also passed inside the Python 3.11 image, using the migrated
  temporary PostgreSQL database and read-only test scripts.

All DB validation used synthetic projects in a temporary PostgreSQL container.
No deployment or migration of a configured application database was performed.

## M2 implementation checklist

- [x] Immutable admin corrections, source/classification inheritance and family ancestry.
- [x] Atomic parent supersession/replacement approval and competing-edit fencing.
- [x] Rejection/supersession/forget fingerprints; explicit version-guarded release.
- [x] Validity windows, explicit plaintext erasure and independent source retention.
- [x] Keyset queue/history pagination with project/view-bound cursor validation.
- [x] Migration `005`, M1 backfill/receipt preservation and guarded downgrade.
- [x] Authorization, PostgreSQL integration, real transports and packaging checks.

## M2 validation — 2026-09-10

- `ruff check src migrations tests` and `git diff --check`: passed.
- Full pytest suite against a freshly migrated PostgreSQL 16 schema: **121 passed**,
  including 21 PostgreSQL integration cases; no skips. Without a configured test
  DB: 100 passed, 21 explicitly skipped. Existing deprecation warnings remain.
- Real HTTP and stdio E2E passed with 17 tools on local Python 3.14 and the
  Python 3.11 Docker image, including revision, suppression/release and forgetting.
- `tests.migration_e2e_smoke`: `003 → 005 → 003 → 005` preserved the original
  handoff payload and active claim.
- `tests.migration_lifecycle_e2e_smoke`: 502 populated M1 rows crossed the 500-row
  backfill boundary. All original columns and proposal/review receipts survived
  `004 → 005 → 004 → 005`; rejected claims were suppressed. Downgrade after
  correction/forgetting failed without changing rows or schema revision. Passed
  on Python 3.14 and inside the Python 3.11 image.
- Python wheel and Docker image `isekai-memory:m2-verification` built successfully.

All database changes were limited to synthetic data in the task's disposable
PostgreSQL container. No configured application database was migrated or deployed.

## M3 implementation checklist

- [x] Provider request/capability boundary, pre-top-K filters and authoritative hydration.
- [x] Retained default lexical ranking plus opt-in title/tag-weighted lexical provider.
- [x] Versioned Korean/English judgments, Recall@3/nDCG@3/MRR and local latency measurement.
- [x] Citation schema 1, full-content/excerpt/source binding and complete result budgets.
- [x] Separately opt-in Core recall before execution/Context preview; Context remains network-free.
- [x] Local scope/hash validation, reference-only content, optional section/citation trimming and offline fallback.
- [x] Real Core-client/Memory-server E2E and independent Memory/Core package builds.
- [x] Documented semantic misses; no unmeasured embedding/vector/RRF feature enabled.

## M3 validation — 2026-09-10

- Memory: **129 passed**, including 24 PostgreSQL integration cases, no skips
  with the explicit disposable database. Lint and whitespace checks passed.
- Core new recall tests: **28 passed**, including malformed responses, scope/hash
  mismatch, budget enforcement, no stale cache and actual worker execution with
  and without an available recall service. Changed Core modules passed lint and
  whitespace checks.
- Core full unit suite run before the final extra malformed-response case:
  **234 passed, 2 failed**. Both failures also reproduced unchanged in a clean
  temporary archive of pre-change commit `c0e0acedb104aa16b8d94beb950d187023e1acb2`:
  `test_activation_is_conversation_local_and_does_not_create_work` (uninitialized
  Project activation) and
  `test_kiro_adapter_uses_cached_subscription_without_forwarding_api_key`
  (workspace-isolation assertion). They were not modified as part of M3. The
  overall Core suite is therefore not claimed green.
- Actual Memory HTTP/stdio and Core MCP-client recall passed with both baseline
  and weighted lexical server configurations: citation validation, optional
  Context budget, cross-project rejection and retirement without cached reuse.
- `tests.retrieval_eval`: 26 rows, 22 queries, K=3, three repeats per provider.
  Recall@3 remained 0.850; nDCG@3 improved 0.777→0.850. Disallowed hits: zero;
  two no-answer queries correctly empty; three semantic queries still missed.
  [Raw results](retrieval-evaluation-v1.json) record dataset digest, ranks and
  local timing. These are synthetic agent-curated judgments, not production proof.
- Python 3.11 Docker HTTP/stdio and the same retrieval fixture passed; relevance
  results matched the local environment. Memory and Core wheels built; image
  `isekai-memory:m3-verification` built successfully.

No new database revision beyond `005` was needed. Core edits were limited to
integration config/schema, Memory client/recall/coordinator, execution/Context
wiring and associated tests/docs. The pre-existing Core `.isekai/state.db` change
was preserved. No actual Project enabled recall; no real database was migrated.

## M4 implementation checklist

- [x] Migration `006`: durable source receipts, lease/attempt fencing, backoff,
  dead letters and version-guarded redrive (three default, 30 lifetime attempts).
- [x] Missing-receipt source scans cover late/old sources without a timestamp gap;
  all extraction work remains independent of handoff claim/ack.
- [x] Finite, disabled-by-default worker CLI; offline structured extractor with
  pinned recipe/model/prompt versions, character/time limits and zero-cost budget.
- [x] Generated proposals share M1/M2 normalization and source/classification
  checks; proposal + completion receipt commit atomically, never auto-approve.
- [x] Exact duplicate suppression plus conservative source-level protection for
  rejected/forgotten claims and manual corrections, including paraphrases.
- [x] Project/phase approved-reference snapshots; ID/version/digest storage only,
  canonical read-time freshness checks, classification/Lock filters and budgets.
- [x] Four new authenticated tools (21 total), tests and operational documentation.

Scope choice: this M4 baseline deliberately quotes structured Result summaries and
projects already-approved references. It does **not** implement a remote LLM,
narrative synthesis, inferred scenario segmentation, a paid-provider budget ledger,
automatic scanning daemon or Core summary injection. Those require separate
provider/operational choices. No external generation is enabled.

## M4 validation — 2026-09-10

- `ruff check src migrations tests` and `git diff --check`: passed.
- Full PostgreSQL 16 suite: **170 passed**, including **49 DB integration cases**,
  no skips. M4 adds 16 unit and 25 DB cases. Without a configured DB: 121 passed,
  49 explicitly skipped. Existing deprecation warnings remain.
- Covered connection/process-boundary recovery, expired/stale leases (including
  expiry after proposal insertion), retry limits/redrive replay, partial-write
  rollback, input/output/time budgets, conservative correction/suppression gates,
  late source coverage and 50-source manifest truncation.
- Actual HTTP + stdio + separate worker CLI passed locally and in the Python 3.11
  image `isekai-memory:m4-verification`: pending extraction, explicit approval,
  fresh summary read, forgetting invalidation and an empty replay batch.
- Existing actual Core MCP recall E2E also passed: citations, Context budget,
  cross-project denial and retirement without cached reuse. No M4 Core edits were
  needed; the unrelated full-Core-suite limitations recorded under M3 remain.
- Populated `005 → 006 → 005 → 006` preserved the existing claimed handoff and
  approved experience byte-for-byte. Once M4 jobs/snapshots existed, downgrade
  refused transactionally and all job/attempt/snapshot rows remained unchanged.
- Legacy populated `003 → 006 → 003 → 006` preservation and 502-row M1 backfill /
  M2 rollback-refusal tests passed in separate disposable databases.
- Python wheel build during Docker packaging and production Python 3.11 image
  build passed; the installed generation module/CLI ran successfully.

All database work used synthetic projects in a temporary PostgreSQL container.
No real deployment database was migrated, no project configuration was enabled,
and no Core files were changed by M4.

## M5 implementation checklist

- [x] Migration `007`: project-local Skill identities, immutable revisions/source
  bindings, one-active-revision constraint, review events and safe rollback guard.
- [x] Bind 1–8 exact approved experience versions from reported successful work
  with evidence references, including at least one procedure and exactly one Lock.
- [x] M4 offline worker generates source-linked scaffolds only; manual authorship
  and a separate admin approval are required before activation/export.
- [x] Strict trigger/step/validation/resource schema, latest-revision CAS, captured
  active-revision fencing, durable proposal and actor-bound review receipts.
- [x] Monotonic classification floor and fresh-source validation on approval,
  reads and exports; no Skill instructions enter normal experience search.
- [x] Transactional source retirement invalidation and cross-revision body/resource
  erasure when a source experience is forgotten, including retired revisions.
- [x] Explicit bounded deterministic unsigned native Skill export with fixed safe
  paths, non-executable members, separate digests and no capability grant.
- [x] Eight new authenticated tools (29 total), Core artifact-verifier acceptance,
  real transports/worker, migration preservation and operational documentation.

Scope choice: native ISEKAI `kind: skill`, not a Codex `SKILL.md`. Automatic
generation is an offline scaffold, not semantic procedure synthesis or a claim of
successful Skill reuse. Source prose remains evidence, not automatically promoted
instruction. Export is structurally verified but unsigned and uninstalled; Git
release provenance, signatures, execution policy, installation, automatic Core
consumption and external-model generation remain separate explicit workflows.

## M5 validation — 2026-09-10

- `ruff check src migrations tests` and `git diff --check`: passed.
- Full PostgreSQL 16 suite: **209 passed**, including **70 DB integration cases**,
  no skips. M5 adds 18 unit and 21 DB cases. Without a configured DB: 139 passed,
  70 explicitly skipped. Existing deprecation warnings remain.
- Covered concurrent proposal/revision/approval, generated-scaffold approval
  rejection, manual-authoring gate, same-project/Lock binding, classification floor,
  source drift/expiry and source forgetting across superseded/active revisions.
- Covered job partial-write rollback, stale leases, pinned/current budgets,
  immutable DB body/source records, metadata pagination and deterministic safe
  exports. Hostile source prose stayed out of generated/exported instructions.
- Actual HTTP and stdio (29 tools), separate M4/M5 worker CLI, reviewed export and
  source-forgetting propagation passed locally and in Python 3.11 image
  `isekai-memory:m5-verification`. Wheel build during image packaging passed.
- The unchanged Core `ArtifactArchive` and `ArtifactVerifier` accepted a real
  exported native Skill and rejected modified instruction bytes. No Skill was
  installed. Existing Core-client recall E2E also passed. No M5 Core edits were
  needed; the unrelated full-Core-suite limitations recorded under M3 remain.
- Populated `006 → 007 → 006 → 007` preserved existing handoff, experience,
  generation job/attempt and summary data. Downgrade after Skill history existed
  refused atomically, preserving all Skill/job/binding/event data.
- Separate legacy migration scripts passed: claimed handoff preservation from
  `003`, 502-row M1 backfill and M2 rollback guard from `004`, and populated M4
  receipt preservation/rollback guard from `005`, all through current head `007`.

All DB work used synthetic data in the M5 disposable PostgreSQL container. No
deployment DB was migrated, no existing project opted in, and no Core files were
changed by M5. The prior dirty worktrees and Core state database were preserved.

## M6 implementation checklist

- [x] Additive schema `008`: explicit owner/consumer grants, current pushed Wiki
  snapshots and immutable events, import quarantine/erasure and feedback receipts.
- [x] Exact-version/digest sharing for approved experiences, reviewed Skills and
  live knowledge; classification/source/Lock filtering and non-transitive access.
- [x] Permanent version-fenced revocation, actor-bound replay, owner-lock read
  revalidation and no server cache; HTTP tool responses use `no-store`.
- [x] One no-network pushed Wiki adapter: normalized digest, explicit source
  revision, CAS, bounded publisher-reported validity, class floor and prose erasure.
- [x] Bounded M5 native import: safe canonical tar, independently checked transport,
  manifest and artifact digests, strict JSON/source claims and compression portability.
- [x] Quarantine only, admin inventory/inspection, claimed-identity conflict
  handling and explicit erasure; no imported source becomes local approval evidence.
- [x] One explicit immutable actor/asset-version observation, same-project
  reported outcome evidence and no implicit counts/ranking/lifecycle effects.
- [x] Fourteen authenticated tools (43 total), real transports and Core
  compatibility, source drift/expiry, adversarial archives and migration preservation.

Scope choice: this is a local team-asset baseline, not a remote Wiki/code-graph
connector, Git transport, signature authority or automatic Skill adoption. An
operator can exchange native archives through their existing reviewed Git
workflow; Memory validates/imports them without cloning, fetching, committing,
pushing or installing. Upstream Wiki freshness is explicitly publisher-reported.
Shared reads and imported copies have different retention semantics: revoking a
grant prevents future authorized reads, but cannot erase copies already delivered.
Feedback binds a reported observation, not independent proof of causal success.

## M6 validation — 2026-09-10

- `ruff check src migrations tests`, compilation and `git diff --check`: passed.
- Full suite on a newly migrated PostgreSQL 16 database: **265 passed**, including
  **87 DB integration cases**, no skips. M6 adds 39 unit and 17 DB cases. Existing
  deprecation warnings remain. Without DB, the final run passed 178 unit cases
  and explicitly skipped 87 DB cases.
- Covered denied default/cross-project/transitive access, exact grant/source
  versions, source retirement/drift/expiry, same-actor receipt replay, concurrent
  submission and read-after-revocation locking without cached content reuse.
- Covered Wiki class floors, deletion/republication, bounded expiry, digest
  mismatch, partial-write rollback and scope-bound metadata pagination.
- Covered actual M5 export → quarantine → inspect/forget, changed identity-content
  conflicts, compression bombs, malicious tar paths/types/modes/duplicates,
  tampered instructions/digests, duplicate JSON, invalid source claims and immutable
  DB receipts. Gzip encoding is separate from canonical native artifact identity.
- Covered feedback actor spoofing, duplicate-key ballot stuffing, pending/foreign
  assets, mismatched/foreign outcome evidence, grant revocation, immutable records
  and absence of approval/ranking/owner-disclosure side effects.
- Actual HTTP and stdio (43 tools), separate M4/M5 worker CLI, M6 two-project
  grants/feedback/deletion and native quarantine passed locally and inside the
  final Python 3.11 image `isekai-memory:m6-verification`. Wheel/image build passed.
  A Python 3.14-produced native archive was also accepted by the Python 3.11 importer.
- Unchanged Core MCP recall and native archive verifier passed against the real
  server; tampered Skill bytes were rejected and no installation occurred.
  No M6 Core edits were needed. The unrelated full-Core-suite failures recorded
  under M3 remain outside this result; the full Core suite is not claimed green.
- Populated `007 → 008 → 007 → 008` preserved claimed handoff, experience and
  Skill/binding/event data. Even after revocation/deletion/import erasure, M6
  history caused atomic downgrade refusal. Passed locally and in Python 3.11.
- Independent legacy migration scripts passed through head `008`: claimed
  handoff preservation from `003`, 502-row M1 backfill and M2 rollback refusal
  from `004`, M4 receipt preservation from `005` and M5 Skill history from `006`.

All database work used synthetic data in the task's disposable PostgreSQL
container. No deployment DB was migrated, no existing project opted in, no
external service or Git repository was connected, and no Core files were edited.
Existing dirty worktrees and the Core state database were preserved.

## Follow-up choices (not enabled or implied by M0–M6)

1. Select actual Wiki/code providers, credential ownership, collection allowlists,
   upstream change/deletion feeds and operational freshness limits.
2. Select a reviewed Git/release transport, signature trust policy and destination
   retention process before automating asset exchange or adoption.
3. Evaluate any shared search, feedback-driven ranking, semantic generation or
   automatic Core consumption against explicit scope and quality datasets.
4. Plan deployment/backups/retention and an explicitly approved migration of an
   actual application database. This implementation did not perform a rollout.
