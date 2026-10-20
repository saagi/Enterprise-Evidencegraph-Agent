
from typing import Protocol

from app.domain.interfaces import EntityRepository
from app.domain.models import (
    CanonicalArtifact,
    Entity,
    EntityType,
    Source,
)
from app.ingestion.connectors import SourceConnector, SourceRecord
from app.ingestion.processor import ArtifactProcessor, ProcessingResult


class IngestionPersistence(Protocol):
    """Persists an ingestion result atomically."""

    def persist(
        self,
        artifact: CanonicalArtifact,
        result: ProcessingResult,
    ) -> None:
        ...


class IngestionOrchestrator:
    """
    Coordinates ingestion from a source connector.

    Flow:
        1. Normalize the source record.
        2. Build the primary entity in memory.
        3. Process the artifact without writing to PostgreSQL.
        4. Persist the complete result in one transaction.
    """

    def __init__(
        self,
        connector: SourceConnector,
        entity_repository: EntityRepository,
        processor: ArtifactProcessor,
        persistence: IngestionPersistence,
    ) -> None:
        self._connector = connector
        self._entity_repository = entity_repository
        self._processor = processor
        self._persistence = persistence

    def ingest(self, record: SourceRecord) -> ProcessingResult:
        artifact = self._connector.normalize(record)

        primary_entity = self._build_primary_entity(artifact)

        result = self._processor.process(
            artifact,
            primary_entity=primary_entity,
        )

        self._persistence.persist(
            artifact,
            result,
        )

        return result

    def _build_primary_entity(
        self,
        artifact: CanonicalArtifact,
    ) -> Entity:
        entity_id = f"{artifact.source.value}:{artifact.source_id}"

        existing = self._entity_repository.get(entity_id)

        entity_type = self._get_entity_type(artifact.source)

        created_at = (
            existing.created_at
            if existing is not None
            else artifact.created_at
        )

        metadata = {
            **(existing.metadata if existing is not None else {}),
            **artifact.metadata,
            "artifact_id": artifact.id,
        }

        return Entity(
            id=entity_id,
            type=entity_type,
            name=artifact.title or artifact.source_id,
            source=artifact.source,
            source_id=artifact.source_id,
            created_at=created_at,
            updated_at=artifact.updated_at,
            metadata=metadata,
        )

    @staticmethod
    def _get_entity_type(source: Source) -> EntityType:
        if source == Source.JIRA:
            return EntityType.JIRA_TICKET

        if source == Source.GITHUB:
            return EntityType.GITHUB_PR

        raise ValueError(
            f"Unsupported source for primary entity: {source.value}"
        )
