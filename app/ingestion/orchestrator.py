
from typing import Protocol

from app.domain.interfaces import EntityRepository
from app.domain.models import (
    CanonicalArtifact,
    Entity,
    EntityType,
    Source,
)
from app.ingestion.connectors import (
    SourceConnector,
    SourceRecord,
)
from app.ingestion.processor import (
    ArtifactProcessor,
    ProcessingResult,
)


class EntityWriter(Protocol):
    """Write capability required by ingestion."""

    def upsert(self, entity: Entity) -> None:
        ...


class IngestionOrchestrator:
    """Normalize records and process them with a verified primary entity."""

    def __init__(
        self,
        connector: SourceConnector,
        entity_repository: EntityRepository,
        entity_writer: EntityWriter,
        processor: ArtifactProcessor,
    ) -> None:
        self._connector = connector
        self._entity_repository = entity_repository
        self._entity_writer = entity_writer
        self._processor = processor

    def ingest(self, record: SourceRecord) -> ProcessingResult:
        artifact = self._connector.normalize(record)

        primary_entity = self._build_primary_entity(artifact)

        # Upsert before processing so the resolver can find
        # the artifact's primary entity.
        self._entity_writer.upsert(primary_entity)

        return self._processor.process(artifact)

    def _build_primary_entity(
        self,
        artifact: CanonicalArtifact,
    ) -> Entity:
        entity_id = (
            f"{artifact.source.value}:{artifact.source_id}"
        )

        existing = self._entity_repository.get_entity(entity_id)

        entity_type = self._get_entity_type(artifact.source)

        created_at = (
            existing.created_at
            if existing is not None
            else artifact.created_at
        )

        return Entity(
            id=entity_id,
            type=entity_type,
            name=artifact.title or artifact.source_id,
            source=artifact.source,
            source_id=artifact.source_id,
            created_at=created_at,
            updated_at=artifact.updated_at,
            metadata={
                **(existing.metadata if existing is not None else {}),
                **artifact.metadata,
                "artifact_id": artifact.id,
            },
        )

    @staticmethod
    def _get_entity_type(source: Source) -> EntityType:
        if source == Source.JIRA:
            return EntityType.JIRA_TICKET

        if source == Source.GITHUB:
            return EntityType.GITHUB_PR

        raise ValueError(
            f"Unsupported source for V1 ingestion: {source}"
        )
