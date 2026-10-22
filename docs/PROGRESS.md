# Progress

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
