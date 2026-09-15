# M8 project continuity and 1:N handoff

Implemented on schema **010**, with the single-recipient package contract from
009 preserved. Core integration is explicitly opt-in. This is an authenticated
MCP/REST service and Core CLI/local-MCP implementation, not an administration UI,
membership directory, automatic departure detector or unattended worker resume.

```text
Project admin -> defaults / sender-specific 1:N recipients / backups / capture policy
                                   |
Sender Core -> immutable server checkpoint -> admin recovery or permitted publication
                                   |
                      one source, separate deliveries
                         /         |         \
                    recipient B    C          D
                    own intake     own intake own intake
                    work unit 1    unit 2     unit 3
```

Multiple recipients are active successors, not merely one primary plus standby
users. All receive the pinned context; each acknowledges independently. B's
acknowledgement never consumes C's delivery or completes C's work. Explicitly
separated work units can run in parallel. Without a supplied work breakdown,
publication creates **one** `continue` work unit with all recipients as eligible
assignees and only one active private-token owner.

## Administrator configuration

`memory_continuity_policy_set` requires project `admin` authority, a full policy,
`expected_version` (0 for creation), `idempotency_key` and a nonblank `reason`.
`memory_continuity_policy_get` returns the current policy/version and the
authenticated project/user identity. `memory_continuity_members` lists eligible
project user IDs with bounded pagination, never credentials or token hashes.

Example policy-set arguments (replace the project and user IDs):

```json
{
  "project_id": "project-a",
  "expected_version": 0,
  "idempotency_key": "continuity-policy-1",
  "reason": "Prepare for unexpected contributor departure",
  "policy": {
    "enabled": true,
    "default_recipient_user_ids": ["bob", "carol"],
    "default_backup_user_ids": ["dave"],
    "sender_rules": [
      {
        "from_user_id": "alice",
        "recipient_user_ids": ["bob", "carol"],
        "backup_user_ids": ["dave"]
      }
    ],
    "retention_hours": 168,
    "lease_seconds": 300,
    "checkpoint_interval_seconds": 60,
    "checkpoint_max_bytes": 1048576,
    "checkpoint_allowed_paths": ["src", "tests", "README.md"],
    "allow_emergency_takeover": false
  }
}
```

- Up to 32 active recipients, 32 backups and 100 sender rules. Each sender has
  at most one rule; the rule replaces defaults rather than merging them.
- Recipient sets are unique; active and backup sets cannot overlap. A sender
  cannot be their own successor. Configure an appropriate sender override for
  administrators who also contribute work.
- Eligible recipients have an unrevoked, unexpired token in the same project
  with `read` + `write`, or `admin`. Recheck on publication/reassignment; this
  does not guarantee human availability or grant membership/access.
- Checkpoint retention is 1–8760 hours; leases 30–3600 seconds; requested Core
  checkpoint interval 30–3600 seconds. Existing sources never gain retention
  when policy changes. Snapshot canonical JSON budget is 1024–1048576 bytes;
  the separate continuation descriptor remains capped at 64 KiB.
- Capture paths are up to 100 literal project-relative file/directory prefixes,
  not commands, URLs or arbitrary host paths. Core also intersects them with
  local opt-in paths and effective local file authority.
- Policy changes do not silently reassign existing deliveries or promote
  backups. Disabling is allowed even after all recipients lose credentials;
  it blocks new capture/publication/claims, not existing retained reads or
  explicit processing/release of already-held work.

## Checkpoints before a user disappears

`memory_checkpoint_save` (`write`) requires `work_id`, `expected_version`,
`continuation`, `classification`, `lock_snapshot_digest`, `idempotency_key` and
optional `snapshot`. The publisher is derived from authentication; no caller
may supply `from_user`. Versions are serialized per project/publisher/work;
classification cannot decrease over that work's history. Receipts are durable
and actor-bound. Source bodies/hashes are immutable except explicit erasure.

