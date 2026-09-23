# ISEKAI Memory

Work Handoff, governed Project Experience, and Repository Registry for ISEKAI. This repository implements the standalone Memory service. ADE's embedded engine implements handoff acquisition and context injection in `engine/src/isekai/memory/`. Experience proposal, review, correction, history, forgetting and retrieval are explicit server tools. Clients can separately opt in to bounded experience recall; it remains disabled by default.

Artifact distribution has moved to Git Releases — Foundation and Preset archives are built in CI, published to each repository's releases, and installed locally via `isekai init --foundation <path> --preset <path>`. The Memory server no longer stores or serves artifact binaries.

Current schema: **020**. ADE's embedded engine is the active client for these improvements;
the standalone `isekai-core` repository is not required by ADE.
See [project materials and history](docs/project-sharing.md) and [multi-user operation and upgrade](docs/multiuser-operation.md)
for membership, cross-PC handoffs, file-sharing limits and deployment order.

## Implemented scope

- Explicit Git/directory/unknown project source metadata, independent of an optional clone URL
- Project-member materials, results and activity records with immutable IDs, citations, bounded search and deletion
- Opt-in non-Git file snapshots through the existing continuity policy and isolated preparation

- Correlated Task/Result handoff push, pending list, compatibility pull, and recoverable claim leases
- Multi-user available/claimed/sent inboxes, delivery status and fenced absolute-deadline lease renewal
- Immutable recipient routing and bounded portable continuation descriptors with explicit client opt-in
- Admin-managed 1:N successor policies, independent acknowledgements, fenced work ownership and audited emergency reassignment
- Stored workspace checkpoints and opt-in Core capture/isolated preparation for unexpected departure
- Repository registry for tracking Foundation/Preset release repositories (config-based, future UI administration planned)
- Project-scoped tokens with `read`, `write`, and `admin` scopes
- Optional GitHub OAuth/PKCE login with a dedicated server-side OAuth app, immutable user allowlist and shared project roles ([setup](docs/github-login.md), introduced in schema 016; live-app acceptance pending)
- Optional single-tenant Entra OIDC API authentication, stable user bindings and project membership ([setup](docs/entra-oidc.md), introduced in schema 015; live-tenant acceptance pending)
- MCP 2026-07-28 over stdio and stateless Streamable HTTP JSON-RPC at `POST /mcp`
- PostgreSQL persistence and Alembic migrations
- Source-backed project experience proposals, admin review, and bounded lexical search/read
- Immutable corrections, source-scoped suppression, validity windows, explicit forgetting and cursor pagination
- Evaluated lexical providers, source-bound citations and an opt-in Core reference adapter
- Durable offline extraction jobs, retry/dead-letter governance and fresh approved-reference project/phase summaries
- Source-bound native Skill drafts, immutable reviewable revisions and deterministic unsigned artifact export

The staged expansion design and Tencent capability mapping are in
[`docs/memory-expansion.md`](docs/memory-expansion.md). Delivery status is tracked
in [`docs/memory-expansion-progress.md`](docs/memory-expansion-progress.md).

Core now provides a shared contributor/admin terminal dashboard with scoped
views and explicit 1:N policy, checkpoint recovery, reassignment, erasure and
audit forms, user handover/preparation, controller/worker observation, token monitoring,
experience review and durable change recovery. See [M9 acceptance](docs/memory-m9-acceptance.md)
for local validation, supported telemetry and explicit operational exclusions.

### Removed / deferred

- **Artifact publish/fetch/resolve** — removed. Artifacts are now distributed via Git Releases.
- **Policy upsert/delete** — commented out for future expansion. The policy engine (`registry/policy.py`) is preserved and can be re-enabled when policy-based version resolution is needed.

## Requirements

For local Docker deployment, Python/PostgreSQL do not need to be installed on the host:

```bash
docker compose up -d
# Or: ./scripts/local.sh up
```

