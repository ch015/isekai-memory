# M5: reviewed native Skill assets

Memory owns drafts, immutable revisions, review receipts
and explicit export. Core owns installation, capability policy and execution.
This is ISEKAI's native `kind: skill` format, not a Codex `SKILL.md` package.

## Trust and source boundary

Each draft binds 1–8 active, approved experience IDs at exact lifecycle versions.
Sources must belong to one project and one Lock, have retained, matching handoff
digests and come from successful work with evidence references. At least one source
must be a `procedure`; other approved kinds can provide context. Source integrity
and approval do not prove procedure correctness. Classification inherits the maximum
source classification and cannot decrease across a Skill's revisions.

The offline generator reuses M4 leases, retry budgets and atomic completion. It
creates a **scaffold**, with references rather than copying source prose into
instructions. A generated scaffold cannot be approved: an admin must first create
a manual revision containing concrete triggers, source-linked steps and validation
criteria. There is no model call or automatic install/execute path.
Simply changing the scaffold title or relabeling an unchanged scaffold as manual
is rejected. Semantic correctness is still an admin responsibility, not something
the schema validator establishes. The recipe is
`local_structured/skill-scaffold-v1/no-prompt`, with M4's pinned/current character
limits, finite worker, zero monetary cost, leases and attempt limits.

This adapts Tencent SkillCore's separate identity/version/resource bindings and
version-fenced writes to ISEKAI's reviewed, project/Lock-scoped artifact contract.
It does not copy Tencent code, prompts or its runtime. The baseline performs
explicit source selection/eligibility checks, not semantic candidate mining.

## Tools and bounded workflow

| Tool | Scope | Contract |
| --- | --- | --- |
| `memory_skill_generate` | admin | Queue a scaffold from exact `sources`; no synchronous generation |
| `memory_skill_propose` | write | New named authored candidate with `idempotency_key`, `sources`, `body` |
| `memory_skill_revise` | admin | Complete body/sources plus `skill_id`, `expected_revision`, new key |
| `memory_skill_review` | admin | `revision_id`, `expected_version`, action approve/reject/archive/forget |
| `memory_skill_list` | admin | Review metadata; optional `skill_id` selects revision history |
| `memory_skill_inspect` | admin | One revision's body, source evidence/freshness and event receipts |
| `memory_skill_read` | read | One active fresh revision with optional classification/Lock filters |
| `memory_skill_export` | admin | Exact active review version and Lock, plus optional classification ceiling |

Every operation requires the token's `project_id`. Actor identity is server-owned;
classification ceilings filter output but are not additional token clearances.
No cross-project sharing is implied. `memory_search` still searches experiences,
not Skill instructions. No new Core automatic recall, install or execution hook
is introduced.

Each source is `{"memory_id":"<UUID>","version":2}`. The version must be the
experience's current approved lifecycle version, not a guessed revision number.
Handoff delivery expiry/ack state is independent; eligibility checks reported
success and nonempty evidence references, but do not fetch or verify those external
evidence objects. Failed-work sources are excluded in this baseline.

Example authored body (replace the UUID with an actual declared source):

```json
{
  "title": "Receipt-aware retry",
  "description": "Check durable receipts after a lost response.",
  "triggers": ["A response was lost and the original request ID is known."],
  "steps": [{
    "instruction": "Compare the retained receipt with the original request ID.",
    "sources": ["00000000-0000-4000-8000-000000000001"]
  }],
  "validation": ["The IDs match and no duplicate work was created."],
  "resources": [{"name": "checklist", "content": "Record both IDs for review."}]
}
```

Names/resource names are ASCII lowercase hyphen-separated identifiers, max 64
characters. Body strings are NFC-normalized and trimmed. Limits: title 200,
description 512; 1–8 triggers of 256 characters; 1–12 steps of 1024 characters,
each referencing 1–8 declared sources; 1–8 validation criteria of 512 characters;
0–4 text resources of 4096 characters each. The complete canonical body is capped
at 24000 characters. No caller-supplied path, URL fetch, executable mode or command
runner is accepted. Paths are generated as `resources/<name>.txt`.

Listing defaults to pending, limit 10 (max 20). With `skill_id` and no status it
returns all revision statuses for that Skill; `cursor` is bound to project/view.
Listing is metadata only; inspection returns review events and available source
evidence explicitly as review data. Read/export have a three-second total and
two-second per-statement SQL budget. Export payload and compressed archive are
each capped at 256 KiB; base64 expansion is additional transport overhead.

## Lifecycle

Skill identity is a project-local name and UUID. Each immutable content revision
has its own UUID, revision number and review version. Revision creation compares
the latest revision number; approval compares the captured active revision. Only
one revision can be active. Review actions approve/reject/archive/forget use exact
review versions and durable actor-bound receipts. Submission keys survive retirement
and forgetting. Source changes fence approval and export; a forgotten experience
erases every dependent revision's body/resources in the same DB transaction.

