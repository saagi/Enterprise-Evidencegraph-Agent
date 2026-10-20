
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.domain.models import (
    CanonicalArtifact,
    Entity,
    EntityType,
    Event,
    EventType,
    Evidence,
    EvidenceLocation,
    EvidenceType,
    Source,
)
from app.ingestion.persistence import PostgresPersistenceService
from app.ingestion.processor import ProcessingResult
from app.storage.postgres import PostgresDatabase
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


@pytest.fixture
def database():
    db = PostgresDatabase(DATABASE_URL)
    yield db
    db.dispose()


@pytest.fixture
def sample_data():
    unique_id = uuid4().hex[:12]
    now = datetime.now(UTC)

    entity_id = f"jira:TEST-{unique_id}"
    artifact_id = f"artifact:{entity_id}"
    evidence_id = f"evidence:{unique_id}"
    event_id = f"event:{unique_id}"

    artifact = CanonicalArtifact(
        id=artifact_id,
        source=Source.JIRA,
        source_id=f"TEST-{unique_id}",
        artifact_type="jira_ticket",
        title="Integration test payment issue",
        content={"status": "In Progress"},
        metadata={"test": True},
        created_at=now,
        updated_at=now,
    )

    entity = Entity(
        id=entity_id,
        type=EntityType.JIRA_TICKET,
        name="Integration test payment issue",
        source=Source.JIRA,
        source_id=f"TEST-{unique_id}",
        created_at=now,
        updated_at=now,
        metadata={"test": True},
    )

    evidence = Evidence(
        id=evidence_id,
        entity_ids=[entity_id],
        source=Source.JIRA,
        source_id=f"TEST-{unique_id}",
        evidence_type=EvidenceType.STATUS_UPDATE,
        claim="Ticket is In Progress",
        content="Jira status: In Progress",
        timestamp=now,
        location=EvidenceLocation(artifact_id=artifact_id),
        metadata={"test": True},
        created_at=now,
    )

    event = Event(
        id=event_id,
        entity_id=entity_id,
        event_type=EventType.UPDATED,
        timestamp=now,
        source=Source.JIRA,
        source_id=f"TEST-{unique_id}",
        data={"status": "In Progress"},
        metadata={},
        evidence_id=evidence_id,
        created_at=now,
    )

    result = ProcessingResult(
        artifact_id=artifact_id,
        entities=[entity],
        entity_resolutions=[],
        events=[event],
        evidence=[evidence],
        relationship_candidates=[],
        relationships=[],
    )

    return artifact, result


@pytest.fixture
def persistence(database):
    return PostgresPersistenceService(database)


@pytest.fixture
def cleanup(database, sample_data):
    artifact, result = sample_data
    entity_id = result.entities[0].id
    event_id = result.events[0].id
    evidence_id = result.evidence[0].id

    yield

    with database.session() as session:
        session.execute(
            delete(EventRow).where(EventRow.id == event_id)
        )
        session.execute(
            delete(EvidenceRow).where(EvidenceRow.id == evidence_id)
        )
        session.execute(
            delete(EntityRow).where(EntityRow.id == entity_id)
        )
        session.execute(
            delete(ArtifactRow).where(ArtifactRow.id == artifact.id)
        )


def test_persist_all_records(database, sample_data, cleanup):
    artifact, result = sample_data
    service = PostgresPersistenceService(database)

    service.persist(artifact, result)

    with database.session() as session:
        assert session.get(ArtifactRow, artifact.id) is not None
        assert session.get(EntityRow, result.entities[0].id) is not None
        assert session.get(EvidenceRow, result.evidence[0].id) is not None
        assert session.get(EventRow, result.events[0].id) is not None


def test_repeated_persistence_is_idempotent(
    database,
    sample_data,
    cleanup,
):
    artifact, result = sample_data
    service = PostgresPersistenceService(database)

    service.persist(artifact, result)
    service.persist(artifact, result)
    service.persist(artifact, result)

    with database.session() as session:
        for row_class, record_id in [
            (ArtifactRow, artifact.id),
            (EntityRow, result.entities[0].id),
            (EvidenceRow, result.evidence[0].id),
            (EventRow, result.events[0].id),
        ]:
            count = session.scalar(
                select(func.count())
                .select_from(row_class)
                .where(row_class.id == record_id)
            )
            assert count == 1