This starts PostgreSQL, applies migrations, then serves Memory at
`http://127.0.0.1:8100/mcp`. Database data survives `./scripts/local.sh down`.
Port 8100 binds to loopback by default. For team access, use an HTTPS proxy or encrypted tunnel;
`ISEKAI_LOCAL_BIND_HOST` explicitly selects a different interface when needed.
Existing token authentication remains enabled; issue keys explicitly with
`./scripts/local.sh token <project-id> <user-id> [read,write|admin]`.
See [local Docker operations](docs/local-docker.md) for ports, credentials, logs and TUI connection.
AWS deployment is intentionally separate. The requirements below apply to a host-based installation.

- Python 3.11+
- PostgreSQL 15+ (validation uses PostgreSQL 16)

## Install and migrate

```bash
pip install -e '.[test]'
export ISEKAI_MEMORY_DATABASE_URL='postgresql://isekai:isekai@localhost:5432/isekai_memory'
alembic upgrade head
```

The application and Alembic use `ISEKAI_MEMORY_DATABASE_URL`. `DATABASE_URL` remains an Alembic compatibility fallback. Run migrations explicitly before starting the server.

## Token administration

```bash
isekai-memory --issue-token \
  --project-id project-a \
  --user-id developer-a \
  --scopes read,write

isekai-memory --revoke-token '<token-uuid>'
```

The raw token is printed only by the issue command. HTTP accepts `Authorization: Bearer <token>` and the legacy configurable token header.

## Run

```bash
# Local MCP subprocess; trust boundary is the local process owner.
isekai-memory --mode stdio

# Team HTTP server
isekai-memory --mode http --host 0.0.0.0 --port 8100
```

Endpoints:

- `GET /health`: process liveness
- `GET /ready`: DB connectivity, required tables, and Alembic revision
- `POST /mcp`: stateless MCP JSON-RPC/Streamable HTTP endpoint
- `GET /tools`, `POST /tools/{name}`: authenticated diagnostic REST facade

## Configuration

Server settings can be provided via environment variables (`ISEKAI_MEMORY_` prefix) or a JSON config file (`--config <path>`).

### Repository registry

Register artifact repositories via the `repos` key in the config file. Each entry tracks a Git repository URL, artifact kind, and identity:

```json
{
  "repos": [
    {
      "url": "https://github.com/org/isekai-foundation",
      "kind": "foundation",
      "artifact_id": "standard-foundation",
      "current_version": "2.0.0"
    },
    {
      "url": "https://github.com/org/isekai-presets",
      "kind": "preset",
      "artifact_id": "development",
      "current_version": "2.0.0"
    }
  ]
}
```

Future: repository registration will be managed via UI.

## MCP 2026-07-28 contract

The server is modern-only. Clients do not send `initialize`, `notifications/initialized`, or `ping`; they start with `server/discover`. Every request carries `_meta` protocol version and client capabilities.

HTTP requests additionally require `MCP-Protocol-Version` and `Mcp-Method`. `tools/call` also requires `Mcp-Name`; `Mcp-Name` is rejected on other methods.

```bash
curl -sS http://localhost:8100/mcp \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: server/discover' \
  --data '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{},"io.modelcontextprotocol/clientInfo":{"name":"example","version":"1"}}}}'
```

## MCP tools

