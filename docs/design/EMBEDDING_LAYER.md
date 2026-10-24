# Embedding layer: decisions and tradeoffs

| Record field | Value |
| --- | --- |
| Status | Implementation started: configuration, embedding adapter, local tokenizer loader, and explicit compatibility probe |
| Last updated | 2026-10-24 |
| Pending verification | Model access and matching local tokenizer |

These decisions were agreed in discussion. Model access and matching local
tokenizer availability are still unverified. No model/provider substitution is
authorized by this document. PostgreSQL remains authoritative; Qdrant is a
derived retrieval index.

## Scope and existing code

The repository already persists canonical artifacts and evidence in PostgreSQL.
Chunk storage, Qdrant storage, and the indexing workflow are not implemented.
The first increment adds configuration, a separately testable Cohere adapter,
local tokenizer loading, and an explicit compatibility probe. Live model access
and the matching tokenizer are not verified by mocked tests.

The existing `VectorStore` protocol in `app/domain/interfaces.py` combines text
input and vector-storage behavior. It has no explicit chunk upsert/deletion or
embedding-cache contract. Separating these responsibilities is part of the
implementation plan; the final interfaces and SQL fields are not implemented
or finalized here.

Live Jira/GitHub fetching, the daily schedule, keyword search, reranking, and
the LangGraph investigation agent remain separate work.

## D01: Index artifact passages and evidence

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | Index both normalized artifact chunks and derived evidence. |
| Rationale | Artifact passages retain context that extraction may miss; evidence provides focused, source-backed statements with canonical references. |
| Alternatives | Evidence-only indexing reduces duplication but narrows coverage. Artifact-only indexing loses a direct retrieval path to evidence IDs. |
| Tradeoffs | More vectors and embedding inputs; overlapping text requires deduplication. Current evidence includes full comments and PR descriptions, so it is not always a concise claim. Evidence type alone does not establish truth. |

## D02: Hybrid chunking without semantic boundary detection

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | Split artifacts by source structure first, such as descriptions and individual Jira comments. Split oversized sections at paragraph/sentence boundaries, falling back to token boundaries when necessary. Keep short evidence whole and split oversized evidence. Do not overlap unrelated sections/comments. |
| Rationale | Preserve meaningful source boundaries while bounding input size. |
| Alternatives | Fixed token windows ignore structure; embedding-based semantic splitting adds another model-dependent processing stage. |
| Tradeoffs | Source-specific extraction and deterministic fallback rules are needed. Structural boundaries may not align perfectly with topics. Semantic boundary detection is deferred. |

## D03: 512 tokens maximum and 64 tokens overlap

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | Each embedding input is at most 512 tokens, including its context prefix. Target 64 tokens of passage overlap between adjacent chunks within a section; the prefix is not part of overlap. Short standalone sections need no overlap. |
| Rationale | An explicit starting budget balances local context and focused retrieval. This is an evaluation baseline, not a proven optimum. |
| Alternatives | Smaller windows provide narrower results; larger windows retain more context but may combine several claims. |
| Tradeoffs | Overlap increases embedding work and duplicate matches. Edits can shift later boundaries. A long prefix reduces the passage budget and needs a deterministic bounding policy. Output vector dimensions do not determine the input token limit. |

## D04: Short source/title/type prefixes

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | Embed source, artifact title, and section name for artifact chunks; use source, title, and evidence type for evidence. Preserve original passage text separately. Keep canonical IDs, URLs, authors, and timestamps in provenance and filtering metadata rather than requiring them in the prefix. |
| Rationale | Short passages and comments benefit from artifact context. |
| Alternatives | Content alone avoids repeated context but can be ambiguous; large metadata prefixes can dominate the passage. |
| Tradeoffs | Title/type changes alter embedding input even when passage text is unchanged. Repeated prefixes can increase similarity between otherwise different passages and consume the 512-token budget. |

## D05: Qdrant as a derived vector index

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | Use Qdrant for embeddings, canonical references, and filtering metadata. PostgreSQL owns source records, chunks, provenance, and workflow state. |
| Rationale | A separate retrieval service can evolve independently of canonical persistence and follows the project's projection approach. |
| Alternatives | pgvector would reduce service count and permit SQL joins and shared PostgreSQL transactions. |
| Tradeoffs | Another service/container, synchronization path, and recovery mechanism. PostgreSQL and Qdrant do not share an atomic transaction. The design does not require duplicating the full evidence body in Qdrant. |

