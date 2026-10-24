
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
    cohere_embeddings.py
    local_tokenizer.py
  storage/
    postgres.py
    neo4j.py
    neo4j_repositories.py
    graph_projection.py
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
- PostgreSQL canonical relationship storage, with endpoint foreign keys,
  confidence/type checks, preserved creation time, and immutable ID identity.
- Atomic ingestion persistence includes validated relationships.
- Neo4j allowlisted relationship projection and distinct, sorted, bidirectional
  one-hop neighbors. RelationshipIdentity helper nodes enforce edge ID identity.
- PostgreSQL-to-Neo4j full replay, optional post-commit ingestion projection,
  explicit failure reporting, and repeatable recovery after partial graph writes.
- Repository-aware PR mention resolution in GitHub artifacts and explicit GitHub
  PR URL resolution in Jira/GitHub. Ambiguous Jira PR numbers stay unresolved.
- First embedding increment: Cohere document/query adapter, model-metadata
  tokenizer loading, local counting/configuration fingerprinting, masked settings,
  and an explicit compatibility-check command. Provider tests are mocked;
  live Cohere model/tokenizer access remains unverified.

## Testing
- Verified baseline (2026-10-24): 184/184 tests passing on Python 3.12.15.
- Includes 28 embedding adapter/tokenizer/compatibility tests with no Cohere calls.
- Includes Neo4j connection-manager tests and a regression test for
  refreshed primary entity replacement.
- Includes 5 Neo4j entity unit tests and 6 live entity integration cases.
- Includes relationship constraints/rollback, concurrent graph writes,
  full replay recovery/serialization, and Jira-to-PR projection coverage.
- Live Neo4j tests require NEO4J_PASSWORD from the environment or local .env;
  missing credentials skip these cases, while connection failures fail them.

## Current Development Checkpoint
Neo4j infrastructure, entity/relationship persistence, one-hop traversal,
and PostgreSQL-authoritative replay are implemented.

Approved and implemented node representation:
- Common :Entity label with canonical PostgreSQL entity ID as identity.
- Unique Entity.id constraint; explicitly call repository.ensure_schema()
  before using the repository. Constructors do not modify the database.
- Properties: id, type, name, source, source_id, created_at, updated_at,
  and metadata_json (JSON encoding of the domain metadata dictionary).
- Timestamps use Neo4j datetime properties and convert back to Python datetime.
- save() refreshes projected fields from the supplied canonical entity.

Approved and implemented relationship representation:
- PostgreSQL relationships table mirrors the Relationship domain model;
  Text IDs support concatenated endpoint identities longer than 255 characters.
- Source/target foreign keys refer to entities.id. Reusing an ID for different
  endpoints or relationship type is rejected; confidence/provenance can update.
- Directed Neo4j edges use the existing RelationshipType enum mapped to uppercase
  Cypher types, with confidence, temporal properties, and JSON provenance/metadata.
- Constrained :RelationshipIdentity helper nodes serialize each edge identity
  across types on Neo4j Community; they are not canonical domain entities.

Synchronization:
- PostgresPersistenceService optionally accepts graph_projection; PostgreSQL
  commits before replay begins. GraphProjectionError means PostgreSQL committed
  successfully but Neo4j needs replay; PostgreSQL is never rolled back afterward.
- Replay reads one committed PostgreSQL snapshot, validates it, then upserts
  entities before relationships. Advisory locking serializes cooperating workers.
- Run `python -m scripts.init_relationship_storage` once for the additive table,
  then `python -m scripts.sync_graph` to initialize graph constraints and replay.
- See docs/GRAPH_PERSISTENCE.md for wiring, recovery, and limitations.

NEXT: Verify Cohere model/tokenizer access, then implement source-aware chunking
and vector indexing. The first embedding adapter/tokenizer increment is complete.

Embedding/vector decisions and their tradeoffs are recorded in
[docs/design/EMBEDDING_LAYER.md](design/EMBEDDING_LAYER.md). Its status tables
distinguish implemented adapter code from the remaining design. Cohere model
access and a matching local tokenizer remain unverified. See [design maintenance rules](design/README.md)
before implementing or changing a decision.

Install dependencies from pyproject.toml with `python -m pip install -e .`.
`python -m scripts.check_embedding_compatibility` checks local prerequisites only;
`--live` explicitly calls Cohere with synthetic inputs. The user will add the real
COHERE_API_KEY later; no Cohere requests were made in this increment.

Known limitations: replay is upsert-only, materializes the full snapshot, and
holds a PostgreSQL transaction during graph writes. No deletion propagation,
outbox/background worker, or automatic retry scheduler exists. Out-of-order
source payloads can still replace newer canonical state. An unscoped Jira PR
number cannot safely identify a repository and is deliberately unresolved.

## Remaining Milestones
1. Embedding generation and vector indexing
2. BM25 and semantic retrieval
3. Multi-hop graph retrieval and hybrid retrieval
4. Reranking
5. LangGraph investigation agent
6. Evidence-grounded response generation
7. FastAPI endpoints
8. Evaluation and integration testing

## Development Philosophy
Build a complete end-to-end Jira/GitHub vertical
slice before adding more data sources.

Prefer correctness, reliability, observability,
and maintainability over unnecessary complexity.