| Tool | Required scope | Purpose |
|---|---:|---|
| `memory_repo_list` | read | List registered artifact repositories |
| `memory_repo_check_updates` | read | Check repositories for newer releases |
| `memory_handoff_push` | write | Register a Task/Result handoff |
| `memory_handoff_list` | read | List non-expired pending handoffs |
| `memory_handoff_pull` | write | Compatibility one-shot claim (preserved for existing clients) |
| `memory_handoff_claim` | write | Acquire or replay a recoverable token-bound lease |
| `memory_handoff_get_claimed` | write | Recover the payload for an active lease |
| `memory_handoff_ack` | write | Idempotently acknowledge a lease |
| `memory_handoff_nack` | write | Idempotently release a lease with a bounded reason code |
| `memory_handoff_inbox` | read | Bounded live available/claimed/sent views, including expired recoverable leases |
| `memory_handoff_status` | read | Observe delivery metadata without claiming or consuming a handoff |
| `memory_handoff_renew` | write | Monotonically extend an active owned generation to an absolute deadline, capped by retention |
| `memory_experience_propose` | write | Propose a pending experience from a retained project handoff |
| `memory_experience_list` | admin | Paginate the review queue or other lifecycle states |
| `memory_experience_review` | admin | Approve/reject/archive/forget with expected version and replayable event receipt |
| `memory_experience_revise` | admin | Propose an immutable correction that replaces its parent on approval |
| `memory_experience_history` | admin | Paginate a revision family, review events and target suppression metadata |
| `memory_experience_suppression_release` | admin | Explicitly release a suppressed claim with a version guard |
| `memory_search` | read | Search approved, unexpired experiences with bounded excerpts |
| `memory_read` | read | Read an approved, unexpired experience with source attribution |
| `memory_generation_enqueue` | admin | Schedule bounded source extraction or a scoped reference summary |
| `memory_generation_list` | admin | Inspect durable jobs, provenance and dead letters with cursor pagination |
| `memory_generation_retry` | admin | Version-fenced dead-letter redrive with a lifetime attempt cap |
| `memory_summary_read` | read | Read a fresh, bounded approved-reference snapshot; never generates on read |
| `memory_skill_generate` | admin | Queue an offline scaffold from exact approved procedure sources |
| `memory_skill_propose` | write | Propose a pending native Skill with triggers, steps, validation and text resources |
| `memory_skill_revise` | admin | Create an immutable revision, fenced by the latest revision number |
| `memory_skill_review` | admin | Approve/reject/archive/forget using the review version |
| `memory_skill_list` | admin | Cursor-paginated review/history metadata |
| `memory_skill_inspect` | admin | Inspect a revision, its source evidence, freshness and review events |
| `memory_skill_read` | read | Read only an active, source-fresh reviewed revision as reference data |
| `memory_skill_export` | admin | Explicit deterministic native Skill archive, exact review version and Lock required |
| `memory_grant_create` / `memory_grant_revoke` / `memory_grant_list` | admin | Owner-issued exact-version reference grants and permanent revocation |
| `memory_shared_read` | read | Consumer-bound live grant/asset checks; no transitive sharing or cache authority |
| `memory_knowledge_sync` / `memory_knowledge_delete` / `memory_knowledge_list` | admin | Explicit bounded pushed Wiki snapshots, CAS, erasure and metadata inventory |
| `memory_knowledge_read` | read | Current unexpired publisher-reported reference data |
| `memory_skill_import` / `memory_skill_import_list` / `memory_skill_import_inspect` / `memory_skill_import_forget` | admin | Validate deterministic M5 archives into quarantine; list/inspect/erase, never install |
| `memory_feedback_record` | write | One explicit actor/asset-version observation; reported outcomes need local evidence |
| `memory_feedback_list` | admin | Bounded project feedback history, never a ranking or approval signal |

HTTP project-scoped tools require their `project_id` to match the token project. Actor fields are derived from the token and cannot be supplied by callers.

### Recoverable handoff lease contract

Clients generate a unique, high-entropy base64url `claim_token` (32–256 characters) for each claim attempt and retain it locally. Memory accepts the raw token only as a tool argument, immediately reduces it to a SHA-256 digest, and never persists, logs, or returns the raw value.

`memory_handoff_claim` can acquire a pending handoff or replace an expired lease. Repeating it with the same project, actor, handoff, and token while the lease is active returns the same claim without extending it. The effective lease deadline is capped by the handoff retention deadline. `memory_handoff_get_claimed` recovers a lost claim response. Ack and nack require the returned `claim_generation` and are idempotent through digest-only durable receipts; a nack makes the handoff pending again, and generation fencing prevents a delayed request from mutating a replacement lease. The handoff `classification` is stored and returned with its immutable Task/Result payload. Nack reason codes are limited to `retryable`, `processing_failed`, `shutdown`, and `cancelled`.

Lease duration is bounded by `ISEKAI_MEMORY_HANDOFF_CLAIM_LEASE_MIN_SECONDS`, `..._DEFAULT_SECONDS`, and `..._MAX_SECONDS` (defaults 30, 300, and 3600). JSON config uses `handoff.claim_lease_min_seconds`, `handoff.claim_lease_default_seconds`, and `handoff.claim_lease_max_seconds`.

### Multi-user continuity (M7)

