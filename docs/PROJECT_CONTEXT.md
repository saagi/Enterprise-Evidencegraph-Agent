
# Enterprise EvidenceGraph Agent — Project Context

## Objective
Build a production-grade enterprise knowledge and
investigation agent that produces evidence-grounded
answers from connected engineering systems.

## V1 Scope
- Jira ticket ingestion
- GitHub PR ingestion
- Canonical artifact processing
- Entity resolution
- Event and evidence extraction
- Relationship extraction
- PostgreSQL persistence
- Neo4j graph persistence
- Vector embeddings and indexing
- Hybrid retrieval (keyword + semantic + graph)
- LangGraph investigation agent
- Evidence-grounded answer generation
- API and evaluation framework

Deferred: Slack, document ingestion, action workflows.

## Existing Project Structure
app/
  config.py
  domain/
    models.py
    interfaces.py
    entity_registry.py
    services.py
  ingestion/
    connectors.py
    processor.py
    orchestrator.py
    persistence.py
  models/
    gateway.py
    openai_gateway.py
  storage/
    postgres.py
    neo4j.py
    neo4j_repositories.py
    schema.py
    repositories.py

tests/
  fixtures/
    jira/PAY-1842.json
    github/PR-829.json
  unit/
    domain/
    ingestion/
    models/
    storage/
  integration/

docker-compose.yml
pyproject.toml
.env.example
README.md

## Completed Implementation
- Jira and GitHub connectors
- Canonical artifact processing
- Entity resolution
- Event and evidence extraction
- Relationship extraction and validation
- OpenAI gateway
- PostgreSQL repositories
- Atomic ingestion persistence
- Rollback and idempotency tests
- Refreshed primary entities replace stored versions in processing results,
  preserving updated fields without early repository writes.
- Neo4j Docker deployment
- Neo4j Python connection manager
- Neo4j unit tests
- Live Python-to-Neo4j connectivity verification
- Neo4j entity repository with explicit identity-constraint initialization,
  canonical-ID MERGE writes, and get/save methods matching EntityRepository.
- Neo4j entity unit tests and live integration tests for round trips,
  updates, idempotency, and duplicate-ID rejection.

## Testing
- Verified baseline (2026-10-22): 101/101 tests passing on Python 3.12.15.
- Includes Neo4j connection-manager tests and a regression test for
  refreshed primary entity replacement.
- Includes 5 Neo4j entity unit tests and 6 live entity integration cases.
- Live Neo4j tests require NEO4J_PASSWORD from the environment or local .env;
  missing credentials skip these cases, while connection failures fail them.

## Current Development Checkpoint
Neo4j infrastructure, connectivity, and entity persistence are complete.

Approved and implemented node representation:
- Common :Entity label with canonical PostgreSQL entity ID as identity.
- Unique Entity.id constraint; explicitly call repository.ensure_schema()
  before using the repository. Constructors do not modify the database.
- Properties: id, type, name, source, source_id, created_at, updated_at,
  and metadata_json (JSON encoding of the domain metadata dictionary).
- Timestamps use Neo4j datetime properties and convert back to Python datetime.
- save() refreshes projected fields from the supplied canonical entity.

NEXT: Finalize relationship persistence and synchronization design.

Relationships are extracted but not persisted: PostgreSQL has no relationship
table, and PostgresPersistenceService does not save result.relationships.
Neo4j entity persistence is not yet wired into ingestion. Relationship schema
and cross-store synchronization still require approval before implementation.

## Remaining Milestones
1. Durable relationship storage and Neo4j relationship repository
2. PostgreSQL-to-Neo4j synchronization
3. Embedding generation and vector indexing
4. BM25 and semantic retrieval
5. Graph traversal and hybrid retrieval
6. Reranking
7. LangGraph investigation agent
8. Evidence-grounded response generation
9. FastAPI endpoints
10. Evaluation and integration testing

## Development Philosophy
Build a complete end-to-end Jira/GitHub vertical
slice before adding more data sources.

Prefer correctness, reliability, observability,
and maintainability over unnecessary complexity.
