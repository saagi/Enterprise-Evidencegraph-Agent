
# Enterprise EvidenceGraph Agent — Codex Instructions

## Project
Production-oriented enterprise investigation agent using
Jira and GitHub evidence.

## Tech Stack
- Python 3.12
- Pydantic and SQLAlchemy
- PostgreSQL 16
- Neo4j 5 Community
- OpenAI LLM gateway
- LangGraph (planned)
- Vector DB and hybrid retrieval (planned)
- Pytest, Ruff, Mypy
- Docker Compose

## Repository Conventions
- Application source code lives under app/
- Imports must use app.* paths
- Domain models: app/domain/
- Ingestion: app/ingestion/
- Model gateways: app/models/
- Persistence: app/storage/
- Tests: tests/unit/ and tests/integration/

## Architectural Decisions
- PostgreSQL is the authoritative data store.
- Neo4j stores a graph projection of canonical entities.
- Entity identity must remain consistent across stores.
- Use idempotent persistence operations.
- Do not assume atomic transactions across databases.
- V1 supports Jira and GitHub only.
- Slack and document connectors are deferred.
- V1 must include embeddings, vector retrieval,
  graph traversal, hybrid search, and LangGraph.

## Development Rules
- Read docs/PROJECT_CONTEXT.md before starting.
- Inspect existing interfaces before implementing new ones.
- Reuse existing models and repository conventions.
- Work one file or small logical change at a time.
- Explain design decisions and tradeoffs.
- Read the relevant record in docs/design/ before changing a subsystem.
- Document new design decisions and tradeoffs before implementation.
- When a decision changes, update its design record and dated change history
  as part of the same work; distinguish agreed, proposed, and implemented behavior.
- Ask for the user's preference before recommending design choices unless
  the user requests a recommendation or authorizes autonomous decisions.
- Add tests for new functionality.
- Run relevant tests after modifications.
- Do not refactor unrelated code.
- Do not modify existing schemas without approval.
- Do not invent missing APIs or domain fields.
- Never commit credentials or .env secrets.
- Update project context after completed milestones.

## Collaboration Style
- Explain the approach before major changes.
- Prefer incremental, test-driven development.
- Ask for approval before architectural changes.
- Report modified files and test results.