Use separate project-scoped HTTP tokens for each user. The shared Memory server
connects their handoff state; each Core still owns its execution and approvals.

- `memory_handoff_inbox({project_id, view: "available"})` finds pending work and
  abandoned **expired leases**, without consuming either. `view: "claimed"`
  shows the current user's active leases; `view: "sent"` shows their deliveries.
- Use recoverable `claim`, retain the private claim token, and verify the source
  before continuing. `memory_handoff_status` lets teammates observe who acquired
  a handoff and whether it was acknowledged, without receiving raw payloads.
- For longer processing, call `memory_handoff_renew` with the same project,
  handoff, private token and generation plus an absolute `lease_expires_at`.
  Retry the **same deadline** on response loss. Renewal cannot revive an expired
  lease, extend retention, or take ownership from another user/session.
- Ack records handoff processing, **not completion of subsequent work**. Nack
  returns it for another claim. A worker that loses its lease must not assume it
  still owns the delivery; the server cannot stop a remote process.

The inbox is paginated and read-only, not a durable notification feed. On each
refresh, restart from the first page, deduplicate IDs and drain pages as needed;
use status for already tracked deliveries. M7 does not install an automatic
poller, fetch workspaces, add private recipient ACLs or auto-resume Core.
The existing pending-only list and one-shot pull keep their old contracts.
See [collaboration contracts and roadmap](docs/memory-collaboration.md).

### Addressed continuation packages (M8)

`memory_handoff_push` optionally accepts `recipient_user_id` and/or
`continuation`. Either creates a version-2 handoff. Recipients must have a live
read/write or admin token for the same project when a new handoff is published.
Only the designated user can acquire it, even after lease expiry; admin does
not override the recipient. This routes delivery, **not private project data**.

The continuation describes the goal, last sender-reported verified state,
exact repository commit, shared artifact hashes, uncommitted workspace state,
remaining work, next steps and blockers. It never contains executable fetch
commands or credentials. Local-only changes must be captured in a referenced
snapshot or marked unavailable. Memory validates descriptors, not remote bytes.

Version-2 rows do not appear in the legacy list and cannot be consumed by
one-shot pull. A capable client uses `memory_handoff_inbox`, then passes
`accept_handoff_version: 2` to recoverable claim. Claim/get return the package,
its digest and a **required or blocked preflight**, never execution approval.
Version-2 rows are deliberately protected from automatic legacy intake. The
separate continuity workflow below supports explicit Core inspection and preparation.

Run an explicit `alembic upgrade head` to apply current schema `010` before
starting this version (`009` introduced these packages). Existing version-1
payloads and digests are preserved. Downgrade
to `008` is refused once any M8 row exists, even if expired or acknowledged.
See [M8 package and recipient contract](docs/memory-continuation.md).

### Project continuity and unexpected departure (M8)

Project administrators configure sender-to-recipient 1:N designation, optional
backups, retention, work leases, checkpoint intervals/byte/path limits and the
emergency-takeover policy. Each recipient receives a separate delivery and ack;
work units have independent, generation-fenced ownership. Reassignment is
version-checked and audited, and cannot stop an already running remote process.

Stored checkpoints retain approved changed-file bytes independently of the
sender's token. Administrators can publish a saved checkpoint after departure,
split work between recipients, inspect history and explicitly forget source
bodies. There is no automatic departure detection or backup promotion.

Core provides nine local MCP tools and matching `isekai memory continuity`
commands for capture, inbox/status, inspection, acknowledgement, claim,
preparation, renewal and release. Capture requires explicit local opt-in and
intersecting admin/local path permissions. Preparation reconstructs into an
isolated directory using local Git objects and stored snapshot bytes; it never
runs the recovered work or bypasses normal checks/approval. Unsaved changes
since the last successful checkpoint remain unrecoverable.

See [M8 configuration, tools and recovery contract](docs/memory-project-continuity.md).
Schema `010` refuses downgrade once continuity history exists; take a backup
before migration. No real project is enabled automatically.

### Project experience workflow

