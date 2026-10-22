from sqlalchemy import text

from app.domain.interfaces import EntityRepository, GraphRepository
from app.domain.models import Entity, Relationship
from app.storage.postgres import PostgresDatabase


class PostgresGraphProjection:
    """Replay committed canonical records; partial graph writes are safe to retry.

    Full replay is intentionally small-scale and upsert-only. Deletion propagation
    and a background outbox worker are separate future capabilities.
    """

    # Serialize cooperating replay workers, including workers in other processes.
    _LOCK_ID = 485871826375

    def __init__(
        self,
        database: PostgresDatabase,
        entities: EntityRepository,
        graph: GraphRepository,
    ) -> None:
        self._database = database
        self._entities = entities
        self._graph = graph

    def replay(self) -> None:
        with self._database.session() as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": self._LOCK_ID},
            )
            # One SQL statement gives both record sets the same committed snapshot.
            # Read it after the lock so a waiting worker cannot replay an old snapshot.
            records = session.execute(
                text(
                    "SELECT kind, data FROM ("
                    "SELECT 'entity' AS kind, to_jsonb(entity) AS data "
                    "FROM entities AS entity "
                    "UNION ALL "
                    "SELECT 'relationship' AS kind, to_jsonb(relationship) AS data "
                    "FROM relationships AS relationship) AS snapshot "
                    "ORDER BY kind, data->>'id'"
                )
            ).all()
            # Validate the full snapshot before starting graph writes.
            entities = [
                Entity.model_validate(record.data)
                for record in records
                if record.kind == "entity"
            ]
            relationships = [
                Relationship.model_validate(record.data)
                for record in records
                if record.kind == "relationship"
            ]
            for entity in entities:
                self._entities.save(entity)
            for relationship in relationships:
                self._graph.save_relationship(relationship)
