# Memory expansion work ledger

Design: [memory-expansion.md](memory-expansion.md).

Core baseline update: the initial M3–M6 Core checks below are historical. After
the user's latest-remote concern, Core was reconciled onto `3fb6480`; see
[Core latest-remote reconciliation](core-latest-reconciliation.md) for the
**333-pass historical Core unit suite**, preserved state and remaining optional
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
| M7 | complete (local baseline) | [Collaboration contract](memory-collaboration.md): multi-user delivery inbox/status and fenced lease renewal; automatic delivery and Core continuation remain follow-up work |
| M8 | complete (local implementation and validation) | [Project continuity](memory-project-continuity.md): admin-managed 1:N policy, independent deliveries, fenced work/reassignment, stored checkpoints and opt-in Core capture/local-MCP preparation. Deployment and project activation remain explicit; no automatic execution |
| M9 | complete (local implementation and synthetic validation) | [Acceptance](memory-m9-acceptance.md): user/admin TUI, controller/worker observation, token monitoring, user work/lease and durable events; no deployment or real subscription execution |
| M10 | planned | Broader team/membership operations and operational automation; external connectors deferred |

## M9 final acceptance — 2026-09-14

Current schema: 013. Catalog: 82 tools. The user/admin console, 1:N recovery,
controller/worker observation, token monitoring, experience review, user work
sessions and independent lease keeper, and durable cursor recovery are implemented.
The final results and explicit exclusions are in [M9 acceptance](memory-m9-acceptance.md).
Token monitoring is frozen at the user's requested scope; no cost, billing or budget
feature is being added. All sections below are historical intermediate results.

## Historical M9 runtime progress — 2026-09-14

### Current usage ledger/reporter/TUI slice

[Usage runtime contract](memory-usage-runtime.md) supersedes the earlier pure
metrics-only milestone below. Schema 012 and 80 tools now provide independent
opt-in collection/retention/alerts, actor-owned exclusive runs, immutable exact
receipts, full-set scoped period/group totals, bounded rate/retention handling,
Codex 0.154.0 numeric parsing, Core runtime reporting and a bounded owner-only
outbox. TUI f edits filters; j edits usage policy with exact pending-request retry.
Unknown/unsupported/initial context estimates are never reported as zero consumption.

Validated: Memory 633 full tests then 12 usage DB tests including additional active
claim proof, late reporting after takeover, source erasure and rate-limit rollback;
Core 703 full passes/1 sandbox skip, then 59 focused parser/reporter/read/boundary
passes including the real execution path with a fake worker. HTTP/stdio/TUI 80-tool
smokes and parser→outbox→HTTP reply-loss recovery passed (own 60/project 180).
Populated M8/presence preservation and 012 downgrade refusal also passed.
These are synthetic/local checks, not real subscription or deployment validation.
M9 remains open for controller/user actions, experience review and durable events.

The following sections are historical intermediate milestones.

### M9-4 administrator policy and continuity action slice

Core --manage now supports all ten M8 policy fields including sender-specific
1:N/default/backups, separate presence policy, checkpoint recovery publication,
explicit work assignments/reassignment, bounded admin audit and ID-confirmed
checkpoint body erasure. These are server operations, never local restoration,
recipient impersonation, automatic execution or process termination.

Requests pin policy/bundle versions and every work generation. Emergency takeover
requires enabled policy, explicit affected keys and the running-process warning.
All large-preview pages must be visited before final confirmation. Eligible users
are paged in groups of 50; full policy size is bounded at 2 MiB per call.

A credential snapshot binds each preflight and write. One owner-only pending
request per connection/actor is written durably before sending, with nonblocking
cross-process locking through the result write, no automatic retries, seven-day
retry retention and stale-preview digest fencing. Server success and failure to
store a local receipt remain distinct. Successful/discarded requests are scrubbed.

- Focused Core policy/action/console/pending and boundary suite: **120 passed**.
- Actual HTTP/stdio synthetic suite passed with **73 tools**, including prior
  read-only and policy TUI tests plus two-recipient recovery, lost publish reply
  exact retry, emergency reassignment after an actual work claim, audit and
  erasure revoking dependent deliveries/claims (generations 1 → 2 → 3).