Run `python -m alembic upgrade head` to apply revision `013` before starting this version.
The existing nine handoff/registry tools retain their contracts. Eight experience
plus four generation/summary, eight Skill, fourteen team-asset and three
collaboration tools, plus seventeen continuity, two read-only dashboard and eight
presence tools, seven usage tools and two change-feed tools extend the catalog to 82 tools.

The M9-1 [collaboration read model](docs/memory-collaboration-read-model.md) adds
scoped overview/list queries and a bounded Core client without modifying leases,
deliveries or local State. [Presence APIs and the opt-in Core worker observer](docs/memory-presence-runtime.md)
now provide scoped session/idle metadata and bounded readers. Core also provides
an optional `isekai watch` TUI with connection profiles and read-only default views.
Explicit --manage adds server-authorized policy/recovery/reassignment/erasure/audit
forms. [Usage ledger, opt-in Core collection and TUI](docs/memory-usage-runtime.md)
now separate reported/estimated/missing counts, with scoped periods and admin soft
alerts. Codex 0.154.0 parsing is synthetic-fixture validated; unknown versions and
Claude/Kiro are explicitly unsupported, never zero. Controller/user-action and
durable-event integration are also implemented and tested with synthetic data;
no real account or project was activated. Cost, billing and budget features are out of scope.

M6 sharing, pushed Wiki knowledge, offline native Skill import and explicit
feedback are documented in [Team asset contracts](docs/memory-team-assets.md).
No network crawling, Git operations, Skill installation, shared search, ranking
changes or Core opt-in happens automatically. Import is an unsigned quarantined
copy, not source approval or a revocable grant.

After a handoff exists, call `memory_experience_propose` with arguments such as:

```json
{
  "project_id": "project-a",
  "source_handoff_id": "00000000-0000-4000-8000-000000000001",
  "idempotency_key": "auth-retry-decision-1",
  "kind": "decision",
  "title": "인증 모듈의 재시도 정책",
  "content": "응답 유실 후 재시도는 동일 claim과 receipt로 처리한다.",
  "tags": ["auth", "retry"]
}
```

Replace the example source UUID with a real handoff in the token's project. The
server derives author identity, source digests and classification. The source may
already be acknowledged or past its delivery window. Proposal retries use a key
scoped to the project and authenticated actor; changing content under the same key
is a conflict. All proposals begin as `pending`.

An admin lists `memory_experience_list` with `project_id`, then calls
`memory_experience_review` with `project_id`, the returned `memory_id`,
`action: "approve"`, and `expected_version: 1`. Alternatively, use `reject` for a
pending item or `archive` for an active item with its current version. Review
returns `applied_status`/`applied_version`: on retries these acknowledge the original
event, even if a subsequent action has changed the current state.

Readers call `memory_search` with `project_id` and `query`, then `memory_read` with
`project_id` and `memory_id`. Neither consumes a handoff. Both exclude pending,
rejected, archived, superseded, forgotten and out-of-validity items, and default `max_classification` to `internal`.
This ceiling narrows output; it is not a token clearance. Existing tokens grant
access at project scope. `source_lock_digest` optionally requires exact source
Lock provenance, not a claim that an experience remains applicable to a new Lock.

Search accepts `kind`, `limit` (1–50, default 10), and `max_chars` (1000–16000,
default 8000). It combines PostgreSQL full-text ranking with an all-term substring
fallback for Korean and other text. `result_chars` counts the compact JSON `items`
array, including escaped excerpts and attribution, not the enclosing MCP response
or model tokens. `truncated` indicates that count or character limits omitted
matches or shortened an excerpt. Provenance is retained when shortening excerpts.
`memory_read` returns the full bounded content and source digests.

### Retrieval providers and Core references

The default `postgres_lexical` retains baseline ranking. Set
`ISEKAI_MEMORY_RETRIEVAL_STRATEGY=postgres_weighted_lexical` (or JSON
`{"retrieval":{"strategy":"postgres_weighted_lexical"}}`) to opt in to title/tag
weighting. This is still lexical search, not vector or hybrid retrieval. On the
versioned synthetic Korean/English fixture, nDCG@3 improved from 0.777 to 0.850
with Recall@3 unchanged at 0.85; paraphrase and cross-language gaps remain.
These are agent-curated fixture results, not independently judged production
quality. See [measurement details](docs/memory-retrieval.md).

