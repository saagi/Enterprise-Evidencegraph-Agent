from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.interfaces import EntityRepository
from app.domain.models import Entity, EntityType, Source


class EntityResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    INFERRED = "inferred"
    UNRESOLVED = "unresolved"


class EntityResolutionMethod(StrEnum):
    EXACT_ID = "exact_id"
    SOURCE_ID = "source_id"
    METADATA = "metadata"
    CONTEXT = "context"
    LLM = "llm"


class EntityCandidate(BaseModel):
    """Potential entity reference detected inside an artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mention: str
    entity_type: EntityType | None = None

    normalized_id: str | None = None

    source: Source
    artifact_id: str

    confidence: float = Field(ge=0.0, le=1.0)

    context: str | None = None


class EntityResolutionResult(BaseModel):
    """Result of attempting to resolve an entity candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mention: str

    entity_id: str | None = None
    entity_type: EntityType | None = None

    status: EntityResolutionStatus
    confidence: float = Field(ge=0.0, le=1.0)

    method: EntityResolutionMethod | None = None

    candidate_ids: list[str] = Field(default_factory=list)


class EntityResolver:
    """Resolves entity candidates to canonical entities."""

    def __init__(self, entity_repository: EntityRepository) -> None:
            self._entity_repository = entity_repository
    
    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entity_repository.get(entity_id)

    def resolve(self, candidate: EntityCandidate) -> EntityResolutionResult:
        if candidate.normalized_id is None:
            return self._unresolved(candidate)

        # Step 1: canonical ID lookup
        entity = self._entity_repository.get(candidate.normalized_id)

        if entity is not None:
            return self._resolved(
                candidate=candidate,
                entity=entity,
                method=EntityResolutionMethod.EXACT_ID,
                confidence=1.0,
            )

        return self._unresolved(candidate)

    @staticmethod
    def _resolved(
        candidate: EntityCandidate,
        entity: Entity,
        method: EntityResolutionMethod,
        confidence: float,
    ) -> EntityResolutionResult:
        return EntityResolutionResult(
            mention=candidate.mention,
            entity_id=entity.id,
            entity_type=entity.type,
            status=EntityResolutionStatus.RESOLVED,
            confidence=confidence,
            method=method,
            candidate_ids=[entity.id],
        )

    @staticmethod
    def _unresolved(
        candidate: EntityCandidate,
    ) -> EntityResolutionResult:
        return EntityResolutionResult(
            mention=candidate.mention,
            entity_id=None,
            entity_type=candidate.entity_type,
            status=EntityResolutionStatus.UNRESOLVED,
            confidence=0.0,
            method=None,
            candidate_ids=[],
        )