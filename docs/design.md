# ISEKAI Memory Design (v0.2)

## 1. Scope

`isekai-memory` is a standalone PostgreSQL-backed Artifact Registry and Work Handoff MCP server. Phase 1–5 and the independent Phase 6 recoverable-handoff server track are implemented here. Core-side automatic acquisition and context injection require the `isekai-core` checkout.

Out of scope: Redis, CRDT, vector search, dashboards, multi-region replication, Kubernetes, and deployment templates.

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

- `read`: resolve/fetch artifacts and list handoffs
- `write`: publish artifacts and push/pull/claim/get/ack/nack handoffs
- `admin`: policy upsert/delete and all lower scopes

Project-scoped operations compare the request `project_id` with the principal project. `from_user`, `claimed_by`, and `published_by` are derived from `Principal.user_id`.

Token lifecycle is administered by `--issue-token` and `--revoke-token`. Revoked and expired tokens are rejected.

## 4. Artifact contract

Accepted artifacts are deterministic-style gzip tar archives containing only regular files:

```text
manifest.json
<every path declared by manifest.files>
```

The server rejects unsafe/duplicate paths, non-regular entries, undeclared or missing files, excessive compressed/uncompressed bytes, excessive members, and size/digest/executable-mode mismatches.

Digest meanings match Core:

```text
artifact_digest = sha256(canonical(manifest without artifact_digest/signatures))
manifest_digest = sha256(exact manifest.json bytes)
archive_digest  = sha256(exact archive bytes)
```

`(artifact_id, kind, version)` is immutable. A retry succeeds only when all three stored digests match; otherwise it is a conflict. Fetch re-hashes the stored archive before returning it.

## 5. Policy contract

A policy key is unique by:

```text
(organization_id, project_pattern, kind, artifact_id)
```

Upsert is deterministic. Resolve applies priority descending, updated time descending, then ID ascending. The first matching policy controls each artifact identity. A non-required high-priority policy suppresses lower policies intentionally.

Version ordering and ranges match Core SemVer behavior, including prerelease/build values and `>=`, `<=`, `>`, `<`, `=`, `^`, and `~`. Selection uses the highest matching semantic version, not publish time.

## 6. Handoff contract

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

## 7. Database and lifecycle

Alembic revision `003` is required. `/ready` verifies:

- database connectivity
- `alembic_version == 003`
- artifacts, artifact_policies, handoffs, handoff_claim_receipts, and access_tokens tables

Migrations are explicit and must run before server startup:

```bash
ISEKAI_MEMORY_DATABASE_URL=... alembic upgrade head
```

The service never silently migrates during process startup.

## 8. Tool boundary

Twelve tools are advertised. Every request is validated at runtime against the exact JSON Schema returned by `tools/list`. Missing/extra/invalid fields are controlled invalid-parameter errors rather than internal failures.

MCP tool execution failures use `CallToolResult.isError=true`; JSON-RPC protocol failures retain standard codes such as `-32700`, `-32600`, `-32601`, and `-32602`.

## 9. Deployment boundary

The repository contains a production Dockerfile but no Kubernetes manifests. A later deployment repository/template owns migration jobs, ingress, certificates, service accounts, and environment-specific configuration. The application image expects a reachable, already migrated PostgreSQL database.

## 10. Completion evidence

Required checks for the server baseline and independent Phase 6 handoff/acquisition tracks:

1. Python package and Docker image build
2. Alembic upgrade against PostgreSQL 16
3. Registry publish → policy resolve → fetch
4. Handoff push → list → compatibility pull and recoverable claim → get → ack/nack, including expiry/reclaim races
5. read/write/admin and project authorization denial cases
6. stdio and HTTP `server/discover` → `tools/list`/`tools/call`, with no initialize exchange
7. required HTTP routing-header rejection tests
8. unit test and lint pass

Passing syntax parsing or unit tests alone is not completion evidence.
