# M9-1 collaboration read model

Historical slice: implemented locally on 2026-09-11 at schema `010`.
The current release is schema `013`; see [M9 acceptance](memory-m9-acceptance.md).
This document specifies the read model, not automatic enabling of a presence/token collector.

## Calls

Both tools require an existing project token with read or admin scope:

- `memory_collaboration_overview`: identity, scope-level allowed tools, current
  continuity-policy configured/version/enabled flags, bounded counts and telemetry
  capabilities.
- `memory_collaboration_list`: metadata for `work`, `inbox`, `sent` or
  `checkpoints`; default 20, maximum 50 items and a scoped live keyset cursor.

Common arguments are `project_id`, `scope=mine|project` (default mine),
`max_classification` (default internal), `include_inactive` and
`include_acknowledged` (both false). The last flag affects inbox entries; it is
included in every cursor/response binding. List additionally requires `view`
and accepts `limit` and `cursor`.

`scope=project` requires project admin authority. Even an admin starts in mine
scope unless explicitly requesting the project view. This is a query scope,
not a UI management-mode or privilege-elevation switch.

| View | Mine | Project admin view |
| --- | --- | --- |
| work | Publisher or current, non-revoked bundle recipient | All permitted project work metadata |
| inbox | Own non-revoked deliveries | Project deliveries, including revoked only with include_inactive |
| sent | Bundles whose original from_user is this actor | Project bundles; publisher and created_by are separate |
| checkpoints | Own metadata | Project checkpoint metadata |

Source bodies, snapshots, continuation text and claim credentials/hashes are
never returned. A classification maximum only narrows existing project access;
it is not a new clearance grant. Every count and list uses the same visibility
predicate. A removed recipient cannot recover former access by changing a
cursor, choosing include_inactive, or using the bundle's old identifier.

## Response guarantees

Contract version 1 includes project/actor, the complete requested scope,
server observed_at, no_store and consistency=snapshot_per_response_live_pagination.
Allowed tools are scope-level UI hints, not approval to mutate a particular
resource. Existing mutation tools still enforce recipient, version and lease
conditions at execution time.

Lists return items, has_more, next_cursor and coverage=page. Refresh starts from
the first page. Work sorts by updated_at/id (also exposed as the pagination
created_at key); other views sort by created_at/id. Pages are a live view, not
a durable event cursor or one cross-request snapshot.

Overview counts at most 10,001 visible candidates per view. Up to 10,000, value
and lower_bound agree and coverage is complete. Above that, value is null,
lower_bound is 10,000 and coverage is partial. This lower bound is conservative,
not an exact count. A database timeout is an explicit retryable error, never
an empty/zero-count success.

Each response uses a read-only repeatable-read PostgreSQL transaction and one
server timestamp for lease/retention decisions. Statement timeout is 1.5 seconds,
with an 8-second outer budget. Polling does not acquire the project mutation
advisory lock, acknowledge deliveries, renew claims, save checkpoints, append
receipts/events, or create missing policies. No schema migration is needed.

Work contains raw state plus effective_state, ownership and
execution_state=unobserved. A stored claimed row whose lease has expired remains
unchanged in storage; the response reports lease_expired/expired. Source expiry
or revocation makes ownership unavailable. Checkpoints distinguish retained,
expired and forgotten without returning erased bodies.

Presence and idle now advertise true API capabilities with separate_query /
use_presence_tools / null telemetry; use the [scoped presence reader](memory-presence-runtime.md)
for actual observations and policy. A capability is not proof of client opt-in or
collected activity. Token usage remains unavailable / not_implemented / null.
The Core v1 reader also accepts the earlier all-unavailable v1 response. Counts
cover collaboration records, not online people; polling creates no activity.

## Core integration

`isekai.memory.overview.CollaborationClient` wraps the existing bounded HTTP
MCP client without constructing a Kernel, opening SQLite or requiring an active
Lock. It exposes only overview/listing. Calls have a 5-second transport timeout
and 512 KiB response ceiling (or smaller existing transport configuration).

Pinned local schemas reject unexpected/private fields, wrong projects/filters,
invalid dates, over-ceiling classifications, oversized/duplicate rows and
inconsistent counts/pages. Date-time validation explicitly requires a timezone
without relying on jsonschema's optional format dependency. The first accepted
response pins actor identity (or the caller supplies the expected actor); changing
profiles requires a new client. Errors propagate without cached-success or
anonymous fallback. This layer does not grant mutation capabilities or render
remote text as terminal markup.

## Verification scope

New pure and authenticated PostgreSQL tests exercise scope separation, metadata
only, no mutation, independent ack, recipient withdrawal, pagination bindings,
classification filtering, expired claims/sources, forgotten bodies, bounded
partial counts, database read-only enforcement and token revocation. Core tests
cover pinned schemas, identity/scope drift, malformed metadata, unavailable
telemetry and request limits.

The synthetic real-transport workflow now tests both tools over stdio and the
Core client over HTTP after M8's two-recipient continuity fixture. It verifies
that work/delivery state is unchanged by the dashboard queries. No real project,
subscription CLI, production DB or TUI screen is exercised by that smoke test.

Implementation progress and actual test counts are recorded in the
[work ledger](memory-expansion-progress.md).
