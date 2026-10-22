import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values

from app.domain.models import Entity, EntityType, Relationship, RelationshipType, Source
from app.storage.neo4j import Neo4jDatabase
from app.storage.neo4j_repositories import Neo4jEntityRepository, Neo4jGraphRepository


@pytest.fixture
def graph():
    local_env = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    password = os.getenv("NEO4J_PASSWORD") or local_env.get("NEO4J_PASSWORD")
    if not password:
        pytest.skip("NEO4J_PASSWORD is required for live Neo4j tests")
    database = Neo4jDatabase(
        os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
        os.getenv("NEO4J_USERNAME", "neo4j"), password,
        os.getenv("NEO4J_DATABASE", "neo4j"),
    )
    prefix = f"graph-test:{uuid4().hex}:"
    try:
        database.verify_connectivity()
        entities = Neo4jEntityRepository(database)
        repository = Neo4jGraphRepository(database)
        repository.ensure_schema()
        now = datetime(2026, 9, 1, tzinfo=UTC)
        nodes = [Entity(
            id=f"{prefix}{index}", type=EntityType.JIRA_TICKET, name=str(index),
            source=Source.JIRA, source_id=str(index), created_at=now, updated_at=now,
        ) for index in range(4)]
        for node in nodes:
            entities.save(node)
        edge = Relationship(
            id=f"{prefix}edge", source_entity_id=nodes[0].id, target_entity_id=nodes[1].id,
            relationship_type=RelationshipType.REFERENCES, confidence=0.8,
            provenance={"nested": [None, True]}, observed_at=now, created_at=now,
            metadata={"nested": {"value": 1}},
        )
        yield database, repository, nodes, edge
    finally:
        with database.session() as session:
            session.run(
                "MATCH (node) WHERE (node:Entity OR node:RelationshipIdentity) "
                "AND node.id STARTS WITH $prefix DETACH DELETE node", prefix=prefix,
            ).consume()
        database.dispose()


def test_relationship_updates_and_idempotency(graph):
    database, repository, _, edge = graph
    repository.save_relationship(edge)
    repository.save_relationship(edge)
    updated = edge.model_copy(update={"confidence": 0.95, "metadata": {}})
    repository.save_relationship(updated)
    with database.session() as session:
        records = list(session.run(
            "MATCH (source)-[edge {id: $id}]->(target) "
            "RETURN source.id AS source, target.id AS target, type(edge) AS type, edge",
            id=edge.id,
        ))
    assert len(records) == 1
    record = records[0]
    assert record["source"] == edge.source_entity_id
    assert record["target"] == edge.target_entity_id
    assert record["type"] == "REFERENCES"
    assert record["edge"]["confidence"] == 0.95
    assert json.loads(record["edge"]["provenance_json"]) == edge.provenance
    assert json.loads(record["edge"]["metadata_json"]) == {}
    assert record["edge"]["created_at"].to_native() == edge.created_at


def test_missing_endpoint_rolls_back_identity(graph):
    database, repository, _, edge = graph
    edge = edge.model_copy(update={"target_entity_id": "missing"})
    with pytest.raises(ValueError, match="Missing relationship endpoint"):
        repository.save_relationship(edge)
    with database.session() as session:
        record = session.run(
            "MATCH (identity:RelationshipIdentity {id: $id}) RETURN count(identity) AS count",
            id=edge.id,
        ).single(strict=True)
    assert record["count"] == 0


@pytest.mark.parametrize("field", ["source_entity_id", "target_entity_id", "relationship_type"])
def test_identity_conflicts_preserve_existing_edge(graph, field):
    database, repository, nodes, edge = graph
    repository.save_relationship(edge)
    replacement = RelationshipType.MENTIONS if field == "relationship_type" else nodes[2].id
    with pytest.raises(ValueError, match="identity conflict"):
        repository.save_relationship(edge.model_copy(update={field: replacement}))
    with database.session() as session:
        record = session.run(
            "MATCH ()-[edge {id: $id}]->() RETURN count(edge) AS count", id=edge.id,
        ).single(strict=True)
    assert record["count"] == 1
    assert repository.get_neighbors(nodes[0].id) == [nodes[1]]


def test_neighbors_are_bidirectional_distinct_sorted_and_one_hop(graph):
    _, repository, nodes, edge = graph
    repository.save_relationship(edge)
    repository.save_relationship(edge.model_copy(update={
        "id": f"{edge.id}:duplicate-neighbor", "relationship_type": RelationshipType.MENTIONS,
    }))
    repository.save_relationship(edge.model_copy(update={
        "id": f"{edge.id}:incoming", "source_entity_id": nodes[2].id,
        "target_entity_id": nodes[0].id,
    }))
    repository.save_relationship(edge.model_copy(update={
        "id": f"{edge.id}:second-hop", "source_entity_id": nodes[1].id,
        "target_entity_id": nodes[3].id,
    }))
    repository.save_relationship(edge.model_copy(update={
        "id": f"{edge.id}:self", "target_entity_id": nodes[0].id,
    }))
    assert repository.get_neighbors(nodes[0].id) == [nodes[1], nodes[2]]
    assert repository.get_neighbors("missing") == []


def test_concurrent_replays_create_one_edge(graph):
    database, repository, _, edge = graph
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(repository.save_relationship, [edge] * 8))
    with database.session() as session:
        record = session.run(
            "MATCH ()-[edge {id: $id}]->() RETURN count(edge) AS count", id=edge.id,
        ).single(strict=True)
    assert record["count"] == 1


def test_concurrent_conflicting_identities_create_one_winner(graph):
    database, repository, nodes, edge = graph
    conflicting = edge.model_copy(update={"source_entity_id": nodes[2].id})
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(repository.save_relationship, item) for item in (edge, conflicting)]
        errors = [future.exception() for future in futures]
    assert sum(error is None for error in errors) == 1
    assert sum(isinstance(error, ValueError) for error in errors) == 1
    with database.session() as session:
        record = session.run(
            "MATCH ()-[edge {id: $id}]->() RETURN count(edge) AS count", id=edge.id,
        ).single(strict=True)
    assert record["count"] == 1
