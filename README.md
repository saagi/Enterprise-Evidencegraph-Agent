# Enterprise EvidenceGraph Agent

**An evidence-grounded AI investigation system for enterprise engineering workflows.**

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791)](https://www.postgresql.org/)
[![Status](https://img.shields.io/badge/Status-Active%20Development-orange)](#project-status)

> **Project status:** Work in progress. The domain model, Jira/GitHub normalization, artifact processing, PostgreSQL persistence layer, and initial tests are implemented. The end-to-end investigation agent, graph/vector retrieval, API, and evaluation framework are planned or in progress—not yet production-ready.

## Overview

Engineering decisions are scattered across issue trackers, pull requests, comments, and documentation. Answering a seemingly simple question—*“What is the status of this incident, and was the fix actually implemented?”*—often requires checking multiple systems and reconciling conflicting signals.

**Enterprise EvidenceGraph Agent** is designed to ingest engineering artifacts, preserve their provenance, extract structured evidence and relationships, and support grounded investigations across sources.

The initial vertical slice focuses on **Jira and GitHub** using a synthetic payments-service scenario. It deliberately distinguishes facts such as:

- A Jira issue being **In Progress**
- A related GitHub pull request being **merged**
- A fix being **deployed** (which must not be inferred from a merge alone)

The goal is to provide answers that are traceable to source evidence, aware of timestamps, and explicit about uncertainty.

## Architecture

```mermaid
flowchart TD
    J[Jira] --> C[Source connectors]
    G[GitHub] --> C
    C --> A[Canonical artifacts]
    A --> P[Artifact processor]
    P --> ER[Entity identification and resolution]
    P --> EV[Event and evidence extraction]
    P --> RR[Relationship candidate extraction]
    ER --> DB[(PostgreSQL)]
    EV --> DB
    RR --> DB
    DB -->|Post-commit projection / replay| NG[(Neo4j graph)]
    DB -. Planned .-> VX[(Qdrant vectors + BM25)]
    NG -. Planned .-> AG[LangGraph investigation agent]
    VX -. Planned .-> AG
    AG -. Planned .-> API[FastAPI / grounded answers]
```

**Design principle:** Separate deterministic ingestion and validation from probabilistic LLM interpretation. An LLM may propose a semantic relationship, but the system should validate identifiers, provenance, and supported claims before persisting or using it.

## Core concepts

| Concept | Purpose |
|---|---|
| **Canonical Artifact** | Normalized representation of a Jira issue or GitHub pull request |
| **Entity** | Identifiable object, such as a Jira ticket or repository-scoped PR |
| **Relationship** | Typed connection between entities, with confidence and provenance |
| **Event** | Timestamped change, such as issue creation or PR merge |
| **Evidence** | Source-backed claim with timestamp and location |
| **Investigation** | Planned multi-step retrieval and synthesis over evidence and relationships |

## Current implementation

- **Typed domain models** with Pydantic for artifacts, entities, relationships, events, and evidence.
- **Jira and GitHub connectors** that normalize source records into canonical artifacts.
- **Entity identification and resolution** with deterministic identifier matching and repository-aware GitHub PR IDs.
- **Event and evidence extraction** from supported Jira and GitHub artifact fields.
- **Optional LLM-assisted relationship extraction** with deterministic validation of resolved targets.
- **Ingestion orchestrator** that creates or updates a primary entity before processing its artifact.
- **PostgreSQL storage** using SQLAlchemy 2, psycopg, JSONB, and conflict-aware upserts.
- **Atomic ingestion persistence** for artifacts, entities, events, evidence, and validated relationships.
- **Neo4j projection** with canonical IDs, idempotent entities/edges, and one-hop neighbors.
- **Replay and recovery** from committed PostgreSQL data, with optional post-commit projection.
- **Unit and live integration tests** covering PostgreSQL/Neo4j rollback, retries, and concurrency.

Graph setup, ingestion wiring, PR resolution rules, and recovery limits are documented
in [Graph persistence and recovery](docs/GRAPH_PERSISTENCE.md).

### Planned next

1. Add vector embeddings, Qdrant, BM25, hybrid retrieval, and reranking.
2. Build a LangGraph investigation workflow with evidence validation and conflict handling.
3. Expose investigation endpoints through FastAPI.
4. Evaluate retrieval quality, temporal correctness, groundedness, latency, and cost.

Slack ingestion, autonomous actions, and cloud-scale deployment are **outside the initial V1 scope**.

## Technology stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Data validation | Pydantic |
| Structured storage | PostgreSQL 16, SQLAlchemy 2, psycopg |
| LLM integration | Provider-independent gateway; OpenAI implementation |
| Testing | pytest |
| Local infrastructure | Docker Compose |
| Graph storage | Neo4j 5 Community |
| Semantic search *(planned)* | Qdrant, embeddings |
| Keyword retrieval *(planned)* | BM25 |
| Agent orchestration *(planned)* | LangGraph |
| API *(planned)* | FastAPI |

## Repository structure

```text
enterprise-evidencegraph-agent/
├── app/
│   ├── domain/
│   │   ├── models.py
│   │   ├── interfaces.py
│   │   ├── entity_registry.py
│   │   └── services.py
│   ├── ingestion/
│   │   ├── connectors.py
│   │   ├── processor.py
│   │   └── orchestrator.py
│   ├── models/
│   │   ├── gateway.py
│   │   └── openai_gateway.py
│   ├── storage/
│   │   ├── postgres.py
│   │   ├── schema.py
│   │   └── repositories.py
│   └── config.py
├── tests/
│   ├── fixtures/
│   │   ├── jira/
│   │   └── github/
│   ├── unit/
│   └── integration/
├── docker-compose.yml
├── pyproject.toml
├── .env.example
└── README.md
```

The structure above represents the current development layout; planned services will be added incrementally.

## Getting started

### Prerequisites

- Python **3.12**
- Docker Desktop (or Docker Engine with Compose)
- Git

### 1. Clone and create an environment

```bash
git clone https://github.com/<your-username>/enterprise-evidencegraph-agent.git
cd enterprise-evidencegraph-agent
python -m venv venv
```

Activate the environment:

**Windows / Git Bash**

```bash
source venv/Scripts/activate
```

**macOS / Linux**

```bash
source venv/bin/activate
```

Install the project and its dependencies from `pyproject.toml`:

```bash
python -m pip install -e .
```

### 2. Configure environment variables

Copy the template to `.env` and configure any required application settings. For local PostgreSQL:

```dotenv
DATABASE_URL=postgresql+psycopg://evidencegraph:evidencegraph@127.0.0.1:5432/evidencegraph
```

The credentials above are **local development defaults only**. Never use them for a public deployment. Keep `.env` out of Git.

### 3. Start PostgreSQL

```bash
docker compose up -d postgres
docker compose ps
```

Wait until the PostgreSQL container reports **healthy**.

### 4. Initialize tables

From the repository root:

```bash
python -c "from app.storage.postgres import PostgresDatabase; from app.storage.schema import Base; db = PostgresDatabase('postgresql+psycopg://evidencegraph:evidencegraph@127.0.0.1:5432/evidencegraph'); Base.metadata.create_all(db.engine); print('Tables created'); db.dispose()"
```

Verify the schema:

```bash
docker compose exec postgres psql -U evidencegraph -d evidencegraph -c "\dt"
```

Expected tables: `artifacts`, `entities`, `events`, `evidence`, `relationships`.

For an existing database, initialize the additive relationship table with
`python -m scripts.init_relationship_storage`. Run `python -m scripts.sync_graph`
to initialize graph constraints and replay canonical records into Neo4j.

> `Base.metadata.create_all()` is a development bootstrap step, not a migration strategy. Schema migrations will be added later.

## Running tests

Run unit tests:

```bash
pytest tests/unit -v
```

Run PostgreSQL integration tests **with the database container running**:

```bash
pytest tests/integration/test_postgres_repositories.py -v --durations=10
```

Run the full test suite:

```bash
pytest -v
```

Integration tests write temporary records to the local test database and clean them up. For a production-quality CI pipeline, a dedicated isolated test database will be used.

## Example investigation (target behavior)

**Question:**

> What's the current status of `PAY-1842`, and was the fix implemented?

**Desired evidence-grounded response:**

- Jira `PAY-1842` is currently **In Progress**, based on the latest issue status evidence.
- GitHub PR `#829` in `acme/payments-api` was **merged**, indicating the code change was integrated.
- **Deployment is not confirmed** unless a deployment event or another authoritative source explicitly supports it.
- Each conclusion should link back to its source artifact and relevant timestamp.

*This is an illustrative target response, not a claim that the complete investigation workflow is implemented today.*

## Engineering priorities

This project emphasizes:

- **Groundedness:** every material claim should be supported by retrievable evidence.
- **Temporal accuracy:** newer evidence should be considered without erasing historical events.
- **Provenance:** preserve source system, artifact identity, timestamps, and locations.
- **Idempotency:** repeated ingestion should not create duplicate records.
- **Separation of concerns:** connectors, processing, persistence, retrieval, and reasoning remain independently testable.
- **Operational reliability:** explicit error handling, measurable latency, and reproducible evaluation.

## Development notes

Stop the local database without deleting its data:

```bash
docker compose stop
```

Restart it:

```bash
docker compose start postgres
```

Alternatively, `docker compose down` removes the container and network but preserves the named PostgreSQL volume. **Do not use `docker compose down -v` unless you intentionally want to delete the database volume.**

## Security and data policy

The initial examples and fixtures use **synthetic engineering data**. Do not commit real customer data, proprietary internal artifacts, API keys, or credentials. Future enterprise integrations should enforce source-system permissions and user-specific authorization during retrieval.

## License

No license has been selected yet. Add a `LICENSE` file before specifying reuse terms.

---

**Built as a production-oriented AI engineering portfolio project, developed incrementally with tests and explicit architectural trade-offs.**