Unlike the old Task/Result handoff, a checkpoint can represent **in-progress**
work with no successful Result. It records an exact repository commit, sender
observations, remaining work, next steps, blockers and snapshot provenance.
Reported verification and instructions remain untrusted data.

Snapshots are non-archive JSON objects, schema version 1, with at most 100 files:
`path`, canonical `content_base64`, SHA-256 `digest`, optional boolean
`executable` (default false). Null content/digest means a tracked deletion.
The continuation's workspace artifact must bind these exact stored bytes,
`source_id: memory-checkpoint` and `reference: snapshot-<digest hex>`.
Captured checkpoints require actual snapshot bytes, not a personal-machine URL.

Paths reject traversal, symlinks on Core reads, credential/state directories,
common secret filenames and file/directory/case collisions. Core does not read
hardlinked files for capture. Recognizable private keys and selected token
formats are rejected; **this is not comprehensive secret detection**. Use narrow
approved scopes and classification/retention policy. Ignored files and local
Core state/credentials are not backups and are not automatically uploaded.

`memory_checkpoint_list` exposes own metadata, or project-wide metadata to an
admin, including timestamps/gaps and expired/forgotten history. Payload reads
require the publisher or project admin via `memory_checkpoint_read`; successors
read only through their active delivery. `memory_checkpoint_forget` is an
explicit admin erasure: it removes body/snapshot bytes, revokes dependent
deliveries and fences dependent work, preserving hashes and audit receipts.
Expiry denies reads/recovery; physical cleanup is **explicit**, not a deployed
background retention collector.

## Publication and independent delivery

`memory_continuity_publish` takes `source_kind` (`checkpoint` or `handoff`),
`source_id`, `expected_policy_version`, `idempotency_key`, `reason`, optional
`recipient_user_ids` and optional `work_units`:

```json
[
  {"key": "implementation", "summary": "Continue implementation", "assignee_user_ids": ["bob"]},
  {"key": "verification", "summary": "Verify the saved changes", "assignee_user_ids": ["carol"]}
]
```

The checkpoint publisher may publish to a subset of the admin-configured sender
recipients; administrators may recover another user's checkpoint and explicitly
select any eligible same-project successors. No sender credentials or graceful
shutdown are required. All recipients and work units are created atomically.
There is one bundle per exact source; retries do not duplicate fan-out. Up to
32 lifetime work-unit keys are retained, including terminal/cancelled history.

Promoting a legacy handoff is admin-only and accepts only unexpired pending or
expired recoverable claims. It preserves the original recipient, envelopes and
payload digest, fences old ownership, and marks the source `continuity_managed`.
The DB also rejects later legacy mutations. Old list/pull/claim cannot consume
it; the old status tool reports `continuity_managed`. Acknowledged/retention-
expired/nonrecoverable legacy claims cannot be reopened. Acknowledgement is
not task completion: subsequent interrupted work needs a new checkpoint source.

| Tool | Contract |
| --- | --- |
| `memory_continuity_inbox` | Own live, unexpired active deliveries; optional acknowledged entries; bounded actor/filter-bound cursor |
| `memory_continuity_status` | Publisher, current recipient or admin: independent intake counts and work states; no source body or claim hashes |
| `memory_continuity_read` | Active assigned recipient: pinned context without acquiring a work lease; no admin impersonation |
| `memory_continuity_ack` | Durable idempotent acknowledgement of only the caller's delivery; never work completion |
| `memory_continuity_claim` | Eligible assignee: one active actor/private-token owner per unit; no automatic execution |
| `memory_continuity_renew` | Active actor/token/generation only; absolute bounded deadline; cannot extend source retention |
| `memory_continuity_release` | Fenced release or reported completion, with reason/idempotency receipt; not verified execution |

Inbox cursors are live pagination, not a notification feed. Refresh from the
first page and deduplicate by delivery ID; do not reuse an exhausted cursor as
a subscription. Status returns up to 128 delivery-history entries and marks
truncation; the audit tool provides bounded further history. Project routing is
not a new per-user confidentiality or token-clearance model.

