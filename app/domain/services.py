from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.interfaces import EntityRepository
from app.domain.models import (
    CanonicalArtifact,
    Entity,
    EntityType,
    Event,
    EventType,
    Evidence,
    EvidenceLocation,
    EvidenceType,
    Relationship,
    RelationshipType,
    Source,
)
from app.models.gateway import LLMGateway


# ---------------------------------------------------------------------------
# Entity Resolution
# ---------------------------------------------------------------------------


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

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    mention: str
    entity_type: EntityType | None = None
    normalized_id: str | None = None
    source: Source
    artifact_id: str
    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )
    context: str | None = None


class EntityResolutionResult(BaseModel):
    """Result of attempting to resolve an entity candidate."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    mention: str
    entity_id: str | None = None
    entity_type: EntityType | None = None
    status: EntityResolutionStatus
    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )
    method: EntityResolutionMethod | None = None
    candidate_ids: list[str] = Field(
        default_factory=list
    )


class EntityResolver:
    """Resolves entity candidates to canonical entities."""

    def __init__(
        self,
        entity_repository: EntityRepository,
    ) -> None:
        self._entity_repository = entity_repository

    def get_entity(
        self,
        entity_id: str,
    ) -> Entity | None:
        return self._entity_repository.get(entity_id)

    def resolve(
        self,
        candidate: EntityCandidate,
    ) -> EntityResolutionResult:
        if candidate.normalized_id is None:
            return self._unresolved(candidate)

        entity = self._entity_repository.get(
            candidate.normalized_id
        )

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


# ---------------------------------------------------------------------------
# Event Extraction
# ---------------------------------------------------------------------------


class EventExtractor:
    """Extracts deterministic events from canonical artifacts."""

    def extract(
        self,
        artifact: CanonicalArtifact,
        entity_ids: list[str],
    ) -> list[Event]:
        if artifact.source == Source.JIRA:
            return self._extract_jira_events(
                artifact=artifact,
                entity_ids=entity_ids,
            )

        return []

    def _extract_jira_events(
        self,
        artifact: CanonicalArtifact,
        entity_ids: list[str],
    ) -> list[Event]:
        if not entity_ids:
            return []

        primary_entity_id = entity_ids[0]

        events = [
            Event(
                id=f"event:{artifact.id}:created",
                entity_id=primary_entity_id,
                event_type=EventType.CREATED,
                timestamp=artifact.created_at,
                source=artifact.source,
                source_id=artifact.source_id,
                data={},
                created_at=artifact.created_at,
            ),
            Event(
                id=f"event:{artifact.id}:updated",
                entity_id=primary_entity_id,
                event_type=EventType.UPDATED,
                timestamp=artifact.updated_at,
                source=artifact.source,
                source_id=artifact.source_id,
                data={
                    "status": artifact.content.get(
                        "status"
                    ),
                },
                created_at=artifact.updated_at,
            ),
        ]

        comments = artifact.content.get(
            "comments",
            [],
        )

        if not isinstance(comments, list):
            return events

        for comment in comments:
            if not isinstance(comment, dict):
                continue

            event = self._create_comment_event(
                artifact=artifact,
                entity_id=primary_entity_id,
                comment=comment,
            )

            if event is not None:
                events.append(event)

        return events

    @staticmethod
    def _create_comment_event(
        artifact: CanonicalArtifact,
        entity_id: str,
        comment: dict[str, Any],
    ) -> Event | None:
        comment_id = comment.get("id")
        created = comment.get("created")

        if not isinstance(comment_id, str):
            return None

        if not isinstance(created, str):
            return None

        timestamp = datetime.fromisoformat(
            created.replace(
                "Z",
                "+00:00",
            )
        )

        return Event(
            id=(
                f"event:{artifact.id}:"
                f"comment:{comment_id}"
            ),
            entity_id=entity_id,
            event_type=EventType.COMMENT_ADDED,
            timestamp=timestamp,
            source=artifact.source,
            source_id=comment_id,
            data={
                "body": comment.get("body"),
                "author": comment.get("author"),
            },
            created_at=timestamp,
        )


# ---------------------------------------------------------------------------
# Evidence Extraction
# ---------------------------------------------------------------------------


class EvidenceExtractor:
    """Extracts deterministic evidence from canonical artifacts."""

    def extract(
        self,
        artifact: CanonicalArtifact,
        entity_ids: list[str],
    ) -> list[Evidence]:
        if artifact.source == Source.JIRA:
            return self._extract_jira_evidence(
                artifact=artifact,
                entity_ids=entity_ids,
            )

        return []

    def _extract_jira_evidence(
        self,
        artifact: CanonicalArtifact,
        entity_ids: list[str],
    ) -> list[Evidence]:
        if not entity_ids:
            return []

        primary_entity_id = entity_ids[0]

        evidence: list[Evidence] = []

        status = artifact.content.get("status")

        if isinstance(status, str):
            evidence.append(
                Evidence(
                    id=(
                        f"evidence:"
                        f"{artifact.id}:status"
                    ),
                    entity_ids=[
                        primary_entity_id
                    ],
                    source=artifact.source,
                    source_id=artifact.source_id,
                    evidence_type=(
                        EvidenceType.STATUS_UPDATE
                    ),
                    claim=(
                        f"Ticket status is {status}"
                    ),
                    content=status,
                    timestamp=artifact.updated_at,
                    location=EvidenceLocation(
                        artifact_id=artifact.id,
                    ),
                    created_at=artifact.updated_at,
                )
            )

        comments = artifact.content.get(
            "comments",
            [],
        )

        if not isinstance(comments, list):
            return evidence

        for comment in comments:
            if not isinstance(comment, dict):
                continue

            comment_evidence = (
                self._create_comment_evidence(
                    artifact=artifact,
                    entity_id=primary_entity_id,
                    comment=comment,
                )
            )

            if comment_evidence is not None:
                evidence.append(
                    comment_evidence
                )

        return evidence

    @staticmethod
    def _create_comment_evidence(
        artifact: CanonicalArtifact,
        entity_id: str,
        comment: dict[str, Any],
    ) -> Evidence | None:
        comment_id = comment.get("id")
        body = comment.get("body")
        created = comment.get("created")

        if not isinstance(comment_id, str):
            return None

        if not isinstance(body, str):
            return None

        if not isinstance(created, str):
            return None

        timestamp = datetime.fromisoformat(
            created.replace(
                "Z",
                "+00:00",
            )
        )

        return Evidence(
            id=(
                f"evidence:{artifact.id}:"
                f"comment:{comment_id}"
            ),
            entity_ids=[entity_id],
            source=artifact.source,
            source_id=comment_id,
            evidence_type=EvidenceType.COMMENT,
            claim=body,
            content=body,
            timestamp=timestamp,
            location=EvidenceLocation(
                artifact_id=artifact.id,
            ),
            metadata={
                "author": comment.get("author"),
            },
            created_at=timestamp,
        )


# ---------------------------------------------------------------------------
# Relationship Extraction
# ---------------------------------------------------------------------------


class ExtractedRelationship(BaseModel):
    """Single relationship proposed by semantic extraction."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    source_mention: str
    target_mention: str
    relationship_type: RelationshipType
    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )
    evidence_text: str


