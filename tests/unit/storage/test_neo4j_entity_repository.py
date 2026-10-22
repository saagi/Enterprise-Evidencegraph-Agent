import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from neo4j.time import DateTime

from app.domain.models import Entity, EntityType, Source
from app.storage.neo4j import Neo4jDatabase
from app.storage.neo4j_repositories import Neo4jEntityRepository


@pytest.fixture
def entity() -> Entity:
    return Entity(
        id="jira:PAY-1842",
        type=EntityType.JIRA_TICKET,
        name="Payment investigation",
        source=Source.JIRA,
        source_id="PAY-1842",
        created_at=datetime(2026, 9, 18, tzinfo=UTC),
        updated_at=datetime(2026, 9, 21, tzinfo=UTC),
        metadata={"nested": {"tags": ["payments", None]}, "enabled": True},
    )


@pytest.fixture
def storage():
    database = MagicMock(spec=Neo4jDatabase)
    session = database.session.return_value.__enter__.return_value
    transaction = MagicMock()
    session.execute_write.side_effect = lambda callback, *args: callback(transaction, *args)
    session.execute_read.side_effect = lambda callback, *args: callback(transaction, *args)
    return Neo4jEntityRepository(database), session, transaction


def test_save_serializes_metadata_and_parameterizes_values(storage, entity):
    repository, session, transaction = storage
    entity = entity.model_copy(update={"name": "A 'quoted' title"})

    repository.save(entity)

    session.execute_write.assert_called_once()
    query = transaction.run.call_args.args[0]
    properties = transaction.run.call_args.kwargs["properties"]
    assert entity.name not in query
    assert "MERGE (entity:Entity {id: $entity_id})" in query
    assert transaction.run.call_args.kwargs["entity_id"] == entity.id
    assert properties == {
        "type": "jira_ticket",
        "name": entity.name,
        "source": "jira",
        "source_id": entity.source_id,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
        "metadata_json": json.dumps(entity.metadata),
    }
    transaction.run.return_value.consume.assert_called_once()


def test_get_restores_domain_entity(storage, entity):
    repository, session, transaction = storage
    properties = entity.model_dump(mode="python", exclude={"metadata"})
    properties["metadata_json"] = json.dumps(entity.metadata)
    properties["created_at"] = DateTime.from_native(entity.created_at)
    properties["updated_at"] = DateTime.from_native(entity.updated_at)
    transaction.run.return_value.single.return_value = {"entity": properties}

    assert repository.get(entity.id) == entity
    session.execute_read.assert_called_once()
    assert transaction.run.call_args.kwargs == {"entity_id": entity.id}


def test_get_missing_entity_returns_none(storage):
    repository, _, transaction = storage
    transaction.run.return_value.single.return_value = None

    assert repository.get("jira:MISSING-1") is None


def test_schema_initialization_is_explicit(storage):
    repository, session, transaction = storage
    session.execute_write.assert_not_called()

    repository.ensure_schema()

    query = transaction.run.call_args.args[0]
    assert "IF NOT EXISTS" in query
    assert "REQUIRE entity.id IS UNIQUE" in query
    transaction.run.return_value.consume.assert_called_once()


def test_save_propagates_database_failure(storage, entity):
    repository, _, transaction = storage
    transaction.run.side_effect = RuntimeError("Write failed")

    with pytest.raises(RuntimeError, match="Write failed"):
        repository.save(entity)
