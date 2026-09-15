# ISEKAI Memory Design (v0.8)

## 1. Scope

`isekai-memory` is a standalone PostgreSQL-backed Work Handoff, Project Experience and Repository Registry MCP server. Handoff (Phase 1–6 recoverable-handoff server track) is implemented here. Core-side automatic acquisition and context injection are implemented in the `isekai-core` repository (`src/isekai/memory/`). Experience APIs are explicit server tools; M3 adds separately opt-in Core recall, disabled by default.

Project Experience adds source-backed pending proposals, admin review and bounded
lexical search/read. See [memory-expansion.md](memory-expansion.md) for its detailed
contracts, module boundaries and the staged Tencent capability mapping.
M2 adds immutable corrections, atomic supersession, scoped suppression, validity,
forgetting and cursor history; see [memory-lifecycle.md](memory-lifecycle.md).
M3 provides a retrieval-provider contract, measured lexical weighting, source-bound
citations and an opt-in Core adapter; see [memory-retrieval.md](memory-retrieval.md).
M4 adds durable offline generation jobs, source coverage, fenced retries and fresh
approved-reference project/phase snapshots; see [memory-generation.md](memory-generation.md).
External model providers and automatic summary injection remain disabled/unimplemented.
M5 adds source-bound native Skill scaffolds, immutable authored revisions, review,
atomic source-forgetting propagation and deterministic unsigned exports verified by
Core's existing artifact contract; see [memory-skills.md](memory-skills.md).

Artifact distribution has moved to Git Releases. Foundation and Preset archives are built in CI, published to each repository's releases, and installed locally via `isekai init/update`. The Memory server no longer stores or serves artifact binaries.

Out of scope: Redis, CRDT, vector search, dashboards, multi-region replication, Kubernetes, and deployment templates.

### Removed / deferred features

- **Artifact publish/fetch/resolve tools** — removed. The artifact registry code (`registry/catalog.py`, `registry/verification.py`) is retained in the codebase for reference but is no longer connected to the MCP tool dispatcher.
- **Policy upsert/delete tools** — commented out for future expansion. The policy engine (`registry/policy.py`) with Core-compatible SemVer resolution is preserved and can be re-enabled when policy-based version resolution is needed. Uncomment the tool entries in `server/tools.py` and reconnect the dispatcher in `main.py`.

## 2. Transports and protocol

- **stdio MCP**: local subprocess transport. Authentication relies on the OS/process boundary.
- **Streamable HTTP**: stateless JSON-RPC requests at `POST /mcp`. HTTP uses project-scoped bearer tokens.
- **REST diagnostics**: `/tools` and `/tools/{name}` call the same validation, authorization, and dispatcher path as MCP.

The only supported MCP protocol version is `2026-07-28`. The server does not implement the removed `initialize`, `notifications/initialized`, or `ping` flow. Clients begin with `server/discover`; every request contains `_meta["io.modelcontextprotocol/protocolVersion"]` and `_meta["io.modelcontextprotocol/clientCapabilities"]`.

Every HTTP MCP request requires:

- `MCP-Protocol-Version`, equal to the request `_meta` version;
- `Mcp-Method`, equal to the JSON-RPC method;
- `Mcp-Name` only for `tools/call`, equal to `params.name`.

Missing or mismatched routing headers are HTTP 400 / JSON-RPC `-32020`. An explicitly unsupported version is HTTP 400 / `-32022`. `server/discover` and `tools/list` return cacheable results with `resultType`, `ttlMs`, `cacheScope`, and server identity only in `_meta["io.modelcontextprotocol/serverInfo"]`.

## 3. Authentication and authorization

`access_tokens` stores only SHA-256 token hashes. A verified token becomes a principal:

```text
Principal(user_id, project_id, scopes)
```

Scopes:

- `read`: repos, handoffs, active experiences, fresh reference summaries and active source-fresh Skills
- `write`: handoff delivery, experience proposals and native Skill proposals
- `admin`: all lower scopes, review/lifecycle, generation administration and explicit Skill revision/export

Project-scoped operations compare the request `project_id` with the principal project. `from_user`, `claimed_by`, experience authors and reviewers are derived from `Principal.user_id`. Experience classification is inherited from its source. Search/read classification ceilings are output filters, not additional token clearances; tokens still authorize the whole project.

Token lifecycle is administered by `--issue-token` and `--revoke-token`. Revoked and expired tokens are rejected.

## 4. Repository registry

Artifact repositories are configured via the server config file (`repos` key). Each entry tracks a Git repository URL, the artifact kind it provides, and its artifact identity:

```json
{
  "repos": [
    {"url": "https://github.com/org/isekai-foundation", "kind": "foundation", "artifact_id": "standard-foundation", "current_version": "2.0.0"},
    {"url": "https://github.com/org/isekai-presets", "kind": "preset", "artifact_id": "development", "current_version": "2.0.0"}
  ]
}
```

`memory_repo_list` returns the configured repository entries, optionally filtered by kind. `memory_repo_check_updates` reports the configured state per repository so users can compare against installed versions.

Future: automatic Git provider API polling for latest release tags. Repository registration will be managed via UI rather than direct config editing.

## 5. Handoff contract

A handoff stores one Core Task Envelope and correlated Result Envelope. Push validates:

- required Task/Result fields and envelope types
- `correlation_id`, `work_bundle_id`, `unit_id`, `phase_attempt_id`, optional `session_id`, and `task_id`
- top-level unit/attempt against the Task
- Result status and handoff classification against top-level values
- lock snapshot and context bundle digests
- optional raw output against Result `raw_output_digest`
- configured raw output size
- `envelope_digest = sha256(canonical(task) || canonical(result))`