Reads and exports revalidate all dependencies and validity intervals. Stale,
retired or pending instructions cannot enter ordinary retrieval. Admin inspection
is separate; history retains IDs, digests and event metadata, not forgotten text.
New revisions require a complete body and fresh source bindings. Prior downloads
and backups remain outside server-side erasure and revocation.

`skill_id` identifies a logical asset. `revision_id` identifies immutable content;
`revision` increases on each new proposal, including rejected/generated drafts.
`version` increases on review, supersession and source-triggered invalidation.
An admin passes `expected_revision` when authoring and `expected_version` when
reviewing/exporting. A proposal binds the active revision at creation; if another
proposal wins approval first, the losing proposal cannot overwrite it. Create a
fresh revision against the current state instead. Same-actor review retries return
the original transition receipt, even if the revision has subsequently retired.

Classification is a monotonic asset floor including prior proposals: removing a
high-classification source from a later revision does not downgrade the Skill.
Source status/version changes mark pending/active dependents stale via a DB trigger;
source forgetting erases **all** dependent revisions, including archived, rejected
and superseded ones. Events record `source-lifecycle` and the causing experience ID.
Source content/digest drift and time-based expiry are additionally checked on every
approval/read/export even when no lifecycle trigger ran. Admin metadata may still
show `active` for a time-expired source, but `fresh: false` inspection and normal
read/export rejection remain authoritative. There is no automatic reactivation.

Forgetting a Skill revision itself erases that revision's body/resources, not its
independent source experiences or other revisions. Source forgetting is the
cross-revision erasure operation. Identifiers, digests, bindings, names and receipts
remain for audit/deduplication; this is not a full personal-data purge policy.

## Export

Only an explicitly requested, currently active reviewed revision can be exported.
The caller supplies its review version and exact Lock; classification is filtered
before bytes are built. Files are fixed or server-named text resources, never
arbitrary paths, fetched URLs, executable helpers, links or executable archive members.
Exports are deterministic unsigned gzip/tar native Skill packages, with per-file,
manifest and archive digests. They contain source bindings, not source prose.
They grant no capabilities. Structural acceptance by Core's existing verifier is
required; signatures, release policy, local installation and execution are separate.
The fixed files are `manifest.json`, `instructions.md`, `draft.json` and
`source-bindings.json`, plus optional text resources. Only `instructions.md` is
manifest-marked instruction; every tar member has non-executable mode `0644`.
Source titles/bodies are not automatically copied. Manually authored body/resource
text can contain whatever the reviewer approved; no sanitization or semantic
safety guarantee is claimed for it.

The artifact ID is server-assigned `memory-<skill UUID without hyphens>`, avoiding
cross-project name collisions. Version `<revision>.0.0`, approval timestamp,
canonical JSON, sorted file records and zero tar/gzip timestamps make repeated
exports deterministic in the same packaging toolchain. The response separates
`archive_digest`, `manifest_digest`, and `artifact_digest`; no database export cache
retains plaintext. Export does not count as publication or usefulness feedback.

Native manifests use instruction mode, no granted/requested capabilities, a
conservative high risk label, developer role and a `human-review` check identifier.
Those declarations are not an executable checker or an installation authorization.
Production release tooling must supply appropriate signatures/evidence and any
required project-specific bindings. Already downloaded bytes cannot be remotely
revoked when a source is subsequently retired.

The source locator identifies a Memory revision. The manifest's `resolved_commit`
is the immutable revision's hexadecimal content digest (a content-addressed Memory
revision, **not a fabricated Git commit**). Timestamps are pinned to approval.

Migration `007` is additive and refuses downgrade once Skill revisions or Skill
generation jobs exist. No real deployment database is migrated during development.

## Validation

The suite includes schema/resource-path bounds, concurrent proposal/review,
classification floor, Lock/project isolation, source expiry/drift/forgetting,
immutable DB content/bindings, job rollback/stale leases and deterministic exports.
`skills_e2e_smoke.py` runs actual HTTP and a separate worker process. With explicit
`MEMORY_CORE_PYTHON` and `MEMORY_CORE_SOURCE`, the runner passes the exported archive
to unchanged Core `ArtifactArchive`/`ArtifactVerifier`, then confirms that content
tampering is rejected. It only extracts to a temporary directory, never installs.

`migration_skills_e2e_smoke.py` requires an explicitly selected empty disposable
DB; it verifies populated `006 ↔ 007` preservation and transactional rollback refusal
after Skill history exists. Measured results are in the
[work ledger](memory-expansion-progress.md).