class RelationshipExtractionOutput(BaseModel):
    """Structured relationship output expected from the LLM."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    relationships: list[
        ExtractedRelationship
    ] = Field(
        default_factory=list
    )


class RelationshipCandidate(BaseModel):
    """Potential relationship awaiting canonical entity validation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    source_entity_id: str
    target_mention: str
    relationship_type: RelationshipType
    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )
    evidence_text: str


class RelationshipExtractionResult(BaseModel):
    """Result of semantic relationship extraction."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    candidates: list[
        RelationshipCandidate
    ] = Field(
        default_factory=list
    )

    relationships: list[
        Relationship
    ] = Field(
        default_factory=list
    )


class RelationshipExtractor:
    """Extracts semantic relationships with LLM assistance."""

    def __init__(
        self,
        llm_gateway: LLMGateway,
    ) -> None:
        self._llm_gateway = llm_gateway

    def extract(
        self,
        *,
        artifact: CanonicalArtifact,
        primary_entity: Entity,
        resolutions: list[
            EntityResolutionResult
        ],
    ) -> RelationshipExtractionResult:
        output = (
            self._llm_gateway.generate_structured(
                system_prompt=self._system_prompt(),
                user_prompt=self._build_user_prompt(
                    artifact=artifact,
                    primary_entity=primary_entity,
                ),
                output_model=(
                    RelationshipExtractionOutput
                ),
            )
        )

        candidates: list[
            RelationshipCandidate
        ] = []

        relationships: list[
            Relationship
        ] = []

        for extracted in output.relationships:
            candidate = RelationshipCandidate(
                source_entity_id=primary_entity.id,
                target_mention=(
                    extracted.target_mention
                ),
                relationship_type=(
                    extracted.relationship_type
                ),
                confidence=extracted.confidence,
                evidence_text=(
                    extracted.evidence_text
                ),
            )

            candidates.append(candidate)

            target_entity_id = (
                self._find_resolved_entity_id(
                    mention=(
                        extracted.target_mention
                    ),
                    resolutions=resolutions,
                )
            )

            if target_entity_id is None:
                continue

            relationships.append(
                Relationship(
                    id=(
                        f"relationship:"
                        f"{primary_entity.id}:"
                        f"{extracted.relationship_type.value}:"
                        f"{target_entity_id}"
                    ),
                    source_entity_id=(
                        primary_entity.id
                    ),
                    relationship_type=(
                        extracted.relationship_type
                    ),
                    target_entity_id=(
                        target_entity_id
                    ),
                    confidence=(
                        extracted.confidence
                    ),
                    provenance={
                        "artifact_id": artifact.id,
                        "method": (
                            "llm_semantic_extraction"
                        ),
                        "evidence_text": (
                            extracted.evidence_text
                        ),
                    },
                    observed_at=artifact.updated_at,
                    created_at=artifact.updated_at,
                )
            )

        return RelationshipExtractionResult(
            candidates=candidates,
            relationships=relationships,
        )

    @staticmethod
    def _find_resolved_entity_id(
        *,
        mention: str,
        resolutions: list[
            EntityResolutionResult
        ],
    ) -> str | None:
        normalized_mention = (
            mention.strip().lower()
        )

        for resolution in resolutions:
            if (
                resolution.status
                != EntityResolutionStatus.RESOLVED
            ):
                continue

            if resolution.entity_id is None:
                continue

            if (
                resolution.mention
                .strip()
                .lower()
                == normalized_mention
            ):
                return resolution.entity_id

        return None

    @staticmethod
    def _system_prompt() -> str:
        return """
You extract relationships between enterprise artifacts.

Use only information explicitly supported by the provided artifact.

Allowed relationship types:
- belongs_to
- discussed_in
- implemented_by
- related_to
- references
- mentions

Do not invent entities or relationships.

The source entity is already known.
Extract relationships from the source entity to other entities
explicitly mentioned in the artifact.

Use implemented_by only when the text indicates that another
artifact contains or implements the fix/change.

Return no relationship when the evidence is insufficient.
""".strip()

    @staticmethod
    def _build_user_prompt(
        *,
        artifact: CanonicalArtifact,
        primary_entity: Entity,
    ) -> str:
        return (
            f"Source entity: "
            f"{primary_entity.id}\n"
            f"Source entity name: "
            f"{primary_entity.name}\n"
            f"Artifact title: "
            f"{artifact.title}\n"
            f"Artifact content:\n"
            f"{artifact.content}"
        )