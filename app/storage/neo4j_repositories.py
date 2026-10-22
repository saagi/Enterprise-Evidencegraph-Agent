import json
from typing import Any

from neo4j import ManagedTransaction
from neo4j.time import DateTime

from app.domain.models import Entity, Relationship, RelationshipType
from app.storage.neo4j import Neo4jDatabase


class Neo4jEntityRepository:
    """Project canonical entities into Neo4j using their PostgreSQL identities."""

    def __init__(self, database: Neo4jDatabase) -> None:
        self._database = database

    def ensure_schema(self) -> None:
        """Initialize the identity constraint before using the repository."""
        with self._database.session() as session:
            session.execute_write(self._ensure_schema)

    @staticmethod
    def _ensure_schema(transaction: ManagedTransaction) -> None:
        transaction.run(
            "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS "
            "FOR (entity:Entity) REQUIRE entity.id IS UNIQUE"
        ).consume()

    def save(self, entity: Entity) -> None:
        """Insert or refresh a projection from the supplied canonical entity."""
        properties = {
            "type": entity.type.value,
            "name": entity.name,
            "source": entity.source.value,
            "source_id": entity.source_id,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
            "metadata_json": json.dumps(entity.metadata),
        }
        with self._database.session() as session:
            session.execute_write(self._save, entity.id, properties)

    @staticmethod
    def _save(
        transaction: ManagedTransaction,
        entity_id: str,
        properties: dict[str, Any],
    ) -> None:
        transaction.run(
            "MERGE (entity:Entity {id: $entity_id}) "
            "SET entity += $properties",
            entity_id=entity_id,
            properties=properties,
        ).consume()

    def get(self, entity_id: str) -> Entity | None:
        with self._database.session() as session:
            return session.execute_read(self._get, entity_id)

    @staticmethod
    def _get(transaction: ManagedTransaction, entity_id: str) -> Entity | None:
        record = transaction.run(
            "MATCH (entity:Entity {id: $entity_id}) RETURN entity",
            entity_id=entity_id,
        ).single()
        if record is None:
            return None

        return _entity_from_properties(dict(record["entity"]))


def _entity_from_properties(properties: dict[str, Any]) -> Entity:
    properties["metadata"] = json.loads(properties.pop("metadata_json"))
    for field in ("created_at", "updated_at"):
        if isinstance(properties[field], DateTime):
            properties[field] = properties[field].to_native()
    return Entity.model_validate(properties)


_RELATIONSHIP_TYPES = {
    RelationshipType.BELONGS_TO: "BELONGS_TO",
    RelationshipType.DISCUSSED_IN: "DISCUSSED_IN",
    RelationshipType.IMPLEMENTED_BY: "IMPLEMENTED_BY",
    RelationshipType.RELATED_TO: "RELATED_TO",
    RelationshipType.REFERENCES: "REFERENCES",
    RelationshipType.MENTIONS: "MENTIONS",
}


class Neo4jGraphRepository:
    """Project canonical relationships and traverse one hop in either direction.

    An identity node serializes writes for each canonical relationship ID across
    edge types. This works with Neo4j Community without relationship constraints.
    """

    def __init__(self, database: Neo4jDatabase) -> None:
        self._database = database

    def ensure_schema(self) -> None:
        Neo4jEntityRepository(self._database).ensure_schema()
        with self._database.session() as session:
            session.execute_write(self._ensure_schema)

    @staticmethod
    def _ensure_schema(transaction: ManagedTransaction) -> None:
        transaction.run(
            "CREATE CONSTRAINT relationship_identity_unique IF NOT EXISTS "
            "FOR (identity:RelationshipIdentity) REQUIRE identity.id IS UNIQUE"
        ).consume()

    def save_relationship(self, relationship: Relationship) -> None:
        edge_type = _RELATIONSHIP_TYPES[relationship.relationship_type]
        properties = {
            "confidence": relationship.confidence,
            "provenance_json": json.dumps(relationship.provenance),
            "observed_at": relationship.observed_at,
            "created_at": relationship.created_at,
            "metadata_json": json.dumps(relationship.metadata),
        }
        with self._database.session() as session:
            session.execute_write(self._save_relationship, relationship, edge_type, properties)

    @staticmethod
    def _save_relationship(
        transaction: ManagedTransaction,
        relationship: Relationship,
        edge_type: str,
        properties: dict[str, Any],
    ) -> None:
        # MERGE + dependent SET acquires a write lock held through transaction
        # completion, including the subsequent identity check and edge MERGE.
        record = transaction.run(
            "MERGE (identity:RelationshipIdentity {id: $relationship_id}) "
            "ON CREATE SET identity.source_entity_id = $source_id, "
            "identity.target_entity_id = $target_id, identity.edge_type = $edge_type "
            "SET identity.id = identity.id "
            "RETURN identity.source_entity_id AS source_id, "
            "identity.target_entity_id AS target_id, identity.edge_type AS edge_type",
            relationship_id=relationship.id,
            source_id=relationship.source_entity_id,
            target_id=relationship.target_entity_id,
            edge_type=edge_type,
        ).single(strict=True)
        if (
            record["source_id"] != relationship.source_entity_id
            or record["target_id"] != relationship.target_entity_id
            or record["edge_type"] != edge_type
        ):
            raise ValueError(f"Relationship identity conflict: {relationship.id}")
        edge_record = transaction.run(
            "MATCH (source:Entity {id: $source_id}), (target:Entity {id: $target_id}) "
            f"MERGE (source)-[edge:{edge_type} {{id: $relationship_id}}]->(target) "
            "SET edge += $properties RETURN edge.id AS id",
            source_id=relationship.source_entity_id,
            target_id=relationship.target_entity_id,
            relationship_id=relationship.id,
            properties=properties,
        ).single()
        if edge_record is None:
            raise ValueError(f"Missing relationship endpoint: {relationship.id}")

    def get_neighbors(self, entity_id: str) -> list[Entity]:
        with self._database.session() as session:
            return session.execute_read(self._get_neighbors, entity_id)

    @staticmethod
    def _get_neighbors(transaction: ManagedTransaction, entity_id: str) -> list[Entity]:
        # Only canonical edge types participate; helper identity nodes are isolated.
        edge_types = "|".join(_RELATIONSHIP_TYPES.values())
        records = transaction.run(
            f"MATCH (entity:Entity {{id: $entity_id}})-[:{edge_types}]-(neighbor:Entity) "
            "WHERE neighbor.id <> $entity_id "
            "RETURN DISTINCT neighbor AS entity ORDER BY entity.id",
            entity_id=entity_id,
        )
        return [_entity_from_properties(dict(record["entity"])) for record in records]
