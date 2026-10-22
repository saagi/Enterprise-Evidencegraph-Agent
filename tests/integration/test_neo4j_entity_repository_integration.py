import os
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from neo4j.exceptions import ConstraintError

from app.domain.models import Entity, EntityType, Source
from app.storage.neo4j import Neo4jDatabase
from app.storage.neo4j_repositories import Neo4jEntityRepository


@pytest.fixture
def graph():
    local_env = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    password = os.getenv("NEO4J_PASSWORD") or local_env.get("NEO4J_PASSWORD")
    if not password:
        pytest.skip("NEO4J_PASSWORD is required for live Neo4j tests")

    database = Neo4jDatabase(
        uri=os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
        username=os.getenv("NEO4J_USERNAME", "neo4j"),
        password=password,
        database=os.getenv("NEO4J_DATABASE", "neo4j"),
    )
    try:
        database.verify_connectivity()
        repository = Neo4jEntityRepository(database)
        repository.ensure_schema()
        yield database, repository
    finally:
        database.dispose()


@pytest.fixture
def entity(graph, request):
    database, _ = graph
    source = getattr(request, "param", Source.JIRA)
    source_id = f"TEST-{uuid4().hex}"
    entity_type = EntityType.JIRA_TICKET
    if source == Source.GITHUB:
        source_id = f"acme/{source_id}:pr:829"
        entity_type = EntityType.GITHUB_PR
    entity = Entity(
        id=f"{source.value}:{source_id}",
        type=entity_type,
        name="Neo4j integration test",
        source=source,
        source_id=source_id,
        created_at=datetime(2026, 9, 18, 9, 15, 12, 123456, tzinfo=UTC),
        updated_at=datetime(
            2026, 9, 21, 14, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))
        ),
        metadata={"nested": {"tags": ["payments", None]}, "active": True},
    )
    try:
        yield entity
    finally:
        with database.session() as session:
            session.run(
                "MATCH (entity:Entity {id: $entity_id}) DELETE entity",
                entity_id=entity.id,
            ).consume()


@pytest.mark.parametrize("entity", [Source.JIRA, Source.GITHUB], indirect=True)
def test_entity_round_trip(graph, entity):
    _, repository = graph
    repository.save(entity)

    assert repository.get(entity.id) == entity


def test_repeated_saves_update_without_duplicates(graph, entity):
    database, repository = graph
    repository.save(entity)
    repository.save(entity)
    updated = entity.model_copy(
        update={
            "name": "Updated projection",
            "updated_at": entity.updated_at + timedelta(days=1),
            "metadata": {},
        }
    )
    repository.save(updated)

    assert repository.get(entity.id) == updated
    with database.session() as session:
        record = session.run(
            "MATCH (entity:Entity {id: $entity_id}) RETURN count(entity) AS count",
            entity_id=entity.id,
        ).single(strict=True)
        assert record["count"] == 1


def test_missing_entity_returns_none(graph):
    _, repository = graph

    assert repository.get(f"jira:MISSING-{uuid4().hex}") is None


def test_constraint_rejects_duplicate_identity(graph, entity):
    database, repository = graph
    repository.save(entity)

    with pytest.raises(ConstraintError), database.session() as session:
        session.run(
            "CREATE (:Entity {id: $entity_id})",
            entity_id=entity.id,
        ).consume()

    assert repository.get(entity.id) == entity


def test_schema_initialization_is_idempotent(graph):
    _, repository = graph

    repository.ensure_schema()
    repository.ensure_schema()
