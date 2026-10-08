
from datetime import UTC, datetime
from typing import Protocol

from app.domain.entity_registry import create_default_entity_registry
from app.domain.models import (
    CanonicalArtifact,
    Entity,
    EntityType,
    Relationship,
    RelationshipType,
    Source,
)
from app.domain.services import (
    EntityResolutionResult,
    EntityResolutionStatus,
    EntityResolver,
    EventExtractor,
    EvidenceExtractor,
    RelationshipCandidate,
    RelationshipExtractionResult,
)
from app.ingestion.processor import ArtifactProcessor


class FakeEntityRepository:
    """In-memory entity repository for unit tests."""

    def __init__(
        self,
        entities: dict[str, Entity] | None = None,
    ) -> None:
        self.entities = entities or {}

    def get(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    def save(self, entity: Entity) -> None:
        self.entities[entity.id] = entity


class RelationshipExtractorContract(Protocol):
    """Minimal relationship extraction contract for testing."""

    def extract(
        self,
        *,
        artifact: CanonicalArtifact,
        primary_entity: Entity,
        resolutions: list[EntityResolutionResult],
    ) -> RelationshipExtractionResult:
        ...


class FakeRelationshipExtractor:
    """Fake extractor for processor orchestration tests."""

    def __init__(
        self,
        result: RelationshipExtractionResult,
    ) -> None:
        self.result = result
        self.call_count = 0
        self.received_primary_entity: Entity | None = None

    def extract(
        self,
        *,
        artifact: CanonicalArtifact,
        primary_entity: Entity,
        resolutions: list[EntityResolutionResult],
    ) -> RelationshipExtractionResult:
        self.call_count += 1
        self.received_primary_entity = primary_entity
        return self.result


def make_jira_entity() -> Entity:
    return Entity(
        id="jira:PAY-1842",
        type=EntityType.JIRA_TICKET,
        name="Payment requests fail after authentication token refresh",
        source=Source.JIRA,
        source_id="PAY-1842",
        created_at=datetime(2026, 9, 18, 9, 15, tzinfo=UTC),
        updated_at=datetime(2026, 9, 20, 14, 30, tzinfo=UTC),
    )


def make_artifact() -> CanonicalArtifact:
    return CanonicalArtifact(
        id="artifact:jira:PAY-1842",
        source=Source.JIRA,
        source_id="PAY-1842",
        artifact_type="jira_ticket",
        title="PAY-1842: Payment failure investigation",
        content={
            "summary": "Payment requests fail after token refresh",
            "description": (
                "PAY-1842 is under investigation."
            ),
            "status": "In Progress",
            "comments": [
                {
                    "id": "comment-101",
                    "author": "Alice Chen",
                    "created": "2026-09-19T11:20:00Z",
                    "body": "The issue appears related to token refresh handling.",
                },
                {
                    "id": "comment-102",
                    "author": "Bob Rao",
                    "created": "2026-09-20T14:30:00Z",
                    "body": "Fix is being implemented in PR #829.",
                },
            ],
        },
        metadata={},
        created_at=datetime(2026, 9, 18, 9, 15, tzinfo=UTC),
        updated_at=datetime(2026, 9, 20, 14, 30, tzinfo=UTC),
    )


def make_processor(
    repository: FakeEntityRepository,
    relationship_extractor: RelationshipExtractorContract | None = None,
) -> ArtifactProcessor:
    return ArtifactProcessor(
        entity_registry=create_default_entity_registry(),
        entity_resolver=EntityResolver(repository),
        event_extractor=EventExtractor(),
        evidence_extractor=EvidenceExtractor(),
        relationship_extractor=relationship_extractor,
    )


# ---------------------------------------------------------------------------
# Existing processor behavior
# ---------------------------------------------------------------------------


def test_processor_identifies_resolved_and_unresolved_entities() -> None:
    repository = FakeEntityRepository(
        entities={
            "jira:PAY-1842": make_jira_entity(),
        }
    )

    processor = make_processor(repository)
    result = processor.process(make_artifact())

    resolved = [
        item
        for item in result.entity_resolutions
        if item.status == EntityResolutionStatus.RESOLVED
    ]

    unresolved = [
        item
        for item in result.entity_resolutions
        if item.status == EntityResolutionStatus.UNRESOLVED
    ]

    assert len(resolved) == 2
    assert len(unresolved) == 1

    assert unresolved[0].mention == "PR #829"
    assert len(result.entities) == 1
    assert result.entities[0].id == "jira:PAY-1842"

    assert len(result.events) == 4
    assert len(result.evidence) == 3


def test_processor_deduplicates_same_entity_mentions() -> None:
    repository = FakeEntityRepository(
        entities={
            "jira:PAY-1842": make_jira_entity(),
        }
    )

    processor = make_processor(repository)
    result = processor.process(make_artifact())

    assert len(result.entities) == 1
    assert result.entities[0].id == "jira:PAY-1842"


def test_processor_keeps_unresolved_references() -> None:
    repository = FakeEntityRepository()

    processor = make_processor(repository)
    result = processor.process(make_artifact())

    assert result.entities == []

    assert all(
        item.status == EntityResolutionStatus.UNRESOLVED
        for item in result.entity_resolutions
    )

    assert result.events == []
    assert result.evidence == []
    assert result.relationship_candidates == []
    assert result.relationships == []


# ---------------------------------------------------------------------------
# Relationship extraction integration
# ---------------------------------------------------------------------------


def test_processor_returns_validated_relationship() -> None:
    repository = FakeEntityRepository(
        entities={
            "jira:PAY-1842": make_jira_entity(),
        }
    )

    candidate = RelationshipCandidate(
        source_entity_id="jira:PAY-1842",
        target_mention="PR #829",
        relationship_type=RelationshipType.IMPLEMENTED_BY,
        confidence=0.96,
        evidence_text="Fix is being implemented in PR #829.",
    )

    relationship = Relationship(
        id=(
            "relationship:jira:PAY-1842:"
            "implemented_by:github:payments-api:pr:829"
        ),
        source_entity_id="jira:PAY-1842",
        target_entity_id="github:payments-api:pr:829",
        relationship_type=RelationshipType.IMPLEMENTED_BY,
        confidence=0.96,
        provenance={
            "method": "llm_semantic_extraction",
            "artifact_id": "artifact:jira:PAY-1842",
        },
        observed_at=datetime(2026, 9, 20, 14, 30, tzinfo=UTC),
        created_at=datetime(2026, 9, 20, 14, 30, tzinfo=UTC),
    )

    fake_extractor = FakeRelationshipExtractor(
        RelationshipExtractionResult(
            candidates=[candidate],
            relationships=[relationship],
        )
    )

    processor = make_processor(
        repository,
        relationship_extractor=fake_extractor,
    )

    result = processor.process(make_artifact())

    assert result.relationship_candidates == [candidate]
    assert result.relationships == [relationship]
    assert fake_extractor.call_count == 1
    assert fake_extractor.received_primary_entity is not None
    assert fake_extractor.received_primary_entity.id == "jira:PAY-1842"


def test_processor_keeps_unresolved_relationship_candidate() -> None:
    repository = FakeEntityRepository(
        entities={
            "jira:PAY-1842": make_jira_entity(),
        }
    )

    candidate = RelationshipCandidate(
        source_entity_id="jira:PAY-1842",
        target_mention="PR #829",
        relationship_type=RelationshipType.IMPLEMENTED_BY,
        confidence=0.96,
        evidence_text="Fix is being implemented in PR #829.",
    )

    fake_extractor = FakeRelationshipExtractor(
        RelationshipExtractionResult(
            candidates=[candidate],
            relationships=[],
        )
    )

    processor = make_processor(
        repository,
        relationship_extractor=fake_extractor,
    )

    result = processor.process(make_artifact())

    assert result.relationship_candidates == [candidate]
    assert result.relationships == []
    assert fake_extractor.call_count == 1


def test_processor_skips_relationship_extraction_when_disabled() -> None:
    repository = FakeEntityRepository(
        entities={
            "jira:PAY-1842": make_jira_entity(),
        }
    )

    processor = make_processor(repository)

    result = processor.process(make_artifact())

    assert result.relationship_candidates == []
    assert result.relationships == []

    assert len(result.entities) == 1
    assert len(result.events) == 4
    assert len(result.evidence) == 3


def test_processor_skips_relationship_extraction_without_resolved_entities() -> None:
    repository = FakeEntityRepository()

    fake_extractor = FakeRelationshipExtractor(
        RelationshipExtractionResult()
    )

    processor = make_processor(
        repository,
        relationship_extractor=fake_extractor,
    )

    result = processor.process(make_artifact())

    assert fake_extractor.call_count == 0
    assert result.relationship_candidates == []
    assert result.relationships == []
