# ISEKAI Memory

Work Handoff server and Repository Registry for ISEKAI. This repository implements the standalone Memory service. Core-side automatic acquisition and context injection are implemented in the `isekai-core` repository (`src/isekai/memory/`); this server provides the handoff and repository registry endpoints that Core consumes.

Artifact distribution has moved to Git Releases — Foundation and Preset archives are built in CI, published to each repository's releases, and installed locally via `isekai init --foundation <path> --preset <path>`. The Memory server no longer stores or serves artifact binaries.

## Implemented scope

- Correlated Task/Result handoff push, pending list, compatibility pull, and recoverable claim leases
- Repository registry for tracking Foundation/Preset release repositories (config-based, future UI administration planned)
- Project-scoped tokens with `read`, `write`, and `admin` scopes
- MCP 2026-07-28 over stdio and stateless Streamable HTTP JSON-RPC at `POST /mcp`
- PostgreSQL persistence and Alembic migrations

### Removed / deferred

- **Artifact publish/fetch/resolve** — removed. Artifacts are now distributed via Git Releases.
- **Policy upsert/delete** — commented out for future expansion. The policy engine (`registry/policy.py`) is preserved and can be re-enabled when policy-based version resolution is needed.

## Requirements

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

HTTP project-scoped tools require their `project_id` to match the token project. Actor fields are derived from the token and cannot be supplied by callers.

### Recoverable handoff lease contract

Clients generate a unique, high-entropy base64url `claim_token` (32–256 characters) for each claim attempt and retain it locally. Memory accepts the raw token only as a tool argument, immediately reduces it to a SHA-256 digest, and never persists, logs, or returns the raw value.

`memory_handoff_claim` can acquire a pending handoff or replace an expired lease. Repeating it with the same project, actor, handoff, and token while the lease is active returns the same claim without extending it. The effective lease deadline is capped by the handoff retention deadline. `memory_handoff_get_claimed` recovers a lost claim response. Ack and nack require the returned `claim_generation` and are idempotent through digest-only durable receipts; a nack makes the handoff pending again, and generation fencing prevents a delayed request from mutating a replacement lease. The handoff `classification` is stored and returned with its immutable Task/Result payload. Nack reason codes are limited to `retryable`, `processing_failed`, `shutdown`, and `cancelled`.

Lease duration is bounded by `ISEKAI_MEMORY_HANDOFF_CLAIM_LEASE_MIN_SECONDS`, `..._DEFAULT_SECONDS`, and `..._MAX_SECONDS` (defaults 30, 300, and 3600). JSON config uses `handoff.claim_lease_min_seconds`, `handoff.claim_lease_default_seconds`, and `handoff.claim_lease_max_seconds`.

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

See [`docs/design.md`](docs/design.md) for contracts and trust boundaries.