- Production data, migrations and login are unchanged. No subscription CLI,
  real project activation, deployment, commit or push. Tests erased only their
  newly created synthetic checkpoint body. Previous full-suite/wheel counts
  below are historical; final regression/packaging for this slice is separate.

M9 and M9-4 are not complete: experience review, token ledger/policies, actual
controller lifecycle, local user intake/lease actions and durable events remain.

Final administrator-slice verification (including clearing open forms after an
admin-role downgrade or credential failure):

- Core full unit suite: **648 passed, 1 sandbox process-table skip**. That same
  process-tree cleanup scenario passed separately with approved process access:
  **649 scenarios covered**, not one no-skip full-suite run.
- Final Core wheel installed into the temporary Python **3.11.16** console
  environment passed **120 console/admin/pending tests**, using installed code
  rather than editable source. Base packaging/import was also checked without
  Textual/Rich. The console dependency remains optional, pinned at Textual 8.2.8.
- Actual HTTP/stdio and all existing/new synthetic Core TUI scripts passed again
  after the final role fence. Ruff and git diff --check passed; the user's staged
  Core state DB has no new unstaged changes. No code was committed or pushed.

The read-only milestone below predates the administrator forms above.

### M9-2b pure normalized token metrics — first slice

The no-I/O usage_metrics module now distinguishes reported/estimated/unavailable
per field, validates totals and cache/reasoning subsets, preserves unknown versus
zero, rejects counter resets/downgrades in an epoch, and aggregates bounded
latest non-overlapping snapshots with quality-specific partial coverage.
**29 pure tests passed; Memory full PostgreSQL regression: 593 passed, no skips**
(2,008 dependency warnings). Schema remains 011 and the catalog remains 73 tools.

This does not implement a host parser, usage meter registration, durable receipt,
parent-child reconciliation, time buckets, reporter/outbox, admin alert policy or
usage TUI. The usage capability must remain false/null until those layers exist.
Next implementation slice: authenticated usage meter/attempt ownership and a
versioned receipt/latest-counter ledger with scoped period aggregates, followed
by verified host mappings, an owner-bound outbox and TUI/alert policy integration.
The pure arithmetic helper does not replace those identity or deduplication checks.

### M9-3 first usable read-only TUI

Core now exposes isekai watch with optional console extra (Textual 8.2.8),
owner-controlled connection profiles, mine/admin-project scopes, metadata tabs,
presence views, classification/CLI filters, live pagination and explicit unknown
usage. No Kernel/State/Lock/bootstrap or observer starts from watch.

Single-flight daemon reads have generation fencing, bounded clients, jitter/
backoff, stale last-confirmed display, and immediate clearing on auth/protocol
errors or scope changes. Metadata detail never fetches bodies or mutates state.
ANSI/OSC/control strings are stripped before plain rendering. Admin editing
forms and local workflow commands remain unimplemented, including under --manage.

- **47 new model/profile/headless UI tests + 2 package boundary tests passed**.
- Real HTTP + Textual headless admin/recipient flows passed over 73-tool Memory:
  32 bounded read calls for both actors, zero mutation calls, no local checkout.
- Built Core wheel, verified console modules and optional-only Textual metadata.
  Python **3.11.16** clean base install imports without Textual/Rich; the same
  wheel plus console extra passed all **47 console tests**, not editable source.
- Core full unit regression: **575 passed, 1 sandbox process-table skip**.
  That skipped process-tree cleanup regression passed separately with approval:
  **576 unit scenarios covered**, not a single no-skip full-suite run.
  Actual subscription-host tests were not selected or run. Ruff/whitespace pass.
- No real project was activated. Existing staged Core state DB remains unchanged.
  No deployment, login implementation, subscription CLI, commit or push.

This is a concrete TUI milestone, not M9 completion. Next required work remains
admin policy/recovery/reassignment forms and durable receipts, token accounting,
actual controller lifecycle and local workflow/lease integration, plus events.

## M9 presence milestone — 2026-09-11

### M9-2a persistence, worker observer and metadata reader

[Runtime contract](memory-presence-runtime.md): additive schema 011, eight new
tools (73 total), independent opt-in/admin policy, actor/private-capability-bound
register/report/end, non-refreshing retries, continuous idle, read-only whole-set
user aggregation and explicit bounded retirement with anti-replay tombstones.

