
from pydantic import BaseModel, ConfigDict, Field

from app.domain.entity_registry import EntityIdentificationRegistry
from app.domain.models import (
    CanonicalArtifact,
    Entity,
    Event,
    Evidence,
    Relationship,
)
from app.domain.services import (
    EntityResolutionResult,
    EntityResolutionStatus,
    EntityResolver,
    EventExtractor,
    EvidenceExtractor,
    RelationshipCandidate,
    RelationshipExtractor,
)


class ProcessingResult(BaseModel):
    """Domain objects and resolution results produced from an artifact."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    artifact_id: str
    entities: list[Entity] = Field(default_factory=list)
    entity_resolutions: list[EntityResolutionResult] = Field(
        default_factory=list
    )
    events: list[Event] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    relationship_candidates: list[RelationshipCandidate] = Field(
        default_factory=list
    )
    relationships: list[Relationship] = Field(default_factory=list)


class ArtifactProcessor:
    """Processes canonical artifacts into domain-level information."""

    def __init__(
        self,
        entity_registry: EntityIdentificationRegistry,
        entity_resolver: EntityResolver,
        event_extractor: EventExtractor,
        evidence_extractor: EvidenceExtractor,
        relationship_extractor: RelationshipExtractor | None = None,
    ) -> None:
        self._entity_registry = entity_registry
        self._entity_resolver = entity_resolver
        self._event_extractor = event_extractor
        self._evidence_extractor = evidence_extractor
        self._relationship_extractor = relationship_extractor

    def process(
    self,
    artifact: CanonicalArtifact,
    primary_entity: Entity | None = None,
) -> ProcessingResult:
        # ---------------------------------------------------------
        # 1. Identify entity mentions
        # ---------------------------------------------------------

        text = self._extract_searchable_text(artifact)

        candidates = self._entity_registry.identify(
            text=text,
            source=artifact.source,
            artifact_id=artifact.id,
        )

        # ---------------------------------------------------------
        # 2. Resolve entity mentions
        # ---------------------------------------------------------

        resolutions = [
            self._entity_resolver.resolve(candidate)
            for candidate in candidates
        ]

        entities = self._get_resolved_entities(resolutions)

        # ---------------------------------------------------------
        # 3. Identify the artifact's primary entity
        # ---------------------------------------------------------

        primary_entity_id = f"{artifact.source.value}:{artifact.source_id}"

        if primary_entity is not None:
            if primary_entity.id != primary_entity_id:
                raise ValueError(
                    "Provided primary entity does not match artifact identity"
                )
        else:
            primary_entity = self._entity_resolver.get_entity(
                primary_entity_id
            )

        if primary_entity is not None:
            for index, entity in enumerate(entities):
                if entity.id == primary_entity.id:
                    entities[index] = primary_entity
                    break
            else:
                entities.insert(0, primary_entity)

        # ---------------------------------------------------------
        # 4. Extract source-owned events and evidence
        # ---------------------------------------------------------

        events: list[Event] = []
        evidence: list[Evidence] = []

        # Never attribute events/evidence to a referenced entity
        # when the artifact's own primary entity is missing.
        if primary_entity is not None:
            resolved_entity_ids = [
                entity.id for entity in entities
            ]

            events = self._event_extractor.extract(
                artifact=artifact,
                entity_ids=resolved_entity_ids,
                primary_entity_id=primary_entity.id,
            )

            evidence = self._evidence_extractor.extract(
                artifact=artifact,
                entity_ids=resolved_entity_ids,
                primary_entity_id=primary_entity.id,
            )

        # ---------------------------------------------------------
        # 5. Extract semantic relationships (optional LLM)
        # ---------------------------------------------------------

        relationship_candidates: list[
            RelationshipCandidate
        ] = []

        relationships: list[Relationship] = []

        if (
            self._relationship_extractor is not None
            and primary_entity is not None
        ):
            relationship_result = (
                self._relationship_extractor.extract(
                    artifact=artifact,
                    primary_entity=primary_entity,
                    resolutions=resolutions,
                )
            )

            relationship_candidates = (
                relationship_result.candidates
            )

            relationships = (
                relationship_result.relationships
            )

        # ---------------------------------------------------------
        # 6. Return processing result
        # ---------------------------------------------------------

        return ProcessingResult(
            artifact_id=artifact.id,
            entities=entities,
            entity_resolutions=resolutions,
            events=events,
            evidence=evidence,
            relationship_candidates=relationship_candidates,
            relationships=relationships,
        )

    def _get_resolved_entities(
        self,
        resolutions: list[EntityResolutionResult],
    ) -> list[Entity]:
        """Retrieve unique canonical entities from resolution results."""

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
        """Collect searchable text from a canonical artifact."""

        parts: list[str] = []

        if artifact.title:
            parts.append(artifact.title)

        summary = artifact.content.get("summary")
        if isinstance(summary, str):
            parts.append(summary)

        description = artifact.content.get("description")
        if isinstance(description, str):
            parts.append(description)

        body = artifact.content.get("body")
        if isinstance(body, str):
            parts.append(body)

        comments = artifact.content.get("comments", [])

        if isinstance(comments, list):
            for comment in comments:
                if not isinstance(comment, dict):
                    continue

                comment_body = comment.get("body")

                if isinstance(comment_body, str):
                    parts.append(comment_body)

        return "\n".join(parts)