## D06: One shared Qdrant collection

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | Put artifact and evidence vectors in one collection, distinguished by `record_type`. Revisit separate collections if retrieval evaluation warrants it. |
| Rationale | A common model/configuration permits combined retrieval with fewer collection-management paths. Type filters can support separate result quotas. |
| Alternatives | Separate collections allow independent configuration and rebuilds, but require multi-collection retrieval and merging. |
| Tradeoffs | An unfiltered top-k may favor one record type. Deduplication and ranking are required regardless of collection layout. A shared collection does not prohibit running separate filtered searches. |

## D07: Cohere evaluation API for embeddings

| Field | Details |
| --- | --- |
| Status | Adapter implemented with mocked tests; real account access unverified |
| Decision | Use Cohere's evaluation service for the current testing workload. Keep embedding generation behind a provider-independent interface. Batch inputs, reuse cached results, and mock routine tests to conserve API calls. |
| Rationale | The user expects low-volume testing over time and preferred a recurring evaluation allowance over a one-time token grant. |
| Alternatives | OpenAI, Gemini, Voyage, managed open-weight endpoints, or local open-weight model serving were discussed. Existing OpenAI LLM usage does not require using OpenAI embeddings. |
| Tradeoffs | Hosted-service dependency, quotas, and external data processing. Evaluation terms do not establish production authorization or a production SLA. Provider allowances can change; verify current terms before deployment. Cohere API selection is not a decision to self-host an open-weight model. |

## D08: Proposed model configuration, pending compatibility checks

| Field | Details |
| --- | --- |
| Status | Configuration, response validation, and opt-in probe implemented; live model compatibility unverified |
| Decision | Start with `embed-v5.0-fast`, 1,024-dimensional float vectors and cosine similarity, subject to access verification. Use document input mode for indexed text and query input mode for searches, as supported by the selected API. |
| Rationale | A lightweight model and reduced vector size provide a starting configuration for retrieval evaluation. |
| Alternatives | Higher-dimensional output, the Pro model, or a different model family may improve some workloads but change storage, latency, or integration. |
| Tradeoffs | Reduced dimensions may affect quality. Model/dimension changes require compatible query vectors and a versioned reindexing plan; equal vector length alone does not make unrelated models compatible. Availability under the user's evaluation key has not been verified. There is no approved silent fallback. |

## D09: Model-matched local tokenizer

| Field | Details |
| --- | --- |
| Status | Local loader tested with a synthetic tokenizer; provider-matched tokenizer unverified |
| Decision | Count tokens locally using a tokenizer matching the chosen model. Count the exact prefixed input. Do not silently substitute another model's tokenizer. |
| Rationale | Avoid network latency and API calls for repeated token counting. |
| Alternatives | A hosted tokenizer adds requests; word/character estimates or another provider's tokenizer cannot guarantee our chosen model's token count. |
| Tradeoffs | Tokenizer availability, downloads, versioning, and exact counting semantics must be checked. Matching tokenizer support for the proposed model remains unverified and is a prerequisite for implementation of exact token limits. |

## D10: Offline batch indexing after canonical persistence

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | Refresh embeddings as part of an offline ingestion run, after data is committed to PostgreSQL. The intended pipeline is source ingestion, canonical persistence, graph synchronization, and vector indexing. A daily trigger can be added later; no execution time or scheduler has been selected. |
| Rationale | Match the user's periodic freshness needs without query-time or interactive ingestion latency. |
| Alternatives | Immediate per-record indexing improves freshness but couples ingestion latency to embedding/vector services; a dedicated worker adds scheduling and operational complexity. |
| Tradeoffs | Data is eventually consistent and may not be searchable until the indexing stage completes. Independent graph/vector failures must not imply canonical PostgreSQL rollback. Stage coordination still needs implementation. |

## D11: Content-based IDs and incremental embedding reuse

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | Identify chunks by content rather than chunk number alone. Track source ownership and occurrence/location separately enough to distinguish repeated passages. Fingerprint the exact embedding input and embedding configuration, including model, dimensions, and document/query role. |
| Rationale | Reuse unchanged embeddings even when content is reprocessed; identical text in different sources must retain its own provenance. |
| Alternatives | Position-based IDs are simpler but shift after insertions; regenerating all embeddings wastes calls on unchanged inputs. |
| Tradeoffs | Separate chunk occurrence identity, input fingerprint, and source version tracking are necessary. The precise ID encoding and duplicate-occurrence mapping are implementation details still to specify; content hashes alone do not identify where a passage came from. Changes to overlap or prefix can invalidate several inputs. Metadata-only changes need not generate new embeddings. |