def test_transaction_rolls_back_on_invalid_event(
    database,
    sample_data,
    cleanup,
):
    artifact, result = sample_data
    service = PostgresPersistenceService(database)

    invalid_event = result.events[0].model_copy(
        update={"entity_id": "jira:NONEXISTENT-ENTITY"}
    )

    invalid_result = result.model_copy(
        update={"events": [invalid_event]}
    )

    with pytest.raises(Exception):
        service.persist(artifact, invalid_result)

    with database.session() as session:
        assert session.get(ArtifactRow, artifact.id) is None
        assert session.get(EntityRow, result.entities[0].id) is None
        assert session.get(EvidenceRow, result.evidence[0].id) is None
        assert session.get(EventRow, invalid_event.id) is None


def test_created_at_preserved_on_update(
    database,
    sample_data,
    cleanup,
):
    artifact, result = sample_data
    service = PostgresPersistenceService(database)

    service.persist(artifact, result)

    original_created_at = artifact.created_at

    updated_artifact = artifact.model_copy(
        update={
            "title": "Updated payment investigation",
            "created_at": original_created_at + timedelta(days=1),
            "updated_at": original_created_at + timedelta(days=2),
        }
    )

    service.persist(updated_artifact, result)

    with database.session() as session:
        stored = session.get(ArtifactRow, artifact.id)

        assert stored is not None
        assert stored.title == "Updated payment investigation"
        assert stored.created_at == original_created_at
        assert stored.updated_at == (
            original_created_at + timedelta(days=2)
        )


def test_atomic_ingestion_commits_artifact_and_entity(
    database,
    persistence,
):
    unique_id = uuid4().hex[:8]
    entity_id = f"jira:ATOMIC-{unique_id}"
    artifact_id = f"artifact:{entity_id}"
    now = datetime.now(UTC)

    artifact = CanonicalArtifact(
        id=artifact_id,
        source=Source.JIRA,
        source_id=f"ATOMIC-{unique_id}",
        artifact_type="jira_ticket",
        title="Atomic ingestion success",
        content={"status": "Open"},
        created_at=now,
        updated_at=now,
    )

    entity = Entity(
        id=entity_id,
        type=EntityType.JIRA_TICKET,
        name="Atomic ingestion success",
        source=Source.JIRA,
        source_id=f"ATOMIC-{unique_id}",
        created_at=now,
        updated_at=now,
    )

    result = ProcessingResult(
        artifact_id=artifact_id,
        entities=[entity],
    )

    try:
        persistence.persist(artifact, result)

        with database.session() as session:
            artifact_count = session.scalar(
                select(func.count())
                .select_from(ArtifactRow)
                .where(ArtifactRow.id == artifact_id)
            )

            entity_count = session.scalar(
                select(func.count())
                .select_from(EntityRow)
                .where(EntityRow.id == entity_id)
            )

        assert artifact_count == 1
        assert entity_count == 1

    finally:
        with database.session() as session:
            session.execute(
                delete(EntityRow).where(EntityRow.id == entity_id)
            )
            session.execute(
                delete(ArtifactRow).where(ArtifactRow.id == artifact_id)
            )


def test_atomic_ingestion_rolls_back_on_invalid_event(database, persistence):
    unique_id = uuid4().hex[:8]
    entity_id = f"jira:ROLLBACK-{unique_id}"
    artifact_id = f"artifact:{entity_id}"
    now = datetime.now(UTC)

    artifact = CanonicalArtifact(
        id=artifact_id,
        source=Source.JIRA,
        source_id=f"ROLLBACK-{unique_id}",
        artifact_type="jira_ticket",
        title="Atomic ingestion rollback",
        content={"status": "Open"},
        created_at=now,
        updated_at=now,
    )

    entity = Entity(
        id=entity_id,
        type=EntityType.JIRA_TICKET,
        name="Atomic ingestion rollback",
        source=Source.JIRA,
        source_id=f"ROLLBACK-{unique_id}",
        created_at=now,
        updated_at=now,
    )

    invalid_event = Event(
        id=f"event:{unique_id}",
        entity_id=f"jira:NONEXISTENT-{unique_id}",
        event_type=EventType.CREATED,
        timestamp=now,
        source=Source.JIRA,
        source_id=f"ROLLBACK-{unique_id}",
        data={},
        metadata={},
        created_at=now,
    )

    result = ProcessingResult(
        artifact_id=artifact_id,
        entities=[entity],
        events=[invalid_event],
    )

    with pytest.raises(IntegrityError):
        persistence.persist(artifact, result)

    with database.session() as session:
        artifact_count = session.execute(
            text("SELECT COUNT(*) FROM artifacts WHERE id = :id"),
            {"id": artifact_id},
        ).scalar_one()

        entity_count = session.execute(
            text("SELECT COUNT(*) FROM entities WHERE id = :id"),
            {"id": entity_id},
        ).scalar_one()

    assert artifact_count == 0
    assert entity_count == 0
