# M6: explicit team reference assets

This is a **local baseline**, using schema `008` and 14 additional tools (43
total). Nothing automatically crawls a Wiki, queries a code graph, clones/pushes
Git, installs a Skill, changes rankings or enables Core recall. Existing
`memory_search`, `memory_read`, Skill approval and handoff contracts are unchanged.

## Patterns absorbed and boundaries

| Tencent pattern | Implemented adaptation | Deliberately separate |
| --- | --- | --- |
| Wiki/CodeGraph entities | `pushed_wiki_v1`: explicit bounded Wiki snapshot adapter | Network connectors, code graphs, upstream credentials and live change feeds |
| Asset ACLs/team bindings | Owner-issued exact-version consumer-project grants with revocation | Wildcards, organization-wide defaults, transitive grants and shared search |
| Git learning exchange / versioned Skills | M5 deterministic native archives imported into quarantine | Git transport, signed releases, installation and imported-source approval |
| Usefulness signals | Explicit immutable actor/asset-version feedback, with reported outcome evidence | Implicit read counts, automatic rank boosts and claims of causal success |

The local references are TencentDB-Agent-Memory's `gateway/knowledge-schemas.ts`
and existing Skill asset/binding design, and teamai-cli's project-local Git learning
and recall separation. No vendor code or prompts were copied.

## Authority and sharing

Every request still uses `project_id` matching its token project. Owner-admin
tools are `memory_grant_create`, `memory_grant_revoke`, `memory_grant_list`.
Only the new `memory_shared_read` crosses a project boundary: its `project_id`
is the **consumer**, and `grant_id`/`grant_version` identify owner permission.

Create arguments include `asset_kind` (`experience`, `skill`, `knowledge`),
`asset_id`, `asset_version`, `consumer_project_id`, explicit `max_classification`,
`expires_at` and `idempotency_key`. Skill IDs here mean **revision UUIDs**, not
Skill identity UUIDs. Knowledge IDs mean document UUIDs. The version is the
asset's lifecycle version, not the Skill revision number or upstream revision.
Grant expiry must be in the next 30 days. No grants exist by default.

```json
{
  "project_id": "consumer-project",
  "grant_id": "00000000-0000-4000-8000-000000000001",
  "grant_version": 1,
  "max_classification": "internal"
}
```

Use a real owner-issued grant UUID in this `memory_shared_read` request. The
server verifies the consumer, exact grant version, expiry, classification, live
asset status/version and captured digest. Experience and Skill sources must
still match their retained handoff attribution. Skill source freshness and any
requested Lock also apply. Wiki snapshots cannot satisfy a Core Lock filter.

Reads serialize with owner lifecycle mutations and re-read under READ COMMITTED
after acquiring the owner lock. A read already in progress can complete before
a concurrent revocation; a read after completed revocation cannot use an old
snapshot. Revocation is permanent (`version: 1 → 2`), actor-replayable and never
reactivated by create retries. Grant metadata retains the original receipt;
an idempotent create result is **not** proof that a grant remains active.

Returned content is `reference_only`, not installation/execution authority.
No asset is copied into the consumer's experience/Skill store, no raw handoff
envelopes or review events are returned, and grants cannot be used to regrant,
export or propose against foreign source UUIDs. Retiring/updating a source makes
an exact old grant unusable without rewriting the grant record.

There is no server-side content cache. HTTP MCP/REST tool responses carry
`Cache-Control: no-store`; shared reads also return `cache_policy: no_store`.
Consumers must not treat previously delivered bytes as current authorization.
Revocation **cannot erase content already seen, downloaded, logged or copied by
a recipient**. No remote-erasure guarantee is made. Tokens continue to authorize
the whole project; classification ceilings are output filters, not token clearance.

## Pushed Wiki snapshot adapter

`memory_knowledge_sync` is an explicit admin publication of reference data, not
an experience or Skill approval. Required fields:

| Field | Contract |
| --- | --- |
| `provider` | Exactly `pushed_wiki_v1`; no URL/path/credential arguments |
| `source_key`, `source_revision` | Opaque nonblank strings, at most 128 characters |
| `expected_version` | `0` for first publication, otherwise current document lifecycle version |
| `classification` | Explicit; never lower than the previous document classification |
| `title`, `content` | NFC + trimmed; 200 / 8192 characters maximum |
| `content_digest` | `sha256:` of UTF-8 canonical JSON `{title,content}` after normalization |
| `valid_until` | Explicit future timestamp, at most seven days from server time |

Canonical JSON uses sorted keys, compact separators, unescaped Unicode and no
non-finite numbers. Digest calculation matches `retrieval.citations.canonical`
and `digest`. Successful sync returns `document_id` and the next integer `version`.
Snapshots are supplied by an authorized publisher; **the server has not checked
the Wiki's current upstream revision**. Reads label freshness `publisher_reported`
and `provider_revision_verified: false`. Silence/outage is handled by expiry,
not unlimited cached freshness. Publishers must send new snapshots or deletions
when upstream changes. There is no network call or implicit provider enrollment.

Each source revision can be published once per document. Exact same-actor
retries return the historical receipt; changing content under a used upstream
revision conflicts. Renewing validity requires a new source revision. Concurrent
edits use current-version CAS. Replacing a snapshot overwrites its old prose;
events retain actor, request digest, upstream revision and version, not old text.

