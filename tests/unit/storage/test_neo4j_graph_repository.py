import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.domain.models import Relationship, RelationshipType
from app.storage.neo4j import Neo4jDatabase
from app.storage.neo4j_repositories import Neo4jGraphRepository


@pytest.fixture
def relationship():
    return Relationship(
        id="relationship:test",
        source_entity_id="jira:PAY-1",
        target_entity_id="github:acme/pay:pr:1",
        relationship_type=RelationshipType.IMPLEMENTED_BY,
        confidence=0.9,
        provenance={"artifact_id": "jira:PAY-1", "nested": [None, True]},
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        observed_at=datetime(2026, 9, 2, tzinfo=UTC),
        metadata={"tags": ["payments"]},
    )


@pytest.fixture
def storage():
    database = MagicMock(spec=Neo4jDatabase)
    session = database.session.return_value.__enter__.return_value
    transaction = MagicMock()
    session.execute_write.side_effect = lambda callback, *args: callback(transaction, *args)
    session.execute_read.side_effect = lambda callback, *args: callback(transaction, *args)
    return Neo4jGraphRepository(database), transaction


@pytest.mark.parametrize("edge_type", list(RelationshipType))
def test_edge_allowlist_and_properties(storage, relationship, edge_type):
    repository, transaction = storage
    relationship = relationship.model_copy(update={"relationship_type": edge_type})
    transaction.run.return_value.single.return_value = {
        "source_id": relationship.source_entity_id,
        "target_id": relationship.target_entity_id,
        "edge_type": edge_type.value.upper(),
    }

    repository.save_relationship(relationship)

    query = transaction.run.call_args.args[0]
    params = transaction.run.call_args.kwargs
    assert f"[edge:{edge_type.value.upper()}" in query
    assert relationship.id not in query
    assert params["relationship_id"] == relationship.id
    assert json.loads(params["properties"]["provenance_json"]) == relationship.provenance
    assert json.loads(params["properties"]["metadata_json"]) == relationship.metadata


def test_identity_conflict_rejected_before_edge_write(storage, relationship):
    repository, transaction = storage
    transaction.run.return_value.single.return_value = {
        "source_id": "jira:OTHER-1", "target_id": relationship.target_entity_id,
        "edge_type": "IMPLEMENTED_BY",
    }

    with pytest.raises(ValueError, match="identity conflict"):
        repository.save_relationship(relationship)
    assert transaction.run.call_count == 1


def test_missing_endpoint_raises_within_transaction(storage, relationship):
    repository, transaction = storage
    transaction.run.return_value.single.side_effect = [
        {"source_id": relationship.source_entity_id,
         "target_id": relationship.target_entity_id, "edge_type": "IMPLEMENTED_BY"},
        None,
    ]
    with pytest.raises(ValueError, match="Missing relationship endpoint"):
        repository.save_relationship(relationship)


def test_neighbors_query_is_distinct_bidirectional_and_ordered(storage):
    repository, transaction = storage
    transaction.run.return_value = []
    assert repository.get_neighbors("jira:PAY-1") == []
    query = transaction.run.call_args.args[0]
    assert "RETURN DISTINCT neighbor AS entity ORDER BY entity.id" in query
    assert "]-(neighbor:Entity)" in query
    assert "WHERE neighbor.id <> $entity_id" in query


def test_schema_contains_community_identity_constraint(storage):
    repository, transaction = storage
    transaction.run.assert_not_called()
    repository.ensure_schema()
    assert transaction.run.call_count == 2
    assert "REQUIRE identity.id IS UNIQUE" in transaction.run.call_args.args[0]
