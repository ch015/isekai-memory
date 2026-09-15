# Multi-user work continuity

Memory is a shared handoff service, not the owner of Core execution state. Each
user's Core retains its own approvals, workspace, execution receipts and locks.
Receiving or acknowledging a handoff does not finish a task, transfer approval,
install a Skill, fetch a repository, or automatically resume a worker.

## Staged delivery

| Stage | Scope | Acceptance |
|---|---|---|
| M7 | Observable handoff delivery and safe lease renewal | Project-scoped available/claimed/sent inbox, metadata status, expired-lease discovery, competing-user and stale-owner tests |
| M8 | Reproducible packages and departure recovery | Admin-configured sender-to-recipient 1:N, independent deliveries, work-unit ownership, audited reassignment, stored checkpoints and opt-in Core capture/preparation |
| M9 | Shared user/admin TUI and timely client integration | Scoped dashboard, session reports, administrator TUI forms, Core actions, bounded polling and durable reconnect/catch-up; see [implementation plan](memory-collaboration-tui.md) |
| M10 | Team operations | Full membership lifecycle, escalation automation, retention and operational observability; basic admin continuity policy/reassignment moved into M8 |

Jira, Wiki and Nunchi connectors are deferred until the collaboration path is
usable. They are not prerequisites for sharing work.

Unexpected departure is a first-class requirement: see the implemented
[project continuity contract](memory-project-continuity.md). Schema `010`
implements the administrative recovery path and opt-in Core checkpoints;
schema `009` remains the legacy single-recipient package contract.

## M7 API contract

M7 introduced three tools on schema `008`. The current M8 baseline requires
schema `010`; M8 initially added recipient-aware views and opt-in continuation delivery on `009`;
see [M8 contract](memory-continuation.md). Existing version-1 Task/Result
handoff payloads remain immutable.

### `memory_handoff_inbox` (read)

Required: `project_id`. Optional: `view` (`available`, default; `claimed`;
`sent`), `unit_id`, `limit` (1–100, default 20), `cursor`, and
`max_classification` (default `internal`).

- `available`: unexpired pending handoffs **and expired recoverable leases**.
  With M8, these must be unaddressed or addressed to the authenticated user.
- `claimed`: active recoverable leases held by the authenticated user. The
  client still needs its private claim token to recover the payload or mutate
  the lease. A second session for the same user does not gain that token.
- `sent`: handoffs published by the authenticated user, including terminal and
  retention-expired delivery states, while the source row is retained.

Returns bounded metadata, `observed_at`, `has_more`, `next_cursor`, and
`cache_policy: no_store`. Summary and note previews are capped at 512 characters
each and explicitly marked if truncated. Envelopes, raw output and claim-token
digests are never included. Metadata includes source hashes for later preflight;
these are provenance, not proof of task completion or current applicability.

Ordering is `(created_at DESC, id DESC)`. Cursors are bound to the project,
authenticated actor, view, unit filter and classification filter. Cursors are
positions, not authorization. Every request rechecks token/project authority.
An inbox is a live view, **not a durable change feed or snapshot**: a changed
lease may leave or enter a page. Pollers must restart from the first page on each
refresh cycle, drain pages as needed, deduplicate by handoff ID and use status
for tracked items. Reusing an exhausted cursor can miss new or reavailable work.
An example client refresh interval is five seconds with backoff on errors; M7
does not install a polling daemon or promise immediate delivery.

### `memory_handoff_status` (read)

Required: `project_id`, `handoff_id`. Optional: `max_classification`.
Returns the same metadata projection for one project handoff, without claiming
or consuming it. Unknown, cross-project and filtered records share one error.

`delivery_state` distinguishes `available`, `leased`, `lease_expired`,
`acknowledged`, `legacy_claimed`, and `expired`. `can_claim` is advisory at
`observed_at`; only the atomic claim operation decides the winner. An
acknowledgement records delivery/processing of this handoff, not completion of
the recipient's subsequent Core work. `legacy_claimed` has no recoverable lease
and is never automatically reassigned.

### `memory_handoff_renew` (write)

Required: `project_id`, `handoff_id`, `claim_token`, `claim_generation`, and
`lease_expires_at` (absolute timezone-bearing timestamp).

The server locks the same handoff row as claim/ack/nack, then checks the user,
token digest, generation, active lease and retention deadline using database
time. It advances the deadline monotonically, caps it at retention, and rejects
extensions beyond the configured maximum lease duration from database time.
Renewal does not change claim generation, payload, or retention.

Retry **the same absolute deadline** after a lost response. A current deadline
already covering the request is a no-op, so retries do not keep extending work.
The result reports the current deadline and whether this call extended it; it
is not a replay of a historical receipt. Expired, replaced, nacked, acknowledged,
legacy, or wrong-actor/token/generation claims cannot be renewed. A client that
loses its lease must stop claiming ownership and reacquire with the normal
claim operation; Memory cannot stop processes already running on another host.

## Authorization and compatibility

HTTP tokens remain project-scoped with server-derived user identity. Neither M7
nor M8 adds a user directory or membership administration. M8's continuity
contract adds explicit recipient access and admin checkpoint recovery, not a
retroactive private-data ACL over existing project experiences and metadata.
Project read authority covers project handoff metadata;
`claimed` and `sent` personalize that existing shared project space.
`max_classification` only narrows results; it is not a token clearance.
Local stdio represents one trusted process owner, not a multi-user identity
provider. Teams should use authenticated HTTP behind a TLS-terminating trusted
deployment, with distinct user tokens; credentials must not appear in handoffs.

`memory_handoff_list` remains pending-only and compatibility pull remains
one-shot; both are now limited to version-1 rows. Use inbox and recoverable
claim/get/ack/nack for single-recipient team work, and the separate continuity
tools for 1:N delivery. M8 requires an explicit schema `010` migration;
`accept_handoff_version: 2` alone does not opt into 1:N handling. Core capture
and preparation are opt-in; execution always requires fresh local checks/approval.
