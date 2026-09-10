# Core latest-remote reconciliation — 2026-09-10

## Outcome

At the end of reconciliation, the actual sibling `isekai-core` checkout had
`master`, `origin/master` and `upstream/master` at
**`3fb6480182f96169536930d994e1dff83af66ce2`**. The Memory experience-recall changes
were reviewed and reapplied on that base, with updated regression tests. They
remained staged and uncommitted at that point; reconciliation performed no push
or global installation.

Subsequent user-authorized publication committed the ten scoped files as
**`f4dfa11cab66723fbbf986dc9755eb31b322085e`** and pushed that commit to both
`to-nexus/isekai-core` and `dotwin7/isekai-core` on `master`. Both remote tips
were verified. The pre-existing `.isekai/state.db` change was excluded, and its
file bytes and staged blob remained unchanged.

The original checkout was at `c0e0acedb104aa16b8d94beb950d187023e1acb2`, ten
commits behind. Both remotes were fetched and agreed on the target above; they
were fetched again immediately before applying the validated update.

## Why the local changes were still needed

Latest upstream did not contain `experience_recall`, the bounded `memory_search`
client path, or Memory reference/citation injection into Context. Those remain
the M3 opt-in integration and cannot simply be discarded during an update.

However, upstream changed the surrounding contracts:

| Latest upstream change | Reconciliation |
| --- | --- |
| Preflight repository observations and phase evidence in Context | Preserve collection and all `evidence_citations`; add separate optional Memory citations and hashes |
| Result evidence binds local observations | Preserve `phase_evidence_refs` and Result evidence references; Memory claims do not become execution evidence |
| Inbox lease owner/generation/deadline fencing | Preserve upstream implementation unchanged; add recall methods without restoring old mutation calls |
| Explicit per-Unit preset selection and `units` plans | Update old tests that relied on implicit defaults; verify explicit Unit selection, pinned Lock and preview recall |
| New CLI-only installation, review APIs and packaging resources | Keep the complete upstream update; verify the new wheel's bootstrap resources and packaged schema |

Three-way comparison identified four conflict regions in `context_service.py`
and one in `execution/service.py`. They were resolved by retaining both the
upstream observation/evidence flow and the separate Memory reference flow.
Other scoped files merged without textual conflicts.

The upstream removal of the legacy `src/isekai/infrastructure/global_store.py`
was also retained as part of the fast-forward, not reimplemented or restored.
Its prior contents remain recoverable from Git history and the original archive.

## Validation

| Check | Result |
| --- | --- |
| Clean latest upstream, isolated interpreter | 303 unit tests passed; one process-table check skipped by sandbox |
| Latest + adapted changes, isolated interpreter | 332 unit tests passed; the same single sandbox skip |
| Actual updated Core checkout, process checks allowed | **333 unit tests passed, no skips** |
| Recall-specific tests | 29 passed; preflight evidence/recall coexistence, offline execution and explicit Unit preview covered |
| Normal Core conformance | 20 schemas loaded, **44 fixtures passed**, zero fixture failures |
| Changed Core modules/tests lint and staged/unstaged whitespace | Passed |
| Core wheel build and isolated wheel import | Passed; recall, packaged project schema, disabled default and bootstrap sources verified |
| Current Memory HTTP/stdio and separate worker E2E | Passed, schema `008`, 43 tools |
| Actual latest Core client → Memory recall | Passed; citations, budget, cross-project denial and retirement without cached reuse |
| Latest Core native Skill verifier | Accepted reviewed export, rejected modified bytes; nothing installed |

One unrelated limitation remains: optional conformance
`--require-schema-coverage` fails because ten schema types have no fixtures in
this repository. The **same result was reproduced on untouched latest upstream**:
foundation, hub, knowledge-pack, methodology-binding, methodology-profile, preset,
preset-policy, skill, source-manifest and twin. All 44 existing fixtures pass.
This task did not add unrelated fixtures or claim that optional coverage is green.

The first temporary-tree test runs used the original editable environment plus
`PYTHONPATH`. Kiro's isolated subprocess intentionally strips that variable, so it
loaded the old checkout's process module and failed to import
`terminate_process_tree`. Separate interpreters with explicit source/dependency
paths eliminated that mixed-version artifact. The final actual-checkout run also
passed those tests. These initial failures were not fixed by changing Kiro code.

## Preservation and recovery

The original `.isekai/state.db` was neither reset nor migrated. Its working-file
bytes and staged Git blob remained identical before/after the update and tests:

- File SHA-256: `5a61f81946bd5871e5cdec2f56c0e6ceebd206ffa9036675fcbadc590515757c`
- Staged Git blob: `21d151d59bbfb3eb37b7d68d77cd2a919599148b`

Backup directory on this workstation:
`/private/tmp/isekai-core-latest-review.h1sIiW/backup/`

It contains the original index, state DB copy, full/code-only staged patches,
original base archive and untouched latest archive. It is inside a private
temporary directory; retain or securely relocate it if longer-lived recovery is
needed.

An additional Git stash is intentionally retained:

- Commit: `d2ed8d9d93510ca520582155fb57dc84e0a002aa`
- Message: `memory-recall-before-latest-3fb6480-20260910`

Only the specified code paths were removed from the working tree during the
stash operation; the live DB stayed in place and staged. Git's stash/index
snapshot also contains the pre-existing DB delta. **Do not blindly pop/apply the
old stash onto the latest tree**: it is a recovery/inspection copy of the old
base and can reintroduce conflicts. Compare or recover selected files explicitly.

After the fast-forward, the validated patch was applied and the same ten code,
schema, documentation and test paths were staged again. The pre-existing DB
change remained staged separately. During reconciliation itself, no branch
commit was created and neither remote was pushed; subsequent publication is
recorded above. No real Project was started, no actual application DB was
migrated, and no recall/provider setting was enabled. All Memory database tests
used a task-specific disposable PostgreSQL container.