Search/read now include citation schema 1, with hashes binding the project,
memory version, source digests, full content and returned excerpt. These prove
the returned relationship, not truth or authority. Provider candidates are
project/lifecycle/validity/visibility filtered before ranking and then hydrated
from PostgreSQL with those checks again. There is no shared result cache.

In the updated sibling `isekai-core`, an enabled `integrations.memory` can add:

```json
{
  "experience_recall": true,
  "experience_limit": 5,
  "experience_max_chars": 8000,
  "experience_timeout_seconds": 3
}
```

These fields extend the existing integration; endpoint and credential reference
are still required. Enabling recall sends a bounded query derived from the Unit
objective before execution or Context preview. Core requests the exact pinned
Lock and effective classification ceiling, validates citation hashes, and adds
only optional reference sections within budget. It does not perform network calls
inside Context assembly. Unsupported/offline/malformed responses yield no
experience references; required handoff synchronization keeps its existing rules.
No real project configuration is enabled by this change.

### Corrections, suppression and retention

Content is immutable. An admin calls `memory_experience_revise` with the active
`memory_id`, its `expected_version`, a new `idempotency_key`, and complete
replacement `kind`, `title`, `content`, and optional `tags`. Omitting
`source_handoff_id` retains the parent's source. Approve the returned pending ID
with `expected_version: 1`: the parent becomes `superseded` in the same transaction.
Competing or stale corrections cannot overwrite the approved replacement.
Classification can stay the same or increase, never decrease through a revision.

`memory_experience_history` takes `project_id` and `memory_id`; it returns family
members and their events, including retired versions. Both history and review
listing accept `limit` and return `next_cursor`/`has_more`. Send `next_cursor` as
`cursor` to continue in the same project/view. Listing retains `offset` for older
clients; do not combine it with a cursor.

Reject, supersede and forget suppress the old source-backed claim against future
proposals and approvals. Matching uses the complete source payload digest and a
normalized kind/body fingerprint, not semantic similarity. Changing only title,
tags, actor or proposal key does not bypass suppression. A title/tag-only revision
does not suppress an unchanged claim. To explicitly allow a suppressed claim,
call `memory_experience_suppression_release` with `project_id`, `memory_id` and
`expected_suppression_version` from history's `suppression.version`. This does not
reactivate old rows, and stale release retries cannot undo a newer rejection.

Optional `valid_from`/`expires_at` form a half-open validity interval. Approval and
retrieval require the current time to be within it; there is no scheduled activation
or automatic purge. Use review action `forget` with the current lifecycle version
to erase the stored title/body/tags/search/source JSON and release its source FK.
IDs, hashes, ancestry and retry receipts remain. Forgetting does not erase source
handoffs, backups or exported copies. Successful retries return original receipts,
including after forgetting, without restoring content.

See [the M2 lifecycle contract](docs/memory-lifecycle.md) for boundaries and rollback
restrictions. Migration `005` refuses downgrade after revision, forgetting or
valid-from data exists. No LLM calls, automatic extraction or Skill installation
are enabled by these tools.

### Offline extraction and reference summaries (M4)

An admin enqueues `memory_generation_enqueue` with `project_id`, `kind: "extract"`
and optional `limit` (20 by default; max 100). Repeat while `has_more` is true.
An explicitly enabled, finite worker processes the queue:

```bash
ISEKAI_MEMORY_GENERATION_ENABLED=true isekai-memory \
  --run-generation --project-id project-a --max-jobs 20
```

The local structured extractor quotes ResultEnvelope summaries into **pending**
experiences. Existing admin review is required before retrieval. There are no
external model calls, provider credentials or monetary charges. The worker is
disabled by default and is never started by the MCP server or Context reads.

For an approved-reference summary, enqueue `kind: "summary"`, optionally with
`phase_id`, `max_classification` and `source_lock_digest`, then run the worker.
Call `memory_summary_read` with the same scope. It returns `ready`, `missing` or
`stale`; stale snapshots never return old text. Snapshots hold IDs/versions/digests,
not plaintext copies, and are revalidated against current source/lifecycle state.
They are bounded reference projections, not LLM-written narrative summaries.

