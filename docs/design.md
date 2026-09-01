# ISEKAI Memory Design (v0.3)

## 1. Scope

`isekai-memory` is a standalone PostgreSQL-backed Work Handoff and Repository Registry MCP server. Handoff (Phase 1–6 recoverable-handoff server track) is implemented here. Core-side automatic acquisition and context injection are implemented in the `isekai-core` repository (`src/isekai/memory/`); this server provides the handoff and registry endpoints that Core consumes.

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

- `read`: list repos, check updates, and list handoffs
- `write`: push/pull/claim/get/ack/nack handoffs
- `admin`: all lower scopes (reserved for future policy tools)

Project-scoped operations compare the request `project_id` with the principal project. `from_user` and `claimed_by` are derived from `Principal.user_id`.

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

Alembic revision `003` is required. `/ready` verifies:

- database connectivity
- `alembic_version == 003`
- artifacts, artifact_policies, handoffs, handoff_claim_receipts, and access_tokens tables

Migrations are explicit and must run before server startup:

```bash
ISEKAI_MEMORY_DATABASE_URL=... alembic upgrade head
```

The service never silently migrates during process startup.

Note: the `artifacts` and `artifact_policies` tables remain in the database schema for backward compatibility but are no longer used by the active tool set.

## 7. Tool boundary

Nine tools are advertised: two repository registry tools and seven handoff tools. Every request is validated at runtime against the exact JSON Schema returned by `tools/list`. Missing/extra/invalid fields are controlled invalid-parameter errors rather than internal failures.

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

Passing syntax parsing or unit tests alone is not completion evidence.