## Administrative reassignment and emergency recovery

`memory_continuity_reassign` is admin-only. It requires the complete new
recipient/work-unit assignment, `expected_version`, an `expected_generations`
map for **every existing work-unit key**, `idempotency_key` and `reason`.
The current project policy version is captured in the audit event.

Unchanged recipients keep their delivery IDs and acknowledgements. Removed
recipients lose delivery access; replaced work owners lose their private claim
generation. Readded recipients get new delivery IDs. Unrelated work claims
remain intact. Omitted nonterminal units are cancelled; terminal work cannot
be reopened or altered. Original source bytes/hashes never change.

Active affected leases normally block reassignment. Emergency takeover requires:

1. Admin policy `allow_emergency_takeover: true`.
2. Request `emergency_takeover: true` and explicit `takeover_unit_keys`.
3. `confirm_running_work_may_continue: true`, reason and normal version guards.

This revokes **only named affected ownership**, not another host's running
process. Memory cannot terminate already-running work or undo external effects.
Never infer departure from a transient disconnect/expired token; administrator
recovery and account revocation are separate actions. If successors are
unavailable, report a conflict rather than broadening access or discarding them.
`memory_continuity_history` provides admin-only actor/reason/version audit.
Historical successful receipts may replay, but never mutate newer ownership.

## Core integration and remaining boundaries

Core adds `continuity_enabled`, `continuity_capture`, `continuity_source_id` and
`continuity_allowed_paths` under `integrations.memory`. Both enable flags default
false. No actual project configuration was enabled by this implementation.
Apply configuration through the normal Project/Lock workflow, not by changing
an active generation's JSON behind its Lock.

An enabled worker session captures before invocation, periodically while the
Core process lives, and after invocation when its capture thread is idle.
The background thread uses frozen work identity/observations and never touches
the owning SQLite connection. Pending uploads are owner-only durable files;
retries retain the exact idempotency request. Offline capture errors are exposed
as local `capture_gap`, not falsely acknowledged as server saves. A killed Core
cannot save later changes: recovery is limited to the last confirmed checkpoint.
Unsafe/incomplete capture is explicitly `workspace: unavailable` and cannot be
prepared as complete state. Live snapshots are best-effort observations, not
filesystem-atomic transactions or proof of completed work.

Core CLI: `isekai memory continuity` with `inbox`, `status`, `capture`, `inspect`,
`ack`, `claim`, `prepare`, `renew`, `release`. Corresponding local MCP tools are
`isekai_continuity_<operation>` and require the existing conversation activation
and caller authorization. Private claim tokens stay in owner-only local files,
never tool output. Renew/release require the explicit claim generation.

Receiving Core verifies project/recipient/source hashes, the package schema,
classification, exact source Lock, approved logical repository ID, commit and
Memory snapshot sizes/hashes. It reads only already-available local Git objects
with replacement objects, hooks and fsmonitor disabled; no network fetch or
source-provided command is run. Baseline reconstruction is bounded to 10000
files/64 MiB; symlinks/submodules/protected paths are refused. A fresh private
directory is populated, executable bits are preserved without executing them,
then delivery and lease are rechecked. Incomplete preparation stays marked
`incomplete_do_not_execute`; existing working trees are never overwritten.

Successful preparation means **`prepared_requires_local_checks_and_approval`**,
not ready-to-run. Relevant tests, local workflow/approval setup and another
lease check remain user/client responsibilities before any subsequent execution.
Missing/incompatible Locks, unavailable commits, external artifact descriptors,
or source-reported blockers fail closed. M8 supports the locally approved
repository and Memory-stored snapshot path; arbitrary artifact resolvers, source
reconciliation, automatic notifications and unattended continuation remain
separate integration/operational work.

Schema downgrade to 009 refuses once policy/checkpoint/delivery/audit history
exists. With no M8 continuity history, 009 ↔ 010 preserves original records.
See [validation ledger](memory-expansion-progress.md) for tested coverage.