See [the M4 generation contract](docs/memory-generation.md) for source coverage,
lease recovery, retry limits, budgets and correction/forget protections. Revision
`006` refuses downgrade when generation receipts exist. No Core summary injection
or Skill installation is enabled.

### Reviewed native Skill assets (M5)

Select 1–8 approved experience IDs with their exact lifecycle `version`; at least
one must be a `procedure`, all must share one Lock and have retained successful
handoffs with evidence references. `memory_skill_generate` takes those `sources`
and queues a scaffold on the existing offline worker. It does not copy source
prose into executable instructions. Generated scaffolds cannot be approved directly.

Use `memory_skill_inspect` to review the scaffold and source evidence, then
`memory_skill_revise` with its `skill_id`, `expected_revision`, a new
`idempotency_key`, fresh `sources` and a complete `body`. The body defines `title`,
`description`, `triggers`, source-linked `steps`, `validation` and optional bounded
text `resources`. An admin must author applicability, procedure or validation;
merely renaming a generated scaffold is rejected. Direct authored candidates use
`memory_skill_propose` and still require approval.

Approve the new `revision_id` with `expected_version: 1` using
`memory_skill_review`. Only one revision can be active, and competing approval
cannot overwrite a changed active revision. `revision` tracks immutable content
versions; `version` tracks lifecycle changes. Source forgetting erases all bound
Skill bodies/resources atomically. Source retirement, changes and expiry block reads
and exports until a fresh revision is reviewed.

`memory_skill_export` requires `revision_id`, current `expected_version`, exact
`source_lock_digest` and optionally `max_classification`. It returns a base64
gzip/tar archive, manifest and three digests. Repeating the same active export is
deterministic. Files are non-executable; only reviewed body text is instruction,
and source bindings/resources remain data. The package grants no capabilities.

This is ISEKAI-native `kind: skill`, **not a Codex `SKILL.md` or a signed release**.
Core's existing verifier accepts it structurally; installation, release signing,
runtime policy and execution still require separate explicit workflows. No Core
code changes or actual Skill installations are made by M5. See the
[M5 contract](docs/memory-skills.md) for full limits, trust boundaries and examples.

## Docker

The image does not provision PostgreSQL or run migrations. Connect it to a migrated database; do not use `localhost` for a database in another container.

```bash
docker network create isekai-memory-net
docker run -d --rm --name isekai-memory-pg --network isekai-memory-net \
  -e POSTGRES_USER=isekai -e POSTGRES_PASSWORD=isekai \
  -e POSTGRES_DB=isekai_memory postgres:16

docker build -t isekai-memory .

docker run --rm --network isekai-memory-net \
  --entrypoint alembic \
  -e ISEKAI_MEMORY_DATABASE_URL='postgresql://isekai:isekai@isekai-memory-pg:5432/isekai_memory' \
  isekai-memory upgrade head

docker run --rm -p 8100:8100 --network isekai-memory-net \
  -e ISEKAI_MEMORY_DATABASE_URL='postgresql://isekai:isekai@isekai-memory-pg:5432/isekai_memory' \
  isekai-memory
```

Kubernetes manifests are intentionally not included. Deployment templates and values are maintained separately.

## Validation

```bash
pytest -q
ruff check .
```

`tests/e2e_smoke.py` exercises the migrated database, authenticated HTTP MCP endpoint, handoff round trips, and project/scope denials. Run it against a fresh disposable PostgreSQL 16 database and a running server after issuing admin, read-only, and different-project tokens:

```bash
MEMORY_BASE_URL='http://localhost:8100' \
MEMORY_ADMIN_TOKEN='<project-1-admin-token>' \
MEMORY_READ_TOKEN='<project-1-read-token>' \
MEMORY_CROSS_PROJECT_TOKEN='<project-2-token>' \
python3.11 tests/e2e_smoke.py
```

The real stdio entry point can be checked against the same migrated database:

```bash
ISEKAI_MEMORY_DATABASE_URL='postgresql://isekai:isekai@localhost:5432/isekai_memory' \
python3.11 tests/stdio_e2e_smoke.py
```