## D12: Safe replacement and obsolete-vector cleanup

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | For an updated artifact, calculate desired chunks, reuse unchanged embeddings, generate new/changed embeddings, and write desired points. Remove obsolete points only after replacement indexing succeeds. Track workflow success only after required cleanup succeeds. |
| Rationale | Avoid deleting useful searchable content before replacement is ready. |
| Alternatives | Delete-and-rebuild is simpler but can leave a retrieval gap; retaining every old vector creates stale results indefinitely. |
| Tradeoffs | Partial runs may temporarily retain stale/duplicate results. Upload-then-delete is not an atomic publication mechanism. Retry/recovery must handle ambiguous network outcomes, repeated upserts, and cleanup failure. |

## D13: Separate PostgreSQL storage responsibilities

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | Use separate tables for chunks/provenance, reusable embedding cache, and per-artifact workflow status/retry information. PostgreSQL owns the complete pending/succeeded/failed workflow; Qdrant metadata describes stored vectors. |
| Rationale | Failures can occur before a Qdrant point exists or while Qdrant is unavailable. Independent chunk/cache/workflow updates avoid repeated API work. |
| Alternatives | One combined table reduces table count but mixes lifecycles; Qdrant-only workflow status cannot reliably represent pre-upload failures. |
| Tradeoffs | Additional SQL schemas, joins, storage, and consistency rules. Caching vectors duplicates vector values across stores to support replay without another API call. Exact SQL field definitions and migrations are not finalized. |

## D14: One workflow status per artifact and all derived evidence

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | Track success/failure and retry scheduling for an artifact as a unit, including all its artifact chunks and derived evidence. Persist chunk fingerprints/cache entries so retries can reuse successful work. Reports identify the failed stage and affected chunks/evidence. |
| Rationale | Matches the user's requested source-record level of tracking without forcing successful chunks to be re-embedded. |
| Alternatives | Independent chunk/evidence workflow states offer finer control but add more state transitions and retry scheduling. |
| Tradeoffs | One failed item keeps the artifact unsuccessful. Detailed reports and cache reconciliation remain necessary even without per-chunk workflow status. Interrupted/stale artifact work needs recoverable state transitions. |

## D15: Continue on errors; fixed retry policy

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | Continue other artifacts when one fails. Allow one initial attempt plus three automatic retries, with a fixed one-second delay, for every error. After exhaustion, record the failure and leave it eligible for the next run. Reuse completed work, including cached embeddings after Qdrant write failures. |
| Rationale | Simple, predictable behavior selected by the user for the current testing workload; one artifact must not block the rest of the run. |
| Alternatives | Stop immediately, retry transient errors only, or use exponential backoff with jitter and provider-directed delays. |
| Tradeoffs | Retrying invalid input or authentication failures wastes attempts. One-second retries may repeatedly hit rate limits; lack of jitter can synchronize clients. This is a deliberate current choice, not production retry guidance. Avoid stacking automatic SDK retries on top of the agreed four-attempt policy. Retry bookkeeping must distinguish a new scheduled run from an in-run attempt. |

## D16: JSON report at run completion and short terminal summary

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | Save one detailed JSON report at run completion. Print a short terminal summary with counts and report path. Include artifact IDs, work reused or generated, failures, stage/error reasons, attempts, and deferred work. |
| Rationale | JSON supports later automation; terminal output stays readable. |
| Alternatives | Markdown, both formats, or a continuously updated report. |
| Tradeoffs | A process crash before completion can leave no JSON report. PostgreSQL workflow/cache state must support recovery independently. Report errors must be sanitized; credentials and sensitive raw API responses must not be written. Exact report path, retention, and field names remain implementation details. |

## D17: Success exit for partial success

| Field | Details |
| --- | --- |
| Status | Agreed design; not implemented |
| Decision | Exit successfully when at least one artifact completes, including mixed-success runs. No-work runs also succeed. Return failure when every attempted artifact fails or the run cannot start. Exhausted artifacts remain retryable next run. |
| Rationale | User chose reports and terminal counts to surface partial failures. |
| Alternatives | A nonzero exit for any failure makes scheduler alerts stricter. |
| Tradeoffs | Exit-code-only monitoring misses partial failures; operators or future tooling must inspect report counts. Terminal/report output must distinguish partial success from complete success. Run-level failures such as inability to write the required report need explicit handling during implementation. |

## Implementation sequence and validation

### First-increment implementation details

| Detail | Choice and tradeoff |
| --- | --- |
| Provider transport | Direct Cohere REST calls through HTTPX; avoids SDK-internal retries and keeps the agreed four-attempt policy under the future runner's control. Requires maintaining request/response validation against official API contracts. |
| Live verification | Compatibility command defaults to local readiness checks; explicit live mode uses synthetic text only. A configured key or a placeholder is not proof of model access. |
| Tokenizer loading | Obtain a tokenizer URL from the selected model's metadata and load its JSON locally. Pin model identity and tokenizer content fingerprint; do not claim model compatibility for an arbitrary tokenizer file. |
| Account prerequisites | User will add the real COHERE_API_KEY later. No Cohere API requests are authorized during this increment; routine tests use mocked HTTP responses. |

