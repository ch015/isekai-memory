# M8: addressed, reproducible handoff packages

This document describes the single-recipient package baseline from schema `009`.
Current schema `010` adds [1:N continuity and opt-in Core checkpoint/preparation](memory-project-continuity.md)
through separate tools. No automatic worker resume or notifications are enabled.
M7 delivery leases remain delivery ownership, not a distributed lock over work
running on another machine.

## Publishing

`memory_handoff_push` retains all required Task/Result fields and accepts two
optional fields:

- `recipient_user_id`: the exact user identity allowed to acquire this handoff.
- `continuation`: the structured version-1 package below.

Either field makes the handoff **version 2**. If neither field is present the handoff is
the unchanged version-1 contract. New fields participate in the immutable
`payload_digest`; the continuation also gets a canonical SHA-256 digest. The
same phase-attempt cannot be republished with a different recipient or package.
Unchanged retries preserve identity even if the recipient's token later expires
or is revoked. No schema migration rewrites existing payload digests.

For a new addressed handoff, the recipient must currently have an unrevoked,
unexpired token for the same project with `read` and `write`, or `admin`.
This is a bounded reachability check, not a user directory or membership model.
It does not guarantee future availability. Tokens are never copied into the
handoff, and administrators cannot claim on another recipient's behalf.

Recipient routing is **not per-user confidentiality**. Existing project read
authority continues to cover metadata and project experience. The sender sees
delivery in `sent`, the recipient finds it in `available`; other users do not
see it in their available inbox and cannot claim it, even after lease expiry.
Project-authorized status reads may still show it, with `can_claim: false` for a
non-recipient. The newly required [project continuity policy and admin
reassignment](memory-project-continuity.md), including 1:N recipients with
independent deliveries and work-unit ownership, are implemented separately on
schema `010`, not by this schema `009` baseline. Its scalar recipient and handoff-wide ack
cannot represent independent multi-recipient delivery. Private handoff ACLs
remain separate work.

## Continuation schema 1

All strings, lists and references are bounded; the canonical package is at most
64 KiB. Unknown fields are rejected. Required fields:

- `schema_version: 1`.
- `goal`, `verified_state`: bounded descriptions of the intended continuation
  and last sender-reported verified state. They are not execution receipts.
- `repository`: configured logical `source_id`, full 40/64-hex `commit`, optional
  informational `branch`. A branch alone is not a reproducible reference.
- `workspace`: `state` is `clean`, `captured`, or `unavailable`.
- `artifacts`: at most 20 descriptors with unique `id`, `source_id`, opaque
  `reference`, `kind` (`workspace_snapshot`, `output`, `evidence`), SHA-256
  `digest` and `size_bytes` (1–104857600).
- `remaining_work`, `next_steps` (non-empty), and `blockers`: bounded text lists.
  `decisions` is an optional bounded text list.

`captured` requires `snapshot_artifact_id` naming a declared workspace-snapshot
artifact. `unavailable` requires a nonblank `reason`; `clean` accepts neither.
Uncommitted tracked **and untracked** files must be captured or explicitly marked
unavailable. Memory validates the descriptor and reference relationship, not the
existence, permissions, contents or completeness of the actual snapshot.

Source IDs and artifact references are opaque identifiers, not arbitrary URLs,
filesystem paths, credentials or commands. The receiving Core must resolve them
only through its approved source registry. Sender-local workspace paths and
output paths in the legacy envelopes are not portable artifact locators.

## Opt-in consumption and downgrade safety

- Old `memory_handoff_list` and one-shot `memory_handoff_pull` expose/consume only
  version-1 rows. An old Core cannot silently ingest and acknowledge M8 work.
- `memory_handoff_inbox` and `memory_handoff_status` expose version, recipient
  and continuation digest, but never the full continuation package.
- `memory_handoff_claim` requires `accept_handoff_version: 2` to acquire/replay a
  version-2 row. Recipient and version checks are inside the claim row lock and
  precede mutation. Version-1 callers remain unchanged.
- A version-2 claim/get response includes `handoff_version`, `recipient_user_id`,
  `continuation`, `continuation_digest`, `payload_digest`, and a `preflight`
  descriptor. Full data still requires the actor's active private claim token.
- Ack, nack, lease renewal and generation fencing retain M7 semantics. A
  recipient's expired lease is available to that recipient, not to everyone.
- Schema downgrade refuses to discard **any** version-2 row, including expired
  or acknowledged rows. With only legacy rows, `008 → 009 → 008` preserves them.

## Receiving Core preflight contract

The returned preflight is always `verification_required` or `blocked`, never an
authorization or `ready_to_resume`. A missing package, `unavailable` workspace or sender-reported
blockers produce `blocked`. Required recipient-side checks are:

1. Validate project/user/claim identity, generation, retention and active lease.
2. Recompute the continuation and full payload hashes; validate the schema.
3. Resolve the source Lock under local policy. A missing/incompatible Lock needs
   explicit reconciliation; remote approval is not transferred.
4. Resolve the approved repository source and verify the exact commit.
5. Authorize each artifact source, enforce per-object and aggregate download
   budgets, and verify size/digest.
6. Reconstruct an isolated workspace, including tracked and untracked changes;
   validate approved formats, paths/modes, extracted-byte and file-count limits
   before extraction and never execute on fetch.
7. Re-run relevant checks and establish local execution authority and approvals.
8. Recheck the lease immediately before recording intake/continuation.

This baseline supplies the inputs and checklist. The schema-010 continuity
path implements opt-in Core validation/preparation for approved local Git and
Memory-stored snapshots; local checks and execution approval remain required.
Version-2 handoffs must not be advertised as automatic cross-machine resume. Blockers,
instructions and claimed verification are untrusted sender data. Ack records
handoff processing, not proof that these checks or subsequent work succeeded.