Actor identity comes from the principal. `expires_at` is a timezone-aware DB value. Listing marks elapsed pending rows expired and excludes them. The compatibility `memory_handoff_pull` tool preserves the original one-shot, project-bound conditional transition.

Recoverable consumers use `memory_handoff_claim`, `memory_handoff_get_claimed`, `memory_handoff_ack`, and `memory_handoff_nack`. The client generates and retains a unique high-entropy raw `claim_token`; the service hashes it with SHA-256 before calling persistence and stores only the digest. Claim-token schema failures use fixed redacted messages. Claim acquisition uses a PostgreSQL row lock, then reads `clock_timestamp()` after lock acquisition, and applies a monotonically increasing generation. It accepts pending rows and elapsed recoverable leases, while an active same-project/same-actor/same-token request replays the original lease without extending it. The effective lease deadline is capped by the handoff retention deadline. Get requires the same active project, actor, token digest, and unexpired lease.

Ack and nack require the active generation guards and are committed atomically with a digest-only receipt. Those receipts make response-loss retries idempotent without allowing an old token to mutate a replacement lease. Ack moves the handoff to `acknowledged`; nack returns it to `pending`. Nack reasons are constrained in both JSON Schema and PostgreSQL to `retryable`, `processing_failed`, `shutdown`, or `cancelled`. Lease min/default/max settings are validated as `min <= default <= max` and every request must remain within those configured bounds.

A separate `payload_digest` covers the complete handoff submission. Retry of the same `(project_id, phase_attempt_id)` returns the original ID/timestamps only if the payload digest matches; conflicting payloads are rejected.

## 6. Database and lifecycle

Alembic revision `008` is required. `/ready` verifies:

- database connectivity
- `alembic_version == 008`
- artifacts, artifact_policies, handoffs, handoff_claim_receipts, access_tokens, memory_experiences, memory_experience_events, memory_experience_suppressions, memory_generation_jobs, memory_generation_attempts and memory_summary_snapshots tables
- memory_skills, memory_skill_revisions, memory_skill_sources and memory_skill_events tables
- memory_asset_grants, memory_knowledge_documents, memory_knowledge_events, memory_skill_imports and memory_asset_feedback tables

Migrations are explicit and must run before server startup:

```bash
ISEKAI_MEMORY_DATABASE_URL=... alembic upgrade head
```

The service never silently migrates during process startup.
Migration `005` preserves M1 payloads and receipts and backfills claim fingerprints.
Downgrade to `004` is refused after revisions, forgetting or valid-from data exists.
Migration `006` adds generation jobs/attempt receipts and plaintext-free summary
manifests; it refuses downgrade if any generation job receipts exist.
Migration `007` adds immutable Skill revisions/bindings and a transactional source
invalidation/erasure trigger. Downgrade is refused once Skill revisions or jobs exist.
Migration `008` adds exact-version asset grants, pushed Wiki snapshots/events,
quarantined Skill imports and explicit feedback. Downgrade refuses any M6 history,
including erased/revoked entries. [M6 contracts](memory-team-assets.md) describe
freshness, project authorization, copy versus grant semantics and local-only scope.

Note: the `artifacts` and `artifact_policies` tables remain in the database schema for backward compatibility but are no longer used by the active tool set.

## 7. Tool boundary

Forty-three tools are advertised: two repository registry tools, seven handoff tools,
eight experience tools, four generation/summary tools, eight Skill tools and fourteen
team-asset tools. Every request is validated
at runtime against the JSON Schema returned by `tools/list`. Missing/extra/invalid
fields are controlled invalid-parameter errors rather than internal failures.
Validity date-time validation is provided without optional format dependencies and
requires a valid timezone-bearing timestamp; leap seconds are not accepted.

MCP tool execution failures use `CallToolResult.isError=true`; JSON-RPC protocol failures retain standard codes such as `-32700`, `-32600`, `-32601`, and `-32602`.

## 8. Deployment boundary

The repository contains a production Dockerfile but no Kubernetes manifests. A later deployment repository/template owns migration jobs, ingress, certificates, service accounts, and environment-specific configuration. The application image expects a reachable, already migrated PostgreSQL database.

## 9. Completion evidence

Required checks for the server baseline and handoff tracks:

1. Python package and Docker image build
2. Alembic upgrade against PostgreSQL 16
3. Handoff push → list → compatibility pull and recoverable claim → get → ack/nack, including expiry/reclaim races
4. Repository list and check-updates with configured repos
5. read/write/admin and project authorization denial cases
6. stdio and HTTP `server/discover` → `tools/list`/`tools/call`, with no initialize exchange
7. required HTTP routing-header rejection tests
8. unit test and lint pass
9. experience proposal → pending queue → review → search/read → archive, including concurrent retries, project isolation, expiry/classification exclusion and unchanged handoff state
10. correction → atomic replacement → history → forget; competing edits, suppression/release fencing, cursor scope and populated migration/rollback checks
11. judged Korean/English retrieval, pre-top-K visibility, citation binding and real Core-client recall with optional context budgets and offline fallback
12. generation restart/lease fencing, atomic pending proposals, manual-source protection, bounded retries/budgets and fresh source-only summaries; real worker CLI and guarded M4 rollback
13. source-backed native Skill scaffolding/manual authorship, immutable revisions and single-active review races, source forgetting/expiry, deterministic safe exports and acceptance by the existing Core artifact verifier without installing anything

Passing syntax parsing or unit tests alone is not completion evidence.