`memory_knowledge_read` (read scope) returns only active, unexpired documents,
with optional exact `expected_version` and classification ceiling. These
documents are not added to experience search, summaries or Skill sources.
`memory_knowledge_list` (admin) is a bounded cursor inventory without prose.
`memory_knowledge_delete` (admin, document UUID + expected version) erases title
and content and records a deletion event. Publishing a new upstream revision
after deletion is explicit and allowed; old revisions/grants never revive.
Opaque source keys/revision labels, digests and audit metadata are retained, so
publishers must not put secrets or document prose in identity fields.

## Offline native Skill / Git exchange

M5 `memory_skill_export` produces deterministic unsigned `.tar.gz` bytes. An
authorized operator may separately put the archive and its three digest values
in a reviewed Git change/release. This service does **not** clone, fetch, commit,
push or install anything. Existing release tooling continues to own transport.

Destination-admin `memory_skill_import` takes `archive_base64`, `archive_digest`,
`manifest_digest`, `artifact_digest`, explicit `classification` and an
`idempotency_key`. The destination classification cannot be below the archive's
declared source/Skill floor. This is an **explicit transfer/copy**, not a revocable
grant. The importer is responsible for authorization to transfer the bytes.

Validation accepts only the exact deterministic M5 export profile:

- At most 256 KiB compressed and aggregate file content, 320 KiB decompressed
  tar including padding/headers, and eight regular non-executable members.
- Strict base64 and JSON; duplicate JSON keys, non-finite values, invalid source
  shapes, unsafe resources, unknown members, symlinks, duplicate members,
  altered modes/instructions, decompression bombs and inconsistent bindings fail.
- No filesystem extraction. The server rebuilds the entire canonical native tar
  from validated body/source claims and compares tar bytes, manifest and artifact
  digests. The transport digest is checked against the actual compressed bytes.
  Different gzip encoders/compression levels are supported; a different tar
  profile is not accepted. This keeps compression separate from artifact identity.
- Source watermark, content digest, same-project/same-Lock bindings and class
  inheritance must be internally consistent. Foreign source IDs are never fetched
  or treated as locally approved evidence.

The only successful state is **quarantined**, with `trusted: false` and
`usage: review_only`. Manifest provenance and approval timestamps remain
unverified **claims**. Digests establish internal integrity, not authorship,
truth, signature verification or an execution capability.

The conflict key hashes the claimed source repository, native manifest identity
and version. Any new receipt for an already used identity conflicts (including
identical bytes); the original same-actor idempotency key replays. A changed
archive cannot silently overwrite a prior claim. This namespace is not a signed
global identity registry.

`memory_skill_import_list` provides a bounded admin quarantine/erasure inventory
without bodies or source claims. `memory_skill_import_inspect` is admin-only and classification-filtered; there
is no ordinary imported Skill read, automatic promotion or install. To adopt
an idea, an authorized author must create a **new local Skill proposal**, manually
bind approved local experience versions, author/review it under M5, and separately
follow Core's artifact/install policy. Remote source claims cannot satisfy that
gate. No automatic copy/rebind API is provided.

`memory_skill_import_forget` erases body, resources, manifest and source claims,
retaining digests, hashed origin identity, classification and conflict/erasure
receipts. Replaying the import does not restore erased data. A new receipt with
the same identity conflicts. An independent imported copy is not automatically
erased when its origin source is forgotten or a grant is revoked: destination
retention must be handled explicitly. This differs from M5's local source erasure.

## Explicit feedback

`memory_feedback_record` (write scope) requires an exact asset kind/UUID/version,
`usefulness` (`helpful`, `not_helpful`, `uncertain`), `outcome` (`not_attempted`,
`succeeded`, `failed`) and `idempotency_key`. Shared targets additionally require
the exact consumer grant UUID/version and live authorization. Local targets must
be live and readable in the writer's project. No user-supplied actor, counters,
weights, arbitrary text, evidence URLs or rank fields are accepted.

There is one immutable observation per authenticated actor/asset version in a
project; additional keys cannot stuff that actor's ballot. Exact receipt replay
returns only the receipt even after retirement/revocation, not asset content.
Success/failure needs a same-project handoff with matching reported result status
and non-empty evidence references; its payload digest is captured. `not_attempted`
has no handoff. This binds a **reported** result, not proof that the asset was used,
caused success, or that evidence was independently verified. Multiple authorized
actors are not assumed independent or Sybil-resistant.

`memory_feedback_list` is admin-only, bounded and scoped to the reporting project.
Consumer observations are not automatically disclosed to an asset owner. Reads,
downloads, feedback counts and reported outcomes never modify ranking, approval,
generation recipes, handoff delivery or source lifecycle. Feedback stores no
copied source prose; audit identifiers/digests survive source erasure.

## Operations and migration

All lists default to 10 rows, maximum 20, with project/view-bound keyset cursors.
DB operations have a five-second overall budget and four-second SQL timeout;
mutations serialize on the existing project lock, with sorted owner/consumer
locks for shared feedback. All new mutations require explicit tool calls.

`alembic upgrade head` adds five tables, including the Wiki event table, in revision
`008` without rewriting M1–M5 data. Empty M6 tables can roll back to `007`;
any grant, knowledge, import or feedback history causes atomic downgrade refusal,
even if already revoked/deleted/forgotten. Do not use downgrade as data erasure.
Test against a disposable DB; deployment migration remains an operator action.
Erasure here describes current logical rows, not a rewrite of database backups,
WAL or recipient copies; those retention policies remain operator responsibilities.

Acceptance evidence and remaining production extensions are recorded in
[the progress ledger](memory-expansion-progress.md). No Core code changes or
project opt-ins are required for this baseline.
