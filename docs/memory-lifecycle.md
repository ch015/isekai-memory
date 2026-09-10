# M2 — Experience revisions, suppression and retention

Migration `005` extends the M1 experience model. This is the M2 implementation
contract; M3–M6 remain separate planned deliveries.

## Immutable revisions

`memory_experience_revise` is admin-only. It takes an active `memory_id`, its
`expected_version`, a new proposal idempotency key and complete replacement
kind/title/content/tags. It creates a pending row with `supersedes_id`, the captured
parent lifecycle version, a family root and `revision_number = parent + 1`.
The original body is unchanged. `version` remains the lifecycle concurrency guard;
`revision_number` describes content ancestry, including competing pending branches.

Omitting `source_handoff_id` retains the parent's source. An explicit new handoff
must belong to the same project. Classification inherits the higher of the parent
and new source. Revision metadata and the manual-correction marker are server-owned.

Approval locks and checks both rows, retires the parent as `superseded`, activates
the replacement and writes both event receipts in one transaction. The parent must
still be active at the version captured by the proposal. A partial unique index
also prevents two active rows in one family. Competing replacements, an intervening
archive/forget and stale callers cannot overwrite an approved correction.

Normal proposals never edit an existing memory. A revision requires an explicit
admin call and review; marking a proposal as manual is not a caller capability.
`memory_experience_history` is an admin-only, paginated family view including
pending branches, retired rows, tombstones and their review events.

## Suppression

Rejecting a candidate, superseding an old revision, or forgetting an item records
a suppression scoped to `(project, source payload digest, content fingerprint)`.
Title/tag-only revisions with the same claim identity do not suppress that claim.
The fingerprint covers kind and NFKC/casefold/whitespace-normalized body. Changing
the title, tags, proposal key or actor cannot bypass it. Changed source evidence
or different text is a different candidate. The source digest covers the complete
handoff payload, including attempt identity, not only its raw output; a new
handoff attempt is therefore a new evidence revision. This is deterministic
matching, not semantic contradiction detection.

Both proposal creation and approval check suppression. Already-pending duplicates
cannot be activated after rejection of the same claim. Successful proposal/review
retries still return their original receipts and never reactivate a memory.
M1 rejected rows are backfilled into the suppression table during migration.

Admins may explicitly call `memory_experience_suppression_release` with a target
memory ID and `expected_suppression_version`, available in the history response.
Release is version-guarded: a delayed retry cannot release a newer rejection.
The suppression row retains its reason, version and last modification identity.
Release permits a new proposal; it does not restore an old row to active state.

M2 serializes experience mutations per project with a transaction-scoped PostgreSQL
advisory lock, then obtains row locks. This makes proposal, review and suppression
ordering explicit, including concurrent duplicate proposals. Independent projects
and read queries remain concurrent. Finer write locking is a future throughput
optimization, not an implicit current guarantee.

## Validity and forgetting

`valid_from` and `expires_at` define `[valid_from, expires_at)`, independently of
handoff delivery expiry. Omitted endpoints are unbounded. Approval before
`valid_from` or after expiry fails; activation is never scheduled automatically.
Normal search/read filter both bounds. Expired items remain inspectable by admins.

`memory_experience_review` adds the explicit admin action `forget`. It requires
the current lifecycle version and works on any non-forgotten state. It atomically
replaces title/body with `[forgotten]`, clears tags/search text/source JSON, drops
the source handoff foreign-key reference and records a suppression plus an event.
The tombstone retains IDs, classification, hashes, ancestry, actor/timestamps and
idempotency receipts. History cannot recover the erased plaintext from this row.
This is content erasure in Memory, not erasure from database backups, source
handoffs, exported artifacts or another consumer's local cache.

Unforgotten memories continue to restrict deletion of their source handoff.
Forgetting every referencing memory releases that restriction. M2 never deletes a
handoff or changes its claim state. Operators must separately evaluate source
retention; active leases and evidence retention are not overridden by this API.
There is no default automatic purge interval. Administrators can enumerate retired
or expired items and explicitly forget them one at a time.

## Cursor contract

Review listing retains bounded offset compatibility and adds `next_cursor`.
Cursor pagination uses descending `(created_at, id)` keysets, so new items ahead
of a page do not shift the next page. History uses the same ordering. Cursors are
bounded base64url JSON, validated and bound to project plus status/family scope.
They are navigation positions, not signed authorization tokens. Authorization is
always re-evaluated. Cursor and offset cannot be combined. This is not a frozen
snapshot: a status change can remove a queued item between requests.

## Upgrade and rollback

`004 → 005` preserves bodies, handoffs, review receipts and proposal idempotency.
Old proposal fingerprints are backfilled in bounded batches. Database guards
prevent ordinary content updates; forgetting is the explicit erasure exception.

Downgrade to `004` is allowed only before revision/forget/valid-from data has been
introduced. Afterwards it fails without modifying data: `004` cannot represent
those states safely, and downgrade must not resurrect retired or forgotten content.
Use a compatible forward fix or an operator-managed backup restoration when needed.

## Acceptance

- Approval switches retrieval from parent to replacement atomically; only one
  competing replacement wins and both histories remain attributable.
- Rejection/supersession/forget suppress new and already-pending duplicates;
  explicit release is replayable without releasing a newer suppression.
- Source, family, list, history and release are project-scoped; writers cannot
  revise, review, forget or release suppression.
- Validity boundaries are checked after locking; cursor pagination tolerates
  inserts and rejects mismatched or malformed cursors.
- Forget erases plaintext and search data, retains replay receipts, and releases
  only its own source dependency. Forgotten data is never restored by a retry.
- Populated upgrade preserves M1 data; supported rollback preserves it, while
  rollback with M2 states fails transactionally.
