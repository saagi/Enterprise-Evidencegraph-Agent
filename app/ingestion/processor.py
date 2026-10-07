from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import (
    CanonicalArtifact,
    Entity,
    Event,
    Evidence,
)
from app.domain.entity_registry import EntityIdentificationRegistry

from app.domain.services import (
    EntityResolutionResult,
    EntityResolutionStatus,
    EntityResolver,
    EventExtractor,
    EvidenceExtractor,
)


class ProcessingResult(BaseModel):
    """Domain objects and resolution results produced from an artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str
    entities: list[Entity] = Field(default_factory=list)
    entity_resolutions: list[EntityResolutionResult] = Field(
        default_factory=list
    )
    events: list[Event] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class ArtifactProcessor:
    """Processes canonical artifacts into domain-level information."""

    def __init__(
    self,
    entity_registry: EntityIdentificationRegistry,
    entity_resolver: EntityResolver,
    event_extractor: EventExtractor,
    evidence_extractor: EvidenceExtractor,
) -> None:
        self._entity_registry = entity_registry
        self._entity_resolver = entity_resolver
        self._event_extractor = event_extractor
        self._evidence_extractor = evidence_extractor

    def process(self, artifact: CanonicalArtifact) -> ProcessingResult:
        text = self._extract_searchable_text(artifact)

        candidates = self._entity_registry.identify(
            text=text,
            source=artifact.source,
            artifact_id=artifact.id,
        )

        resolutions = [
            self._entity_resolver.resolve(candidate)
            for candidate in candidates
        ]

        entities = self._get_resolved_entities(resolutions)

        events = self._event_extractor.extract(
            artifact=artifact,
            entity_ids=[
                entity.id
                for entity in entities
            ],
        )

        evidence = self._evidence_extractor.extract(
            artifact=artifact,
            entity_ids=[
                entity.id
                for entity in entities
            ],
        )

        return ProcessingResult(
            artifact_id=artifact.id,
            entities=entities,
            entity_resolutions=resolutions,
            events=events,
            evidence=evidence,
        )

    def _get_resolved_entities(
        self,
        resolutions: list[EntityResolutionResult],
    ) -> list[Entity]:
        entities: list[Entity] = []
        seen_entity_ids: set[str] = set()

        for resolution in resolutions:
            if resolution.status != EntityResolutionStatus.RESOLVED:
                continue

            if resolution.entity_id is None:
                continue

            if resolution.entity_id in seen_entity_ids:
                continue

            entity = self._entity_resolver.get_entity(
                resolution.entity_id
            )

            if entity is None:
                continue

            entities.append(entity)
            seen_entity_ids.add(entity.id)

        return entities

    @staticmethod
    def _extract_searchable_text(
        artifact: CanonicalArtifact,
    ) -> str:
        parts: list[str] = []

        if artifact.title:
            parts.append(artifact.title)

        summary = artifact.content.get("summary")
        if isinstance(summary, str):
            parts.append(summary)

        description = artifact.content.get("description")
        if isinstance(description, str):
            parts.append(description)

        comments = artifact.content.get("comments", [])

        if isinstance(comments, list):
            for comment in comments:
                if not isinstance(comment, dict):
                    continue

                body = comment.get("body")

                if isinstance(body, str):
                    parts.append(body)

        return "\n".join(parts)