Core adds a no-SQLite worker lifecycle reporter and scoped PresenceClient.
The reporter reconciles lost replies against committed state and sends current
observations only. Overview now distinguishes API availability from collection.
Actual long-lived MCP controller integration and TUI are not implemented yet.

- New tests: 45 pure decisions + 21 input/auth + 12 presence DB scenarios.
- Core reporter: 27 tests; presence reader: 57 tests, including conservative user
  aggregates and capability-versus-observation distinction.
- Actual HTTP and stdio synthetic suites passed with 73 tools. Core reporter and
  pinned reader verified two independent actors, waiting/approval and ended states.
  No subscription CLI account was used.
- A fresh dedicated DB verified populated M8 preservation through 010→011,
  empty-presence rollback, and refusal to roll back any observed history.
- Final Memory suite on the dedicated PostgreSQL 16 DB: **564 passed**, no skips
  (2,008 dependency warnings). Core full suite: **528 passed, 5 skipped**;
  four skips are explicitly unauthorized live subscription-host tests. The fifth
  sandbox process-table regression passed separately with approval (**529 unit
  scenarios covered**, not one no-skip full-suite run). Ruff and whitespace pass.
- The existing staged Core state DB is preserved. No real project opt-in,
  production migration, login work, deployment, commit or push.

Goal remains active: required controller lifecycle, token receipts/aggregation,
TUI views and admin forms, Core action integration and reconnect/event validation
remain. The following preparation and M9-1 counts are historical milestones.

## M9 implementation preparation — 2026-09-11

### M9-1 runtime slice — 2026-09-11

[Read-model contract](memory-collaboration-read-model.md): two read-only tools
(65 total), mine/project-admin scopes, identical list/count visibility, explicit
inactive and partial states, bounded live cursors and unavailable telemetry.
The Core client validates pinned DTOs without opening Kernel/SQLite, enforces
response limits and pins actor identity; errors never become cached success.

- Memory full suite on the new synthetic PostgreSQL 16 DB: **478 passed**,
  no skips; new read-model tests: **27 passed**.
- Core new client plus package boundaries: **42 passed**. After repairing the
  moved-path editable installation, the full unit suite passed **444 tests**
  with one sandbox process-table skip; that one test passed separately with
  approved process-table access (**445 covered in total**, not one no-skip run).
- Actual HTTP and stdio expose 65 tools; real Core overview/list queries pass
  after M8's revoked-sender/two-recipient recovery fixture. No query changed the
  recorded delivery/work state; missing idle/usage remained unavailable/null.
- Ruff and whitespace checks passed. Schema remains 010; only the new disposable
  test DB was initialized. No production migration or project activation.
- Core and Memory editable package registrations were refreshed with --no-deps
  at the moved paths, without upgrading runtime dependencies or editing the
  user's staged Core state database.

Goal mode is active for the remaining M9 implementation. This milestone is not
completion of the TUI, telemetry collectors, admin workflows or durable updates.

### M9-2a pure idle decisions — in progress, 2026-09-11

The first presence implementation adds the no-I/O presence_state module:
bounded policy values, fresh/stale/ended/unknown separation, continuous-idle
interval resets on reconnect/clock reversal, and scoped multi-session aggregation.
Heartbeat-only updates preserve idle start; a user is idle only when all known
open sessions are idle, with the shortest shared duration. Running plus a stale
session retains both the running state and uncertainty.

- **45 pure fake-clock tests passed**; Ruff passed. Tests cover 299/300 seconds,
  59/60-second freshness, quiet running/approval, incomplete observations, mixed
  sessions, page incompleteness, policy changes and invalid policy limits.
- This module is not connected to real collection yet. No presence migration,
  register/heartbeat/end tools, Core observer or TUI was enabled by this slice.
  The M9-1 API correctly continues to advertise telemetry as unavailable.
- Next: additive presence persistence and administrator policy, actor/session
  binding and monotonic reports, then Core opt-in observer and TUI integration.
  The goal remains active; token usage, admin forms and durable updates still
  require implementation and their own acceptance tests.

