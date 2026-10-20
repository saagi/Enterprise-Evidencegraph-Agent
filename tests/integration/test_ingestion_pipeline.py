
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.domain.entity_registry import create_default_entity_registry
from app.domain.services import (
    EntityResolver,
    EventExtractor,
    EvidenceExtractor,
)
from app.ingestion.connectors import (
    GitHubPRConnector,
    JiraConnector,
    SourceRecord,
)
from app.ingestion.orchestrator import IngestionOrchestrator
from app.ingestion.persistence import PostgresPersistenceService
from app.ingestion.processor import ArtifactProcessor
from app.domain.models import Source
from app.storage.postgres import PostgresDatabase
from app.storage.repositories import (
    PostgresEntityRepository,
)
from app.storage.schema import (
    ArtifactRow,
    EntityRow,
    EventRow,
    EvidenceRow,
)


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://evidencegraph:evidencegraph@127.0.0.1:5432/evidencegraph",
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(source: str, filename: str) -> dict:
    path = FIXTURES_DIR / source / filename
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def database():
    db = PostgresDatabase(DATABASE_URL)
    yield db
    db.dispose()


def build_orchestrator(database, connector):
    entity_repo = PostgresEntityRepository(database)

    processor = ArtifactProcessor(
        entity_registry=create_default_entity_registry(),
        entity_resolver=EntityResolver(entity_repo),
        event_extractor=EventExtractor(),
        evidence_extractor=EvidenceExtractor(),
        relationship_extractor=None,
    )

    return IngestionOrchestrator(
        connector=connector,
        entity_repository=entity_repo,
        processor=processor,
        persistence=PostgresPersistenceService(database),
    )


def test_jira_ingestion_end_to_end(database):
    payload = load_fixture("jira", "PAY-1842.json")

    # Use a unique Jira key to isolate this test from other runs.
    ticket_key = f"TEST-{uuid4().hex[:8].upper()}"

    payload["key"] = ticket_key

    if isinstance(payload.get("fields"), dict):
        payload["fields"]["summary"] = "Synthetic payment failure"

    record = SourceRecord(
        source=Source.JIRA,
        source_id=ticket_key,
        payload=payload,
        metadata={},
    )

    orchestrator = build_orchestrator(
        database,
        JiraConnector(),
    )

    entity_id = f"jira:{ticket_key}"
    artifact_id = f"artifact:jira:{ticket_key}"

    try:
        result = orchestrator.ingest(record)

        assert result.artifact_id == artifact_id
        assert any(entity.id == entity_id for entity in result.entities)

        with database.session() as session:
            assert session.get(EntityRow, entity_id) is not None
            assert session.get(ArtifactRow, artifact_id) is not None

            events = (
                session.query(EventRow)
                .filter(EventRow.entity_id == entity_id)
                .all()
            )
            assert len(events) >= 1

    finally:
        with database.session() as session:
            session.execute(
                delete(EventRow).where(EventRow.entity_id == entity_id)
            )
            session.execute(
                delete(EvidenceRow).where(
                    EvidenceRow.entity_ids.contains([entity_id])
                )
            )
            session.execute(
                delete(EntityRow).where(EntityRow.id == entity_id)
            )
            session.execute(
                delete(ArtifactRow).where(ArtifactRow.id == artifact_id)
            )


def test_github_ingestion_end_to_end(database):
    payload = load_fixture("github", "PR-829.json")

    # The fixture is synthetic and repository-scoped.
    repo = f"acme/test-{uuid4().hex[:8]}"
    pr_number = 829

    if isinstance(payload.get("base"), dict):
        if isinstance(payload["base"].get("repo"), dict):
            payload["base"]["repo"]["full_name"] = repo

    record = SourceRecord(
        source=Source.GITHUB,
        source_id=f"{repo}:pr:{pr_number}",
        payload=payload,
        metadata={},
    )

    orchestrator = build_orchestrator(
        database,
        GitHubPRConnector(),
    )

    entity_id = f"github:{repo}:pr:{pr_number}"
    artifact_id = f"artifact:{entity_id}"

    try:
        result = orchestrator.ingest(record)

        assert result.artifact_id == artifact_id
        assert any(entity.id == entity_id for entity in result.entities)

        with database.session() as session:
            assert session.get(EntityRow, entity_id) is not None
            assert session.get(ArtifactRow, artifact_id) is not None

            events = (
                session.query(EventRow)
                .filter(EventRow.entity_id == entity_id)
                .all()
            )
            assert len(events) >= 1

            # GitHub events must not be attributed to Jira.
            assert all(
                event.entity_id == entity_id
                for event in events
            )

    finally:
        with database.session() as session:
            session.execute(
                delete(EventRow).where(EventRow.entity_id == entity_id)
            )
            session.execute(
                delete(EvidenceRow).where(
                    EvidenceRow.entity_ids.contains([entity_id])
                )
            )
            session.execute(
                delete(EntityRow).where(EntityRow.id == entity_id)
            )
            session.execute(
                delete(ArtifactRow).where(ArtifactRow.id == artifact_id)
            )
