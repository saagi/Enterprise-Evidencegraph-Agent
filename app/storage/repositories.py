
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain.models import (
    CanonicalArtifact,
    Entity,
    Event,
    Evidence,
    Relationship,
    RelationshipType,
)
from app.storage.postgres import PostgresDatabase
from app.storage.schema import (
    ArtifactRow,
    EntityRow,
    EventRow,
    EvidenceRow,
    RelationshipRow,
)

T = TypeVar("T", bound=BaseModel)


class PostgresRelationshipRepository:
    """Canonical relationship storage; endpoint/type identity is immutable."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save(self, relationship: Relationship) -> None:
        with self._database.session() as session:
            self.save_in_session(session, relationship)

    @staticmethod
    def save_in_session(session: Session, relationship: Relationship) -> None:
        values = relationship.model_dump(mode="python")
        values["metadata_"] = values.pop("metadata")
        statement = insert(RelationshipRow).values(**values)
        excluded = statement.excluded
        upsert_statement = statement.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "confidence": excluded.confidence,
                "provenance": excluded.provenance,
                "observed_at": excluded.observed_at,
                "metadata": excluded.metadata,
            },
            where=(
                (RelationshipRow.source_entity_id == excluded.source_entity_id)
                & (RelationshipRow.relationship_type == excluded.relationship_type)
                & (RelationshipRow.target_entity_id == excluded.target_entity_id)
            ),
        ).returning(RelationshipRow.id)
        if session.scalar(upsert_statement) is None:
            raise ValueError("Relationship ID already belongs to different endpoints or type")

    def get(self, relationship_id: str) -> Relationship | None:
        with self._database.session() as session:
            row = session.get(RelationshipRow, relationship_id)
            if row is None:
                return None
            return self._from_row(row)

    def list_all(self) -> list[Relationship]:
        with self._database.session() as session:
            return [
                self._from_row(row)
                for row in session.scalars(select(RelationshipRow).order_by(RelationshipRow.id))
            ]

    @staticmethod
    def _from_row(row: RelationshipRow) -> Relationship:
        return Relationship(
            id=row.id,
            source_entity_id=row.source_entity_id,
            relationship_type=RelationshipType(row.relationship_type),
            target_entity_id=row.target_entity_id,
            confidence=row.confidence,
            provenance=row.provenance,
            observed_at=row.observed_at,
            created_at=row.created_at,
            metadata=row.metadata_,
        )


def _serialize(model: BaseModel) -> dict:
    """Preserve native datetime values for SQLAlchemy."""
    return model.model_dump(mode="python")



def _upsert(session, row_class, values: dict) -> None:
    """Insert or update a record using PostgreSQL ON CONFLICT."""

    stmt = insert(row_class).values(**values)

    update_values = {
        column.name: stmt.excluded[column.name]
        for column in row_class.__table__.columns
        if column.name != "id"
    }

    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_=update_values,
    )

    session.execute(stmt)



class PostgresArtifactRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def upsert(self, artifact: CanonicalArtifact) -> None:
        values = _serialize(artifact)
        values["metadata_"] = values.pop("metadata")

        with self._database.session() as session:
            _upsert(session, ArtifactRow, values)

    def get_artifact(
        self,
        artifact_id: str,
    ) -> CanonicalArtifact | None:
        with self._database.session() as session:
            row = session.get(ArtifactRow, artifact_id)

            if row is None:
                return None

            return CanonicalArtifact.model_validate(
                {
                    "id": row.id,
                    "source": row.source,
                    "source_id": row.source_id,
                    "artifact_type": row.artifact_type,
                    "title": row.title,
                    "content": row.content,
                    "metadata": row.metadata_,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
            )


class PostgresEntityRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get(self, entity_id: str) -> Entity | None:
        return self.get_entity(entity_id)

    def save(self, entity: Entity) -> None:
        self.upsert(entity)

    def upsert(self, entity: Entity) -> None:
        values = _serialize(entity)
        values["metadata_"] = values.pop("metadata")

        with self._database.session() as session:
            _upsert(session, EntityRow, values)

    def get_entity(self, entity_id: str) -> Entity | None:
        with self._database.session() as session:
            row = session.get(EntityRow, entity_id)

            if row is None:
                return None

            return Entity.model_validate(
                {
                    "id": row.id,
                    "type": row.type,
                    "name": row.name,
                    "source": row.source,
                    "source_id": row.source_id,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                    "metadata": row.metadata_,
                }
            )


class PostgresEventRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def upsert(self, event: Event) -> None:
        values = _serialize(event)
        values["metadata_"] = values.pop("metadata")

        with self._database.session() as session:
            _upsert(session, EventRow, values)

    def get_events(
        self,
        entity_id: str,
    ) -> list[Event]:
        with self._database.session() as session:
            rows = session.scalars(
                select(EventRow)
                .where(EventRow.entity_id == entity_id)
                .order_by(EventRow.timestamp.desc())
            ).all()

            return [
                Event.model_validate(
                    {
                        "id": row.id,
                        "entity_id": row.entity_id,
                        "event_type": row.event_type,
                        "timestamp": row.timestamp,
                        "source": row.source,
                        "source_id": row.source_id,
                        "data": row.data,
                        "metadata": row.metadata_,
                        "evidence_id": row.evidence_id,
                        "created_at": row.created_at,
                    }
                )
                for row in rows
            ]


class PostgresEvidenceRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def upsert(self, evidence: Evidence) -> None:
        values = _serialize(evidence)
        values["metadata_"] = values.pop("metadata")
        values["location"] = evidence.location.model_dump(mode="json")

        with self._database.session() as session:
            _upsert(session, EvidenceRow, values)
            

    def get_evidence(
        self,
        evidence_id: str,
    ) -> Evidence | None:
        with self._database.session() as session:
            row = session.get(EvidenceRow, evidence_id)

            if row is None:
                return None

            return Evidence.model_validate(
                {
                    "id": row.id,
                    "entity_ids": row.entity_ids,
                    "source": row.source,
                    "source_id": row.source_id,
                    "evidence_type": row.evidence_type,
                    "claim": row.claim,
                    "content": row.content,
                    "timestamp": row.timestamp,
                    "location": row.location,
                    "metadata": row.metadata_,
                    "created_at": row.created_at,
                }
            )

    def get_evidence_for_entity(
        self,
        entity_id: str,
    ) -> list[Evidence]:
        with self._database.session() as session:
            rows = session.scalars(
                select(EvidenceRow)
                .where(
                    EvidenceRow.entity_ids.contains([entity_id])
                )
                .order_by(EvidenceRow.timestamp.desc())
            ).all()

            return [
                Evidence.model_validate(
                    {
                        "id": row.id,
                        "entity_ids": row.entity_ids,
                        "source": row.source,
                        "source_id": row.source_id,
                        "evidence_type": row.evidence_type,
                        "claim": row.claim,
                        "content": row.content,
                        "timestamp": row.timestamp,
                        "location": row.location,
                        "metadata": row.metadata_,
                        "created_at": row.created_at,
                    }
                )
                for row in rows
            ]