The experience integration tests exercise real PostgreSQL persistence and the
authenticated HTTP MCP/REST handlers, including concurrent writes, review receipts,
classification/expiry filters and Korean recall. They use unique project IDs and
require an explicitly configured, disposable database already migrated to `010`:

```bash
MEMORY_TEST_DATABASE_URL='postgresql://test:test@localhost:5432/memory_test' \
  pytest -q tests/test_experience_postgres.py tests/test_experience_lifecycle_postgres.py
```

Without `MEMORY_TEST_DATABASE_URL` those integration tests are skipped; unit tests
do not substitute for them.

To exercise real HTTP and stdio subprocesses automatically against the same
disposable database, run `MEMORY_TEST_DATABASE_URL=... python tests/run_local_e2e.py`.
The runner creates a unique test project, starts a loopback-only HTTP server,
performs the smoke tests, stops its server and revokes its temporary tokens.

For migration preservation tests, select a **separate empty disposable database**:
`MEMORY_TEST_DATABASE_URL=... python -m tests.migration_e2e_smoke`. It seeds a claimed
handoff at `003`, verifies upgrade and experience use at the current head, downgrades its
synthetic experience data, checks that the original handoff/claim is unchanged,
then returns to the current head. It refuses a nonempty public schema.

Evaluate the versioned retrieval fixture with
`MEMORY_TEST_DATABASE_URL=... python -m tests.retrieval_eval`. It creates unique
synthetic projects and prints Recall@3, nDCG@3, MRR, empty-query accuracy, response
characters and local p95 latency for both providers; it never migrates a database.
Raw measurements are in [retrieval-evaluation-v1.json](docs/retrieval-evaluation-v1.json).

To include the real Core client in the local E2E runner, set `MEMORY_CORE_PYTHON`
to the Core environment's Python executable and `MEMORY_CORE_SOURCE` to its `src`
directory in addition to `MEMORY_TEST_DATABASE_URL`, then run
`python tests/run_local_e2e.py`. Core and Memory retain independent dependencies.

For M1 data backfill and guarded M2 rollback, select **another empty disposable
database** and run `MEMORY_TEST_DATABASE_URL=... python -m tests.migration_lifecycle_e2e_smoke`.
It verifies 502 existing M1 rows, original proposal/review receipts, rejection
suppression backfill, safe `004 ↔ head` rollback and transactional refusal to
downgrade after M2 revisions/forgetting.

For populated M4 upgrade and receipt-safe rollback refusal, select **another empty
disposable database** and run
`MEMORY_TEST_DATABASE_URL=... python -m tests.migration_generation_e2e_smoke`.
The real transport runner also executes M4 HTTP enqueue/review/summary operations
with a separately launched offline worker CLI.

For M5, run `MEMORY_TEST_DATABASE_URL=... python -m tests.migration_skills_e2e_smoke`
against **another empty disposable database**. It verifies populated M4 preservation
through `006 ↔ 007` and atomic refusal to discard Skill history. The real E2E runner
also exercises Skill generation/revision/review/export/forget; with
`MEMORY_CORE_PYTHON` and `MEMORY_CORE_SOURCE`, it invokes the unchanged Core archive
and manifest verifier, including rejection of tampered content. No installation
occurs during that check.

For M6, select **another empty disposable database** and run
`MEMORY_TEST_DATABASE_URL=... python -m tests.migration_team_e2e_smoke`.
It verifies `007 ↔ 008` preservation and refusal to discard revoked/deleted/
forgotten team history. The real E2E runner covers two-project grants, uncached
revocation, Wiki deletion, feedback and export → quarantined import → erasure.

See [`docs/design.md`](docs/design.md) for contracts and trust boundaries.

## M9 collaboration console

The follow-up [multi-project console](docs/memory-multi-project-console.md) makes
`isekai watch` a global connection directory with project switching. Nunchi login
and new RBAC remain separate; existing project-token authorization is unchanged.

See [M9 acceptance and operating boundary](docs/memory-m9-acceptance.md),
[user work/lease console](docs/memory-user-work-console.md), and
[durable change feed](docs/memory-collaboration-events.md).
The current Memory schema is 013 with 82 MCP tools. Core provides the optional
user/admin TUI; token monitoring is not billing or budget management.
