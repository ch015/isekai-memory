# M3 — Evaluated retrieval and opt-in Core references

M1/M2 lifecycle remains authoritative; schema `005`
and the existing 17 tools are retained. No embedding service or LLM is contacted.

## Provider boundary

`retrieval/contracts.py` defines a scope-bound request and ID/score candidates.
PostgreSQL lexical providers apply project, lifecycle, validity, classification,
kind and source Lock filters before ranking and limiting. The service hydrates
candidate IDs from PostgreSQL with those filters again in the same read snapshot.
Providers never supply authoritative content or citations. No shared result cache
is introduced. Future external providers must also support pre-filtered candidates.

`postgres_lexical` preserves the M2 baseline. `postgres_weighted_lexical` is a
separate evaluation candidate with title/tag/body weighting, not vector or hybrid
search. Server configuration selects the provider; callers cannot change it.
The baseline remains the default until measured results justify a rollout.
SQL has a 2-second statement budget and the whole retrieval has a 2.5-second
budget, including waiting for a pool connection. Failure is a controlled error,
never an unmarked empty success response.

## Citations and budgets

Search retains all existing fields and adds project/source-payload provenance and
`citation`. Citation schema 1 binds project, memory ID, lifecycle version, kind,
title, classification, source handoff/Lock/payload digests, full content digest and
excerpt digest. Digests use SHA-256 over UTF-8, with sorted-key compact JSON for
objects. The full content digest covers `{kind,title,content,tags}`. The binding
digest covers the fields listed in `retrieval/citations.py` plus citation fields
except the binding digest itself. Full read binds its first 512 characters. Search
can shorten that excerpt to fit the budget and recomputes the excerpt/binding
hashes; the full content digest remains identical. With an unshortened excerpt,
the read/search citations match exactly.

These hashes attest to the returned source relationship, not factual truth or
execution authority. An excerpt never becomes Foundation policy or an installed
Skill. Citation bytes count toward `max_chars`; this is serialized JSON character
accounting, not tokens or transport bytes. A small budget may return no item.
Results describe the request's database snapshot; no forever-current guarantee or
cross-request revocation lease is implied.

## Core integration constraints

Experience recall is separately opt-in, independent of handoff inbound/outbound.
The network call belongs before Context assembly, outside lifecycle transactions.
Use the exact pinned source Lock and effective classification ceiling. Receive a
small, validated, citation-bound reference set; recheck project/Lock/classification
locally, enforce a separate reference character budget, and let ContextAssembler
trim optional sections. Citations must be trimmed with their sections.

Unavailable, unsupported or malformed recall yields no experience references and
does not interrupt execution. Existing required-handoff failure rules remain
unchanged. No stale disk cache, credential persistence, automatic extraction or
handoff acknowledgement is added by recall. No configuration is enabled for a
real project as part of implementation.

The Core implementation lives in `isekai-core/src/isekai/memory/recall.py`, with
explicit integration configuration and calls from ExecutionService/Kernel before
ContextService. Core validates the entire batch before accepting any item. The
existing HTTP client narrows recall to a 128-KiB response and a configurable
1–10-second socket timeout (default 3); this is not a hard process-wide deadline.

## Evaluation and rollout decision

Dataset `tests/fixtures/retrieval_v1.json` has 25 hand-authored synthetic candidates
plus a supersession replacement, and 22 Korean/English queries. Judgments are
agent-curated, not independent human labels. Grades are 3 for a direct answer and
1 for related context. Three paraphrase/cross-language queries intentionally
exercise limitations; two no-answer queries require empty results. Pending,
rejected, archived, forgotten, superseded, expired, future, other-project,
other-Lock and excessive-classification rows exercise visibility exclusion.

Reproduce with `MEMORY_TEST_DATABASE_URL=... python -m tests.retrieval_eval` on an
explicit disposable schema `005`. The runner creates unique projects, compares
both providers with identical filters, verifies serialized budgets and unchanged
handoffs, and prints metrics. It neither migrates nor deletes data. Results are
recorded in [retrieval-evaluation-v1.json](retrieval-evaluation-v1.json), including
the fixture digest and per-query ranks.

| Metric | Baseline lexical | Title/tag weighted lexical |
| --- | ---: | ---: |
| Recall@3 | 0.850 | 0.850 |
| nDCG@3 | 0.777 | 0.850 |
| MRR | 0.850 | 0.850 |
| No-answer accuracy | 1.000 | 1.000 |
| Disallowed results | 0 | 0 |

Recall and MRR treat every positive grade as relevant; nDCG distinguishes direct
answers from related logs. Positive-query averages exclude the two no-answer
queries, reported separately. The local single-client run measured about 3.0 ms
baseline and 2.5 ms weighted p95 over 66 calls each. This tiny fixture is not a
production scale, capacity or latency guarantee; timing differences are noisy.

Decision: offer weighted lexical as an opt-in measured improvement but retain the
baseline default. Neither provider solves the three semantic misses. Vector/RRF
integration remains deferred until a real embedding provider can be evaluated
for recall gain, project pre-filtering, latency and cost. No external embedding
service, synthetic vector scores, automatic fallback to wider scope or fabricated
hybrid-quality claim is introduced.
