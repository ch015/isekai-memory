# Current MCP tool catalog

2026-09-23 · schema 020 · 89 tools.

Names and minimum token scopes below are taken from `server/tools.py` and `server/auth.py`.
A scope alone does not grant project access: current membership, owner/author checks, recipient
eligibility and revision/fence guards still apply. Inputs come from each tool inputSchema.

[Project sharing](project-sharing.md) · [Multi-user operation](multiuser-operation.md)

| Tool | Minimum scope | Purpose |
| --- | --- | --- |
| `memory_checkpoint_forget` | admin | Admin: erase checkpoint body/snapshot and revoke dependent deliveries and work claims; immutable audit remains. |
| `memory_checkpoint_list` | read | List own checkpoint metadata, or project-wide metadata for admins. No snapshot bytes. |
| `memory_checkpoint_read` | read | Read a retained checkpoint as its publisher or project admin. No automatic restoration or execution. |
| `memory_checkpoint_save` | write | Save immutable in-progress state under your own identity. Optional bounded snapshot stores explicitly allowed files, never arbitrary archives. |
| `memory_collaboration_events` | read | Read-only durable scoped notifications, separate from list cursors. Encrypted commit-ordered catch-up; reset_required demands a fresh overview. No bodies, hidden counts, acknowledgement or lease mutation. |
| `memory_collaboration_events_prune` | admin | Admin: bounded notification retention cleanup, never erases immutable source audit. Old cursors must fully resync. |
| `memory_collaboration_list` | read | Read-only bounded M8 work, inbox, sent or checkpoint metadata. No bodies, acknowledgement, lease renewal or execution. Live scoped cursor; project-wide scope requires admin. |
| `memory_collaboration_overview` | read | Read-only scoped collaboration counts, authenticated identity and capabilities. Missing idle/usage telemetry is unavailable, never zero. Project-wide scope requires admin; allowed tools are scope-level hints, not resource approval. |
| `memory_continuity_ack` | write | Assigned recipient: idempotently acknowledge only your delivery; not work completion. |
| `memory_continuity_claim` | write | Acquire one token-fenced work unit. All recipients may read context; only eligible assignees can own this unit. |
| `memory_continuity_history` | admin | Admin: bounded project continuity audit metadata and versioned policy/assignment decisions, not checkpoint bodies. |
| `memory_continuity_inbox` | read | Read your independent recipient deliveries. One user's ack never consumes another's; live cursor, not notification feed. |
| `memory_continuity_members` | admin | Admin: list bounded eligible project identities, never credentials or token hashes. |
| `memory_continuity_policy_get` | read | Read project continuity policy and revision. Disabled or absent policy never grants capture authority. |
| `memory_continuity_policy_set` | admin | Project admin: replace version-fenced continuity policy, sender 1:N rules, checkpoints and recovery limits. No execution approval. |
| `memory_continuity_publish` | write | Create atomic independent deliveries and explicitly scoped work units from a checkpoint or admin-promoted legacy handoff. No automatic work split or execution. |
| `memory_continuity_read` | read | Assigned recipient: read pinned shared context without taking a work lease. Admins do not impersonate recipients. |
| `memory_continuity_reassign` | admin | Admin: atomically replace recipients/work assignments with version/generation guards and audit. Optional emergency takeover requires enabled policy and explicit confirmation. |
| `memory_continuity_release` | write | Release an active work lease or report completion with independent immutable receipt. Reported completion is not verified execution. |
| `memory_continuity_renew` | write | Renew only an active work claim to an absolute bounded deadline, without extending retention. |
| `memory_continuity_status` | read | Publisher/recipient/admin: metadata, per-recipient intake and separate work states. Never claim-token hashes or source bytes. |
| `memory_experience_history` | admin | Admin-only family history and target suppression version, including retired and forgotten rows. |
| `memory_experience_list` | admin | Admin-only bounded review queue; metadata_only omits source/content/tags, exact memory_id supports explicit detail. |
| `memory_experience_propose` | write | Propose a pending project experience from an existing handoff. Requires admin review before retrieval. |
| `memory_experience_review` | admin | Admin-only approve/reject/archive/forget with expected version. Forget erases stored plaintext. Retries return original receipts. |
| `memory_experience_revise` | admin | Admin-only immutable correction proposal. Approval atomically replaces its active parent at the captured version. |
| `memory_experience_suppression_release` | admin | Admin-only version-guarded release of a suppressed claim; never reactivates an old memory. |
| `memory_feedback_list` | admin | Admin-only bounded project feedback records. Counts are not success, truth, trust or approval. |
| `memory_feedback_record` | write | Write one explicit immutable actor/asset-version observation. Reported outcomes require same-project handoff evidence; never updates ranking or approval. |
| `memory_generation_enqueue` | admin | Admin-only: enqueue a bounded source scan or an approved-reference summary. Never runs a model. |
| `memory_generation_list` | admin | Admin-only durable job status, source watermarks and dead letters; no lease credentials. |
| `memory_generation_retry` | admin | Admin-only version-fenced dead-letter redrive. Adds at most three attempts, lifetime limit 30. |
| `memory_grant_create` | admin | Owner admin: grant one exact fresh asset version to one consumer project for reference-only reads. |
| `memory_grant_list` | admin | Owner admin: bounded grant metadata, including revoked/expired entries; no asset bodies. |
| `memory_grant_revoke` | admin | Owner admin: permanently revoke a version-fenced grant. Cannot erase copies already delivered. |
| `memory_handoff_ack` | write | Idempotently acknowledge successful processing of an active claim generation. |
| `memory_handoff_claim` | write | Acquire or replay a recoverable token-bound lease. Version-2 delivery requires accept_handoff_version=2 and the assigned recipient. |
| `memory_handoff_get_claimed` | write | Recover an active handoff claim response using its client-held token. |
| `memory_handoff_inbox` | read | Read a bounded live inbox: available (including expired leases), my active claims, or sent handoffs. No claim or automatic resume. |
| `memory_handoff_list` | read | List non-expired pending version-1 handoffs. Use inbox for addressed or continuation handoffs. |
| `memory_handoff_nack` | write | Idempotently release an active claim generation using a bounded reason code. |
| `memory_handoff_pull` | write | Atomically claim a handoff using the compatibility one-shot operation. |
| `memory_handoff_push` | write | Register an immutable Core Task/Result handoff; optional recipient/continuation opts into version-2 delivery. |
| `memory_handoff_renew` | write | Extend an active owned lease to an absolute deadline. Retry the same deadline; never revives an expired lease or extends retention. |
| `memory_handoff_status` | read | Read project handoff delivery metadata without consuming it; acknowledgement is not task completion. |
| `memory_knowledge_delete` | admin | Admin: erase current snapshot prose, preserve revision receipts and invalidate old grants. |
| `memory_knowledge_list` | admin | Admin: bounded source inventory metadata; includes expired/deleted entries, never content. |
| `memory_knowledge_read` | read | Read current unexpired pushed knowledge as untrusted reference data, not verified live upstream state. |
| `memory_knowledge_sync` | admin | Admin: explicitly publish a bounded pushed Wiki snapshot. No network fetch; freshness is publisher-reported with at most seven-day validity. |
| `memory_presence_end` | write | End your session using its private token and next sequence. Ended or retired sessions cannot be revived by late reports. |
| `memory_presence_heartbeat` | write | Report current observed work state with monotonic transport/state sequences. Never renews work leases. Do not replay offline heartbeat history. |
| `memory_presence_list` | read | Read bounded authorized session metadata and derived idle/freshness. Project scope is admin-only. No session token hashes. |
| `memory_presence_policy_get` | read | Read versioned observation policy. Missing policy disables collection, not authentication. |
| `memory_presence_policy_set` | admin | Admin: replace presence policy with version, reason and idempotent receipt. Does not activate any client or change work ownership. |
| `memory_presence_prune` | admin | Admin: retire expired observation metadata in bounded batches. Keeps minimal anti-replay tombstones; never changes work leases or ownership. |
| `memory_presence_register` | write | Register your explicitly enabled Core observer. Stable instance plus private session token makes retries non-refreshing. Not proof of human presence. |
| `memory_presence_users` | read | Read user aggregates from the complete authorized open-session set, not from a single sessions page. Idle is observed Core inactivity, not human absence. |
| `memory_project_assign` | write | Owner assigns or removes directory access. Token scopes still limit allowed work operations. |
| `memory_project_get` | read | Get one accessible project's clone metadata and pinned setup manifest. |
| `memory_project_list` | read | List projects owned by or assigned to this authenticated actor. Project tokens remain limited to their project. |
| `memory_project_record_list` | read | Search or page active records of this project only. Always returns authors and source citations; no implicit approval. |
| `memory_project_record_put` | write | Share one immutable member record, idempotent by ID and authenticated author. Reference data, not workflow authority. |
| `memory_project_record_remove` | write | Author or project owner: erase a record's content and remove it from search; preserve its idempotency tombstone. |
| `memory_project_register` | write | Register a project or replace its metadata with an exact revision guard. Does not create a Git repository. |
| `memory_read` | read | Read one approved, unexpired project experience as reference data with source attribution. |
| `memory_repo_check_updates` | read | Check registered repositories for newer artifact releases. Returns a summary of available updates per repository. The user decides whether to apply each update. |
| `memory_repo_list` | read | List registered artifact repositories. Each entry includes the repository URL, tracked artifact kinds, and the latest known release version. |
| `memory_search` | read | Search approved, unexpired project experiences. Returns reference excerpts and provenance; never consumes a handoff. |
| `memory_shared_read` | read | Consumer project: recheck exact grant and live asset on every read. No export, transitive sharing or cache authority. |
| `memory_skill_export` | admin | Admin-only explicit deterministic unsigned native Skill archive; active review version and exact source Lock required. |
| `memory_skill_generate` | admin | Admin-only: queue a reference-only scaffold from approved successful procedures; manual revision required before approval. |
| `memory_skill_import` | admin | Admin: validate a deterministic M5 native archive into quarantine only. Unsigned provenance is a claim, not trust or installation. |
| `memory_skill_import_forget` | admin | Admin: erase quarantined body/resources/source claims while retaining conflict and erasure receipts. |
| `memory_skill_import_inspect` | admin | Admin-only quarantine inspection; source claims are not locally approved evidence. |
| `memory_skill_import_list` | admin | Admin-only bounded quarantine/erasure metadata inventory; no imported bodies or source claims. |
| `memory_skill_inspect` | admin | Admin-only draft inspection, review events and source freshness; forgotten bodies remain erased. |
| `memory_skill_list` | admin | Admin-only bounded review/history metadata; no instruction bodies. |
| `memory_skill_propose` | write | Propose a pending native Skill from exact approved experience versions. Never installs or executes. |
| `memory_skill_read` | read | Read one active fresh reviewed Skill as data; this does not authorize installation or execution. |
| `memory_skill_review` | admin | Admin-only version-fenced approve/reject/archive/forget. Generated scaffolds must first be manually revised. |
| `memory_skill_revise` | admin | Admin-only complete immutable revision, fenced by latest revision number. Never overwrites content. |
| `memory_summary_read` | read | Read a fresh project/phase snapshot of approved references; stale snapshots return no text. Never generates. |
| `memory_usage_list` | read | Bounded scoped usage metadata and latest counters, never private reporter tokens or source text. |
| `memory_usage_policy_get` | read | Read separate opt-in usage collection, retention and soft-alert policy. |
| `memory_usage_policy_set` | admin | Admin: versioned full usage policy replacement with reason and receipt. Never starts observers or stops work. |
| `memory_usage_prune` | admin | Admin: retire bounded expired usage rows, scrub metrics and preserve bounded anti-replay identities. Does not touch work or presence. |
| `memory_usage_register` | write | Register your private reporter for one exclusive run attempt, independently of presence. Run rollups and external parent conversations are unsupported. |
| `memory_usage_report` | write | Report one absolute run counter revision. Exact receipt retries do not double count; does not heartbeat or renew leases. |
| `memory_usage_summary` | read | Whole authorized retained set, separate reported/estimated/null totals and stable soft-alert identities. Not a billing or account quota API. |