### First-increment results (2026-10-24)

| Component | Implementation and verification |
| --- | --- |
| Configuration | `app/config.py` adds masked COHERE_API_KEY, model, dimension, and timeout settings. Existing LLM configuration is retained. |
| Provider adapter | `app/models/cohere_embeddings.py` implements document/query input roles, explicit dimensions, sanitized errors, finite-vector validation, and no automatic retries. All provider interactions tested with HTTPX mock transports. |
| Local tokenizer | `app/models/local_tokenizer.py` loads tokenizer JSON, counts input tokens locally without model-added special tokens, and records model name plus configuration hash. Tests use a deliberately synthetic tokenizer, not an assumed substitute for Cohere's model. |
| Dependency installation | HTTPX and tokenizers declared in pyproject.toml; installed with `python -m pip install -e .`. Tokenizers 0.23.3 installed in the project venv. |
| Readiness command | `python -m scripts.check_embedding_compatibility` reports local prerequisites without making provider calls or printing credentials. A placeholder counts as a present key, not verified access. |
| Future explicit live check | `python -m scripts.check_embedding_compatibility --live` fetches model metadata, loads its advertised tokenizer, and requests synthetic document/query vectors. No live check has been run. |
| Validation | Full suite: 184 tests passed, including live PostgreSQL/Neo4j tests and 28 added embedding checks. Ruff and targeted Mypy passed. Both database containers healthy. |
| Remaining work | Verify real model/tokenizer access; implement chunking, chunk/cache/workflow schemas, Qdrant adapter, and batch runner/reporting. |

1. Verify model access, local tokenizer compatibility, and API request semantics.
2. Define domain/contracts and implement deterministic source-aware chunking.
3. Add reviewed SQL schemas for chunks, embedding cache, and artifact workflow.
4. Implement provider-independent embeddings and Qdrant storage/search adapters.
5. Implement batch orchestration, bounded retries, cleanup, and JSON reporting.
6. Validate retrieval relevance and failure recovery before declaring completion.

Tests must cover prefix-inclusive token limits, overlap, repeated content,
stable fingerprints, unchanged-input cache reuse, metadata-only updates, removed
chunks/evidence, partial uploads/cleanup failures, process recovery, retry counts,
report contents, exit status, and source traceability. Mock routine provider calls;
run real API checks explicitly to conserve the evaluation allowance.

Source/evidence lineage also needs checking against actual code: domain evidence
permits an absent `location.artifact_id`. Do not assume every stored evidence item
already has the mandatory artifact relationship the indexing workflow needs.

The collection name, exact ID/schema encoding, report location, and schedule are
not decided by this record. Resolve them transparently within the agreed scope;
material deviations need an updated decision and appropriate authorization.

## References

These links describe provider capabilities, not proof of access for this account:

- [Cohere embedding models](https://docs.cohere.com/docs/cohere-embed)
- [Cohere tokenizer guidance](https://docs.cohere.com/docs/tokens-and-tokenizers)
- [Cohere evaluation limits](https://docs.cohere.com/v2/docs/rate-limits)
- [Cohere pricing and trial terms](https://cohere.com/pricing)
- [Qdrant collections](https://qdrant.tech/documentation/manage-data/collections/)
- [Qdrant filtering](https://qdrant.tech/documentation/search/filtering/)

Recheck mutable provider capabilities and terms before implementing adapters.

## Change history

| Date | Change | Reason |
| --- | --- | --- |
| 2026-10-24 | Recorded D01-D17 from the design discussion; no code implemented | Preserve choices and tradeoffs before implementation |
| 2026-10-24 | Captured shared collection instead of separate collections, and Cohere instead of the earlier OpenAI suggestion | User chose combined retrieval initially and a testing-oriented hosted provider |
| 2026-10-24 | Captured local tokenizer, content-based IDs, separate SQL tables, and four total attempts one second apart | Final four design choices agreed by user |
| 2026-10-24 | Reformatted all 17 decisions into structured tables with status, decision, rationale, alternatives, and tradeoffs | User requested a tabular design record; decisions unchanged |
| 2026-10-24 | Started the first implementation increment with mocked provider tests and explicit live verification | User authorized implementation but deferred adding the real Cohere key |
| 2026-10-24 | Completed the adapter/tokenizer/readiness increment; installed manifest dependencies and passed 184 tests | User requested manifest-based installation and started Docker for live database validation; Cohere access remains unverified |
