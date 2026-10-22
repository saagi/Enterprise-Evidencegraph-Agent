from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.domain.models import Entity, EntityType, Relationship, RelationshipType, Source
from app.storage.graph_projection import PostgresGraphProjection
from app.storage.postgres import PostgresDatabase


def snapshot():
    timestamp = datetime(2026, 9, 21, tzinfo=UTC)
    entity = Entity(
        id="jira:TEST-1",
        type=EntityType.JIRA_TICKET,
        name="Test",
        source=Source.JIRA,
        source_id="TEST-1",
        created_at=timestamp,
        updated_at=timestamp,
    )
    relationship = Relationship(
        id="relationship:test",
        source_entity_id=entity.id,
        relationship_type=RelationshipType.REFERENCES,
        target_entity_id=entity.id,
        confidence=1,
        provenance={"artifact_id": "artifact:test"},
        observed_at=timestamp,
        created_at=timestamp,
    )
    return entity, relationship


def test_replay_validates_snapshot_and_saves_entities_before_relationships():
    entity, relationship = snapshot()
    database = MagicMock(spec=PostgresDatabase)
    session = database.session.return_value.__enter__.return_value
    # Deliberately reverse input order; projection still writes entities first.
    session.execute.return_value.all.return_value = [
        SimpleNamespace(kind="relationship", data=relationship.model_dump(mode="json")),
        SimpleNamespace(kind="entity", data=entity.model_dump(mode="json")),
    ]
    operations = MagicMock()
    projection = PostgresGraphProjection(database, operations.entities, operations.graph)

    projection.replay()

    assert operations.mock_calls == [
        ("entities.save", (entity,), {}),
        ("graph.save_relationship", (relationship,), {}),
    ]
    assert "pg_advisory_xact_lock" in str(session.execute.call_args_list[0].args[0])


def test_invalid_snapshot_makes_no_graph_writes():
    entity, _ = snapshot()
    database = MagicMock(spec=PostgresDatabase)
    session = database.session.return_value.__enter__.return_value
    session.execute.return_value.all.return_value = [
        SimpleNamespace(kind="entity", data=entity.model_dump(mode="json")),
        SimpleNamespace(kind="relationship", data={"id": "invalid"}),
    ]
    operations = MagicMock()

    with pytest.raises(ValidationError):
        PostgresGraphProjection(database, operations.entities, operations.graph).replay()

    assert operations.mock_calls == []


def test_graph_failure_releases_postgres_transaction_for_retry():
    entity, _ = snapshot()
    database = MagicMock(spec=PostgresDatabase)
    session = database.session.return_value.__enter__.return_value
    session.execute.return_value.all.return_value = [
        SimpleNamespace(kind="entity", data=entity.model_dump(mode="json"))
    ]
    entities = MagicMock()
    entities.save.side_effect = RuntimeError("Graph unavailable")

    with pytest.raises(RuntimeError, match="Graph unavailable"):
        PostgresGraphProjection(database, entities, MagicMock()).replay()

    database.session.return_value.__exit__.assert_called_once()
