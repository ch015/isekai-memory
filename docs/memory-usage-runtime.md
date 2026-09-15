# M9 usage ledger and reporter runtime

Implemented locally on 2026-09-14. See [M9 acceptance](memory-m9-acceptance.md)
for the final cross-workstream results. The user clarified that token monitoring
is sufficient: this workstream is frozen, with no cost, billing or budget development.
Optional soft alerts remain off by default.

## Contract and scope

Schema 012 adds usage policies, actor-owned run sessions and immutable revision
receipts without modifying M8/presence tables. Seven tools bring the catalog to
80 at that milestone: memory_usage_policy_get/set, register, report, summary, list and prune.
The current catalog is 82 with schema 013 collaboration events.
The token_usage capability means these APIs exist, not that collection is enabled.

Collection needs both project usage policy enabled and Core's explicit
integrations.memory.usage_enabled=true. Defaults are off. It does not enable
presence, checkpoints, work leases, login or a real project. TUI opening/polling
does not start a reporter.

One authenticated actor, project and execution attempt has one exclusive-run
meter epoch. A private reporter capability proves continuity across retries.
Changing observer or epoch for the same attempt conflicts. Request/turn rollups,
automatic log import and external parent-CLI totals are unsupported. Parent
links may label separate exclusive calls; they are not rollup inputs. Self-reported
numbers are not tamper-proof billing evidence.

Optional work binding requires the exact currently active actor/token/generation,
inherits its classification, and never extends a lease. Late usage after takeover
stays with the original reporting actor. Source erasure hides the link but does
not turn previously consumed tokens into zero. Current Core workers conservatively
report unlinked runs: a local Core unit identifier is not a Memory work UUID.

## Revisions, periods and bounds

- Reports are absolute counters. 100 then 150 means 150, not 250. Same sequence
  and digest returns its original receipt, including old receipts; a changed
  payload conflicts. Metrics/latest row/receipt update atomically.
- Known counters cannot reset/disappear/downgrade within an epoch. Reported data
  replaces an estimate for the same scope; different scopes are not merged.
- Reported/estimated/unavailable remain separate per field. Missing is null,
  actual zero stays zero. Input contains cache subsets; output contains reasoning.
- Today/week use IANA calendar boundaries; custom periods are half-open and at
  most 93 days. Final run totals belong to their end bucket, not prorated hours.
  In-progress attribution is provisional and is atomically replaced on finalization.
  Out-of-window source time falls back to first final receipt time. Finalization
  and exact retries cannot move the bucket again.
- Mine is the authenticated user's own usage; project is project-admin only.
  Classification, user, host, model and work filters apply before counts/groups.
  Entire authorized retained sets are aggregated, never a list page's subtotal.
- Bounded limits: 10,000 retained meters/project, 200,000 total identities and
  200,000 receipts/project; 10 registrations/user/minute, 120 reports/user/minute,
  512 revisions/meter. Summary at most 10,000 runs/1,000 groups, lists 50,
  admin prune 500. Limits fail explicitly; no approximate total is called exact.
- Policy retention is 1–90 days; late acceptance is at most 1–168 hours from
  registration, and a later shorter policy applies too. Prune scrubs numeric/source
  metadata but retains bounded anti-replay identities/receipts. Populated 012
  downgrade is refused rather than deleting history.
- Daily soft alerts use reported totals, stable identities and current policy.
  They are read-only levels, not a durable notification feed or enforcement.
  Custom/filtered summaries do not masquerade as a whole-project daily alert.

## Core collection and recovery

The separate WorkerUsage DTO does not redefine context_usage. Codex stdout/stderr
are captured separately so only structured stdout is parsed; both remain in the
existing evidence path. The parser accepts the documented single fresh
thread/turn JSONL layout at the locally inspected Codex 0.154.0 version.
Input/output, optional cached input and optional reasoning are normalized once.
Raw events, prompts and model/provider guesses are not uploaded.

Unknown schemas/versions, Claude, Kiro and other hosts currently report unsupported.
Truncation, ambiguity and invalid numeric relationships produce explicit missing
reasons. Failed executions can retain reported partial consumption; absent usage
is not zero. This release collects at worker completion, not live token streaming.

Sources checked for the mapping:
[Codex machine-readable output](https://learn.chatgpt.com/docs/non-interactive-mode#make-output-machine-readable)
and [OpenAI usage field inclusion](https://developers.openai.com/api/docs/guides/agents-api/observability#understand-token-usage).
Only local version inspection and synthetic fixtures were run, not an authenticated
subscription execution or billing comparison.

The reporter uses the existing runtime service boundary, never execution importing
Memory or a background thread using Kernel/SQLite. An owner-only outbox holds
at most 128 numeric records of 16 KiB each for seven days. It is bound to endpoint,
organization, project, actor and credential reference. A separate owner-only
local key derives private meter capabilities; project/API bearer credentials and
claim tokens are not persisted in numeric records.

Exact requests survive lost registration/report replies. Successful requests are
scrubbed after a minimal receipt; expired requests are removed with a collection-gap
marker. Fixed lock shards bound lock-file growth. Auth rejection halts automatic
retry; explicit isekai memory sync may retry after rechecking the same actor.
New workers also retry a bounded pending batch. Unknown actor at initial connection
means a visible local collection gap, not later attribution to another account.

Local diagnostics live beneath .isekai/usage; latest-status.json has only state,
attempt ID, timestamp and sanitized error code. Process exit may leave a pending
record, and unobserved/offline activity is never claimed as fully collected.

## TUI and validation

The usage tab shows reported input/output/total, separate estimates, partial/run
counts, period/timezone and explicit unobserved scope. f edits period/group and
user/model/work filters; existing host/classification/scope controls still apply.
d switches between the whole-set summary and paged individual executions. Enter
shows host/version, attempt, field qualities/missing reasons, finalized/bucket times
and revision, without fetching raw CLI output. List totals are never substituted
for the server whole-set summary.

A visible threshold banner is informational only. Repeated reads of the same
server alert ID are not counted as new in the current TUI process. The bounded
10,001-ID in-memory set keeps corrections from repeatedly re-alerting; server IDs
change with period/policy/threshold. It is not a durable read receipt or a cross-device
notification service. Restart or an evicted old ID may display a new indication.
Permission failure clears the screen and this local set. Nothing stops workers.
j in manage mode edits all usage settings using version/CAS, preview, reason,
confirmation and the shared durable pending-request mechanism.

Historical usage-slice validation (final results are in M9 acceptance): Memory full PostgreSQL suite (633 tests before two additional ownership/
rate tests); those 12 usage DB tests then passed. Core full suite 703 passed plus
one sandbox process-table skip, with later focused parser/reporter/read/boundary
suite 59 passed. Real HTTP/stdio and TUI passed with 80 tools, including lost policy
reply and parser→outbox→HTTP reply-loss recovery: own 60/project 180, no double count.
The 011↔012 empty-usage migration preserved populated M8/presence records; a
populated usage downgrade was refused without changing their data.