The user requires both contributors and administrators to work from the same
terminal dashboard. [The M9 plan](memory-collaboration-tui.md) specifies the
role-aware screens, all M8 admin policy/recovery actions, metadata/session APIs,
Core integration boundaries and staged acceptance tests. Admin TUI is required,
not a later web-only substitute. The existing M8 catalog remains 63 tools.

This preparation changes documentation only: no TUI/runtime code, new tools,
migrations, dependency installation, project activation, deployment or Git push.
The first implementation slice is M9-1 scoped read APIs and their no-mutation
tests. Existing moved-path venv and write-permission preflight remain explicit.

### TUI refinement: idle visibility, login deferred — 2026-09-11

New login and Nunchi authentication integration are explicitly deferred; M9
continues with existing project tokens and host-local credential references.
[Presence/idle design](memory-presence-idle.md) distinguishes observer freshness,
reported execution, work ownership and confirmed storage. It specifies scoped
multi-session user aggregation, server-clock durations, stale/reconnect behavior,
administrator observation policy and a deterministic acceptance matrix.
Idle means observed Core work inactivity, not human absence or availability.
This is a documentation refinement only; no presence collector, idle detector,
TUI runtime, authentication change or production setting was implemented.

### TUI refinement: token usage visibility — 2026-09-11

[Token usage design](memory-token-usage.md) adds user/project/work/session/CLI/model
views, input/output/cache semantics, reported-versus-estimated quality and explicit
missing coverage. Current Core context usage is an initial prompt-size estimate,
not a normalized model-consumption ledger. M9-2b plans host parsers and durable
receipts with cumulative/retry/parent-child deduplication, scoped period aggregates
and soft administrator alerts; M9-3/M9-4 expose them in the common TUI.
CLI-specific usage availability remains subject to versioned interface verification.
No usage collector, new tool, schema, TUI runtime, login integration, pricing lookup
or account-quota connection was implemented. This change is documentation only;
design checks are not runtime or actual subscription-usage verification results.

## M8 scope addition — 2026-09-10

The user requires project administrators to predesignate handoff recipients for
unexpected user departure. Fixed per-handoff recipients alone cannot satisfy
this: the departing user may be the recipient, or the sender may never have
published a handoff. The [continuity design](memory-project-continuity.md)
therefore adds project sender-to-recipient **1:N** policies, optional backups,
independent recipient delivery/acknowledgement, explicit work-unit ownership,
audited reassignment and recoverable server checkpoints. Multiple recipients
are active successors, not merely one primary and N standbys. These are
requirements are implemented by schema `010` and the opt-in Core integration.
The schema `009` package baseline remains the single-recipient contract.

## Expanded M8 validation — 2026-09-11

Seventeen new Memory tools (63 total) implement administrator policy/eligible
identities, immutable checkpoints, 1:N publication, independent delivery,
work-unit claims and audited reassignment. Core changes are based on fetched
`a7caff2` (HEAD matched origin/master), preserving the user's staged state DB.
Nine local Core MCP tools and matching CLI operations expose explicit intake;
worker capture is opt-in and never auto-enables a real project.

- Final Memory regression on a fresh PostgreSQL 16 database at schema 010:
  **449 passed**, no skips (1774 existing/dependency warnings), including
  48 new pure unit and 19 new PostgreSQL cases. This includes the final DB
  guard rejecting legacy mutation of continuity-managed sources.
- Final Core unit regression: **405 passed**. Four tree-sitter dependencies
  already declared by its latest commit were installed into its local venv;
  dependency declarations were not changed. Tests include lost-response retry,
  digest-verified checkpoint receipts, start/periodic/end capture and explicit
  capture-gap reporting, executable snapshots and local-MCP activation guards.
- Live Core → HTTP Memory → two Core recipients passed: stored tracked and
  untracked changes recovered after revoking the sender, independent intake,
  separate work claims and isolated preparation, with no automatic execution.
  The final run also exercised Core renewal, release/reclaim, stale-generation
  rejection and reported completion. HTTP/stdio exposed all 63 Memory tools.
- Populated 009 ↔ 010 migration preserved existing claims/payloads and refused
  populated continuity rollback. All six earlier migration smoke scripts also
  passed through 010 in separate empty disposable databases.
