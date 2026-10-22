import json
from typing import Any

from neo4j import ManagedTransaction
from neo4j.time import DateTime

from app.domain.models import Entity
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

        properties = dict(record["entity"])
        properties["metadata"] = json.loads(properties.pop("metadata_json"))
        for field in ("created_at", "updated_at"):
            if isinstance(properties[field], DateTime):
                properties[field] = properties[field].to_native()
        return Entity.model_validate(properties)
