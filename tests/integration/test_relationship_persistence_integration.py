import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.domain.models import (
    CanonicalArtifact,
    Entity,
    EntityType,
    Relationship,
    RelationshipType,
    Source,
)
from app.ingestion.persistence import PostgresPersistenceService
from app.ingestion.processor import ProcessingResult
from app.storage.postgres import PostgresDatabase
from app.storage.repositories import PostgresEntityRepository, PostgresRelationshipRepository
from app.storage.schema import ArtifactRow, EntityRow, RelationshipRow


@pytest.fixture
def relationship_records():
    token = uuid4().hex
    timestamp = datetime.now(UTC)
    entities = [
        Entity(
            id=f"jira:REL-{token}-{suffix}",
            type=EntityType.JIRA_TICKET,
            name=f"Relationship endpoint {suffix}",
            source=Source.JIRA,
            source_id=f"REL-{token}-{suffix}",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={},
        )
        for suffix in ("source", "target", "other")
    ]
    artifact = CanonicalArtifact(
        id=f"artifact:relationship-test:{token}",
        source=Source.JIRA,
        source_id=entities[0].source_id,
        artifact_type="jira_ticket",
        title="Relationship transaction test",
        content={"description": "Related tickets"},
        created_at=timestamp,
        updated_at=timestamp,
    )
    relationship = Relationship(
        id=f"relationship:{token}",
        source_entity_id=entities[0].id,
        relationship_type=RelationshipType.REFERENCES,
        target_entity_id=entities[1].id,
        confidence=0.75,
        provenance={
            "artifact_id": artifact.id,
            "evidence_text": "Related tickets",
            "details": {"tags": ["integration", None]},
        },
        observed_at=timestamp,
        created_at=timestamp,
        metadata={"nested": {"enabled": True, "count": 2}},
    )
    return artifact, entities, relationship


@pytest.fixture
def database(relationship_records):
    database = PostgresDatabase(
        os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://evidencegraph:evidencegraph@127.0.0.1:5432/evidencegraph",
        )
    )
    RelationshipRow.__table__.create(database.engine, checkfirst=True)
    artifact, entities, _ = relationship_records
    endpoint_ids = [entity.id for entity in entities]
    try:
        yield database
    finally:
        with database.session() as session:
            session.execute(
                delete(RelationshipRow).where(
                    (RelationshipRow.source_entity_id.in_(endpoint_ids))
                    | (RelationshipRow.target_entity_id.in_(endpoint_ids))
                )
            )
            session.execute(delete(EntityRow).where(EntityRow.id.in_(endpoint_ids)))
            session.execute(delete(ArtifactRow).where(ArtifactRow.id == artifact.id))
        database.dispose()


def save_endpoints(database, entities):
    repository = PostgresEntityRepository(database)
    for entity in entities:
        repository.save(entity)


def test_relationship_round_trip_and_idempotent_updates(database, relationship_records):
    _, entities, relationship = relationship_records
    save_endpoints(database, entities)
    repository = PostgresRelationshipRepository(database)
    repository.save(relationship)

    assert repository.get(relationship.id) == relationship

    refreshed = relationship.model_copy(
        update={
            "confidence": 0.95,
            "observed_at": relationship.observed_at + timedelta(days=1),
            "provenance": {"method": "updated", "nested": [1, {"valid": True}]},
            "metadata": {},
            "created_at": relationship.created_at + timedelta(days=1),
        }
    )
    repository.save(refreshed)
    repository.save(refreshed)

    expected = refreshed.model_copy(update={"created_at": relationship.created_at})
    assert repository.get(relationship.id) == expected
    with database.session() as session:
        assert session.scalar(
            select(func.count())
            .select_from(RelationshipRow)
            .where(RelationshipRow.id == relationship.id)
        ) == 1


def test_relationship_missing_id_returns_none(database):
    assert PostgresRelationshipRepository(database).get(f"missing:{uuid4().hex}") is None


def test_ingestion_persists_relationship_and_preserves_creation_time(
    database, relationship_records
):
    artifact, entities, relationship = relationship_records
    result = ProcessingResult(
        artifact_id=artifact.id,
        entities=entities,
        relationships=[relationship],
    )
    persistence = PostgresPersistenceService(database)
    persistence.persist(artifact, result)
    refreshed = relationship.model_copy(
        update={"created_at": relationship.created_at + timedelta(days=1), "confidence": 0.9}
    )
    persistence.persist(artifact, result.model_copy(update={"relationships": [refreshed]}))

    stored = PostgresRelationshipRepository(database).get(relationship.id)
    assert stored == refreshed.model_copy(update={"created_at": relationship.created_at})


def test_missing_endpoint_rolls_back_entire_ingestion(database, relationship_records):
    artifact, entities, relationship = relationship_records
    invalid = relationship.model_copy(update={"target_entity_id": f"missing:{uuid4().hex}"})
    result = ProcessingResult(
        artifact_id=artifact.id,
        entities=entities,
        relationships=[invalid],
    )

    with pytest.raises(IntegrityError):
        PostgresPersistenceService(database).persist(artifact, result)

    with database.session() as session:
        assert session.get(ArtifactRow, artifact.id) is None
        assert session.get(RelationshipRow, relationship.id) is None
        for entity in entities:
            assert session.get(EntityRow, entity.id) is None


@pytest.mark.parametrize(
    "identity_field", ["source_entity_id", "target_entity_id", "relationship_type"]
)
def test_relationship_identity_conflict_is_rejected(
    database, relationship_records, identity_field
):
    _, entities, relationship = relationship_records
    save_endpoints(database, entities)
    repository = PostgresRelationshipRepository(database)
    repository.save(relationship)
    new_value = (
        RelationshipType.MENTIONS
        if identity_field == "relationship_type"
        else entities[2].id
    )

    with pytest.raises(ValueError):
        repository.save(relationship.model_copy(update={identity_field: new_value}))

    assert repository.get(relationship.id) == relationship


def test_identity_conflict_rolls_back_other_ingestion_writes(database, relationship_records):
    artifact, entities, relationship = relationship_records
    save_endpoints(database, entities)
    repository = PostgresRelationshipRepository(database)
    repository.save(relationship)
    refreshed_entity = entities[0].model_copy(update={"name": "Must roll back"})
    result = ProcessingResult(
        artifact_id=artifact.id,
        entities=[refreshed_entity],
        relationships=[relationship.model_copy(update={"target_entity_id": entities[2].id})],
    )

    with pytest.raises(ValueError):
        PostgresPersistenceService(database).persist(artifact, result)

    assert repository.get(relationship.id) == relationship
    assert PostgresEntityRepository(database).get(entities[0].id) == entities[0]
    with database.session() as session:
        assert session.get(ArtifactRow, artifact.id) is None


def test_long_relationship_identity_round_trips(database, relationship_records):
    _, entities, relationship = relationship_records
    save_endpoints(database, entities)
    relationship = relationship.model_copy(update={"id": f"{relationship.id}:{'x' * 300}"})
    repository = PostgresRelationshipRepository(database)

    repository.save(relationship)

    assert len(relationship.id) > 255
    assert repository.get(relationship.id) == relationship


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_database_rejects_invalid_confidence(database, relationship_records, confidence):
    _, entities, relationship = relationship_records
    save_endpoints(database, entities)
    invalid = relationship.model_copy(update={"confidence": confidence})

    with pytest.raises(IntegrityError):
        PostgresRelationshipRepository(database).save(invalid)

    assert PostgresRelationshipRepository(database).get(relationship.id) is None