- The final 009 ↔ 010 smoke was repeated on a fresh separate database after
  the DB guard was added; preservation and populated rollback refusal passed.
- Memory and Core wheels built successfully. Imports from the extracted wheels
  confirmed 63 Memory tools, nine Core continuity tools and the packaged Core
  Project schema. Memory migrations remain source-deployment assets, not wheel
  contents; deploy the matching Alembic configuration/migrations explicitly.
- Ruff and git diff --check passed for both changed codebases. The user's
  staged Core .isekai/state.db was preserved without additional unstaged changes.
- During final packaging, the repository tree moved from security-philip/isekai
  to security-philip/security-project/isekai. The same worktrees and Core commit
  were confirmed at the new location and packaging checks completed there.
- The dedicated test PostgreSQL container was stopped with its synthetic data
  retained. No production migration, project opt-in, commit, push or automatic
  worker execution was performed.

## M8 package-baseline validation — 2026-09-10

M8 extends the existing push/claim contract without adding tools (46 total).
Schema `009` adds version, recipient, continuation and continuation digest;
existing version-1 payload hashes are unchanged. Addressed delivery requires
the designated actor and explicit version-2 opt-in; legacy list/pull exclude it.
Packets describe portable sources and uncommitted changes but grant no execution
authority. Core preflight is a documented requirement, not an implemented Core
resume workflow.

- Full PostgreSQL 16 suite: **382 passed**, no skips, including 19 new M8 DB
  cases. No-DB suite: **257 passed, 125 skipped**, including 40 M8 unit cases.
  Existing Python/asyncio deprecation warnings remain.
- M7/M8 focused DB suite: **38 passed**. Tests cover non-recipient admin denial,
  claim opt-in, recipient preservation after expiry/nack, private-token recovery,
  immutable recipient/package conflicts, live recipient token checks, replay
  after recipient revocation, one-winner concurrency and cross-project denial.
- Populated `008 → 009 → 008 → 009` migration smoke preserved legacy source and
  active claim fields. With M8 data, downgrade refused atomically for pending,
  claimed, acknowledged and expired states without discarding payloads.
- Actual HTTP/stdio E2E passed, including addressed delivery, legacy intake
  exclusion, package/digest round trip and the required preflight descriptor.
  All five earlier populated migration smoke scripts also passed through `009`.
- Isolated wheel packaging passed. Runtime dependency declarations were unchanged.
- `ruff check src migrations tests` and `git diff --check`: passed.

Only task-created disposable PostgreSQL databases were migrated. No Core code,
configured application database, Git remote, automatic polling or notification
deployment was changed. Existing M7 worktree changes were retained.

## M7 validation — 2026-09-10

Priority is multi-user work continuity, not adding Jira/Wiki/Nunchi tools.
Three additive tools expose bounded project/user views, expired recoverable
leases, sender-visible delivery state and absolute-deadline renewal. The old
handoff contracts, immutable payloads and schema `008` are unchanged.

- Full pytest on local Python 3.14 and a newly created disposable PostgreSQL 16:
  **323 passed**, no skips (106 PostgreSQL cases, including 19 M7 cases).
- Without a test DB: **217 passed, 106 explicitly skipped**. M7 contributes 39
  unit/contract cases. Existing asyncio/Python deprecation warnings remain.
- `ruff check src migrations tests` and `git diff --check`: passed.
- Wheel packaging with isolated build dependencies passed; the archive includes
  all three new handoff modules. Project runtime dependencies were not changed.
- Actual HTTP and stdio subprocess E2E: **46 tools**, existing M1–M6 flows,
  plus distinct publisher/recipient identities, wrong-owner/read-only/project
  rejection, monotonic renewal/retry and publisher-visible acknowledgement.
- Concurrent claims have one winner; repeated renewals extend once; old owners
  cannot renew/ack/nack after replacement. A renew waiting for a row lock samples
  DB time after the lock and rejects expiry. Reads disclose no claim capability,
  envelope or raw output. Cursor, classification and revocation tests passed.

No Core files, configured application DB, production deployment or Git remote
were changed. No automatic notifications or background polling were enabled.
All DB writes used synthetic test projects in the task-created container.

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
