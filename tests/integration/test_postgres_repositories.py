
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

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
from app.storage.postgres import PostgresDatabase
from app.storage.repositories import (
    PostgresArtifactRepository,
    PostgresEntityRepository,
    PostgresEventRepository,
    PostgresEvidenceRepository,
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


@pytest.fixture
def database():
    db = PostgresDatabase(DATABASE_URL)
    yield db
    db.dispose()


@pytest.fixture
def repositories(database):
    return {
        "artifacts": PostgresArtifactRepository(database),
        "entities": PostgresEntityRepository(database),
        "events": PostgresEventRepository(database),
        "evidence": PostgresEvidenceRepository(database),
    }


@pytest.fixture
def entity_id():
    return f"jira:TEST-{uuid4().hex[:12]}"


@pytest.fixture
def cleanup(database, entity_id):
    yield

    with database.session() as session:
        # Delete dependent rows before their parent entity.
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


def make_entity(entity_id: str) -> Entity:
    now = datetime.now(UTC)

    return Entity(
        id=entity_id,
        type=EntityType.JIRA_TICKET,
        name="Integration test ticket",
        source=Source.JIRA,
        source_id=entity_id.removeprefix("jira:"),
        created_at=now,
        updated_at=now,
        metadata={"test": True},
    )


def test_entity_insert_and_upsert(
    repositories,
    entity_id,
    cleanup,
) -> None:
    repo = repositories["entities"]

    entity = make_entity(entity_id)
    repo.upsert(entity)

    stored = repo.get_entity(entity_id)

    assert stored is not None
    assert stored.id == entity.id
    assert stored.name == entity.name

    updated = entity.model_copy(
        update={"name": "Updated integration test ticket"}
    )

    repo.upsert(updated)

    stored = repo.get_entity(entity_id)

    assert stored is not None
    assert stored.name == "Updated integration test ticket"


def test_repeated_upsert_does_not_duplicate_entity(
    repositories,
    database,
    entity_id,
    cleanup,
) -> None:
    repo = repositories["entities"]
    entity = make_entity(entity_id)

    repo.upsert(entity)
    repo.upsert(entity)
    repo.upsert(entity)

    with database.session() as session:
        count = session.scalar(
            select(func.count())
            .select_from(EntityRow)
            .where(EntityRow.id == entity_id)
        )

    assert count == 1


def test_artifact_round_trip(
    repositories,
    database,
) -> None:
    artifact_id = f"artifact:jira:TEST-{uuid4().hex[:12]}"
    source_id = artifact_id.removeprefix("artifact:jira:")
    now = datetime.now(UTC)

    artifact = CanonicalArtifact(
        id=artifact_id,
        source=Source.JIRA,
        source_id=source_id,
        artifact_type="jira_ticket",
        title="Payment failure investigation",
        content={
            "status": "In Progress",
            "description": "Investigating intermittent failures",
        },
        metadata={"priority": "High"},
        created_at=now,
        updated_at=now,
    )

    repo = repositories["artifacts"]

    try:
        repo.upsert(artifact)
        stored = repo.get_artifact(artifact_id)

        assert stored is not None
        assert stored.id == artifact.id
        assert stored.content["status"] == "In Progress"
        assert stored.metadata["priority"] == "High"

        repo.upsert(artifact)

        with database.session() as session:
            count = session.scalar(
                select(func.count())
                .select_from(ArtifactRow)
                .where(ArtifactRow.id == artifact_id)
            )

        assert count == 1

    finally:
        with database.session() as session:
            session.execute(
                delete(ArtifactRow).where(
                    ArtifactRow.id == artifact_id
                )
            )


def test_events_are_returned_newest_first(
    repositories,
    entity_id,
    cleanup,
) -> None:
    repositories["entities"].upsert(make_entity(entity_id))

    now = datetime.now(UTC)

    older = Event(
        id=f"event:{uuid4().hex}",
        entity_id=entity_id,
        event_type=EventType.CREATED,
        timestamp=now - timedelta(days=2),
        source=Source.JIRA,
        source_id=entity_id.removeprefix("jira:"),
        data={"status": "Open"},
        metadata={},
        created_at=now,
    )

    newer = Event(
        id=f"event:{uuid4().hex}",
        entity_id=entity_id,
        event_type=EventType.UPDATED,
        timestamp=now,
        source=Source.JIRA,
        source_id=entity_id.removeprefix("jira:"),
        data={"status": "In Progress"},
        metadata={},
        created_at=now,
    )

    repo = repositories["events"]

    repo.upsert(older)
    repo.upsert(newer)

    events = repo.get_events(entity_id)

    assert [event.id for event in events] == [
        newer.id,
        older.id,
    ]


def test_evidence_retrieval_by_entity(
    repositories,
    entity_id,
    cleanup,
) -> None:
    repositories["entities"].upsert(make_entity(entity_id))

    now = datetime.now(UTC)

    evidence = Evidence(
        id=f"evidence:{uuid4().hex}",
        entity_ids=[entity_id],
        source=Source.JIRA,
        source_id=entity_id.removeprefix("jira:"),
        evidence_type=EvidenceType.STATUS_UPDATE,
        claim="Ticket is In Progress",
        content="Current Jira status: In Progress",
        timestamp=now,
        location=EvidenceLocation(
            artifact_id=f"artifact:{entity_id}"
        ),
        metadata={"test": True},
        created_at=now,
    )

    repo = repositories["evidence"]

    repo.upsert(evidence)

    stored = repo.get_evidence(evidence.id)

    assert stored is not None
    assert stored.claim == evidence.claim
    assert stored.location.artifact_id == (
        f"artifact:{entity_id}"
    )

    matches = repo.get_evidence_for_entity(entity_id)

    assert evidence.id in [
        item.id for item in matches
    ]
