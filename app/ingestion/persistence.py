
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain.models import CanonicalArtifact
from app.ingestion.processor import ProcessingResult
from app.storage.postgres import PostgresDatabase
from app.storage.schema import (
    ArtifactRow,
    EntityRow,
    EventRow,
    EvidenceRow,
)


class PostgresPersistenceService:
    """
    Persist an artifact and its extracted records atomically.

    A single transaction ensures that partial ingestion
    results are not committed to PostgreSQL.
    """

    def __init__(self, database: PostgresDatabase):
        self._database = database

    def persist(
        self,
        artifact: CanonicalArtifact,
        result: ProcessingResult,
    ) -> None:
        if result.artifact_id != artifact.id:
            raise ValueError(
                "ProcessingResult artifact_id does not match artifact.id"
            )

        with self._database.session() as session:
            self._upsert_artifact(session, artifact)

            for entity in result.entities:
                self._upsert_model(session, EntityRow, entity)

            for evidence in result.evidence:
                self._upsert_model(session, EvidenceRow, evidence)

            for event in result.events:
                self._upsert_model(session, EventRow, event)

    @staticmethod
    def _upsert_artifact(
        session: Session,
        artifact: CanonicalArtifact,
    ) -> None:
        PostgresPersistenceService._upsert_model(
            session,
            ArtifactRow,
            artifact,
        )

    @staticmethod
    def _upsert_model(
        session: Session,
        row_class,
        model,
    ) -> None:
        values = model.model_dump(mode="python")

        # The ORM attribute is metadata_, while the
        # underlying PostgreSQL column is metadata.
        values["metadata_"] = values.pop("metadata", {})

        # JSONB must receive JSON-serializable values.
        if isinstance(model, object) and hasattr(model, "location"):
            location = getattr(model, "location")
            values["location"] = (
                location.model_dump(mode="json")
                if location is not None
                else None
            )

        stmt = insert(row_class).values(**values)

        # Use physical database column names in EXCLUDED.
        updates = {
            column.name: stmt.excluded[column.name]
            for column in row_class.__table__.columns
            if column.name not in {"id", "created_at"}
        }

        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_=updates,
        )

        session.execute(stmt)
