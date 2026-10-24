# Progress

## 2026-10-24: Embedding adapter and compatibility tooling

- Added Cohere document/query adapter, validated vector responses, sanitized
  errors, masked configuration, and a local tokenizer loader with content hash.
- Added an explicit compatibility command: no provider requests by default;
  `--live` requires the real key and verifies the advertised tokenizer/model.
- Declared dependencies in pyproject.toml and installed from the project manifest.
- Started PostgreSQL and Neo4j; both containers healthy.
- Validation: 184 tests passed, including 28 new embedding tests. Ruff and
  targeted Mypy passed. No Cohere API calls were made; provider access and a
  model-matched tokenizer remain unverified until the real key is configured.
- Updated the embedding design status and tradeoff record. Chunking, SQL indexing
  schemas, Qdrant, and the batch runner are still to be implemented.

## 2026-10-22: Canonical relationships and graph synchronization

- Added PostgreSQL relationship storage and atomic ingestion writes.
- Added Neo4j relationship persistence and one-hop neighbors.
- Added serialized, replayable PostgreSQL-to-Neo4j projection and optional
  post-commit ingestion integration, with explicit partial-failure reporting.
- Fixed repository-aware GitHub PR resolution; ambiguous Jira PR numbers remain
  unresolved, while explicit PR URLs resolve directly.
- Added bootstrap/replay commands and documented recovery in GRAPH_PERSISTENCE.md.
- Validation: 156 tests pass, including live PostgreSQL/Neo4j failure-recovery
  and concurrency cases. Prior baseline: 101 tests.

Next milestone: embeddings and vector indexing. Full replay has no deletion
propagation, outbox delivery, or background retry scheduler.
