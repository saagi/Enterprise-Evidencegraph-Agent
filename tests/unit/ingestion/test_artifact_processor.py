from datetime import UTC, datetime

from app.domain.entity_registry import create_default_entity_registry
from app.domain.models import (
    CanonicalArtifact,
    Entity,
    EntityType,
    EventType,
    Source,
)
from app.domain.services import (
    EntityResolutionStatus,
    EntityResolver,
    EventExtractor,
    EvidenceExtractor,
)

from app.ingestion.processor import ArtifactProcessor


class FakeEntityRepository:
    def __init__(self, entities: list[Entity] | None = None) -> None:
        self._entities = {
            entity.id: entity
            for entity in (entities or [])
        }

    def get(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def save(self, entity: Entity) -> None:
        self._entities[entity.id] = entity


def make_pay_entity() -> Entity:
    now = datetime.now(UTC)

    return Entity(
        id="jira:PAY-1842",
        type=EntityType.JIRA_TICKET,
        name="Payment requests fail after authentication token refresh",
        source=Source.JIRA,
        source_id="PAY-1842",
        created_at=now,
        updated_at=now,
    )


def make_artifact() -> CanonicalArtifact:
    return CanonicalArtifact(
        id="artifact:jira:PAY-1842",
        source=Source.JIRA,
        source_id="PAY-1842",
        artifact_type="jira_ticket",
        title="PAY-1842 payment failure investigation",
        content={
            "summary": "Payment requests fail after token refresh",
            "description": "PAY-1842 is currently under investigation.",
            "status": "In Progress",
            "comments": [
                {
                    "id": "comment-101",
                    "author": {
                        "displayName": "Alice Chen",
                    },
                    "created": "2026-09-19T11:20:00Z",
                    "body": (
                        "PAY-1842 appears related to token "
                        "refresh handling."
                    ),
                },
                {
                    "id": "comment-102",
                    "author": {
                        "displayName": "Bob Rao",
                    },
                    "created": "2026-09-20T14:30:00Z",
                    "body": "Fix is being implemented in PR #829.",
                },
            ],
        },
        metadata={},
        created_at=datetime(
            2026, 9, 18, 9, 15, tzinfo=UTC
        ),
        updated_at=datetime(
            2026, 9, 20, 14, 30, tzinfo=UTC
        ),
    )


def make_processor(
    repository: FakeEntityRepository,
) -> ArtifactProcessor:
    return ArtifactProcessor(
        entity_registry=create_default_entity_registry(),
        entity_resolver=EntityResolver(repository),
        event_extractor=EventExtractor(),
        evidence_extractor=EvidenceExtractor(),
    )


def test_processor_identifies_resolved_and_unresolved_entities() -> None:
    entity = make_pay_entity()
    repository = FakeEntityRepository([entity])
    processor = make_processor(repository)

    result = processor.process(make_artifact())

    assert result.artifact_id == "artifact:jira:PAY-1842"

    # PAY-1842 resolves to one canonical entity.
    assert len(result.entities) == 1
    assert result.entities[0].id == "jira:PAY-1842"

    resolved = [
        resolution
        for resolution in result.entity_resolutions
        if resolution.status == EntityResolutionStatus.RESOLVED
    ]

    unresolved = [
        resolution
        for resolution in result.entity_resolutions
        if resolution.status == EntityResolutionStatus.UNRESOLVED
    ]

    # PAY-1842 appears three times in the searchable artifact text.
    assert len(resolved) == 3

    assert all(
        resolution.entity_id == "jira:PAY-1842"
        for resolution in resolved
    )

    # PR #829 is identified but cannot yet be canonically resolved
    # because repository context is unavailable.
    assert len(unresolved) == 1

    assert unresolved[0].mention == "PR #829"
    assert unresolved[0].entity_type == EntityType.GITHUB_PR
    assert unresolved[0].entity_id is None

    # The resolved Jira entity allows deterministic event extraction.
    assert len(result.events) == 4

    assert len(result.evidence) == 3

    assert [
        event.event_type
        for event in result.events
    ] == [
        EventType.CREATED,
        EventType.UPDATED,
        EventType.COMMENT_ADDED,
        EventType.COMMENT_ADDED,
    ]


def test_processor_deduplicates_same_entity_mentions() -> None:
    entity = make_pay_entity()
    repository = FakeEntityRepository([entity])
    processor = make_processor(repository)

    result = processor.process(make_artifact())

    # PAY-1842 occurs multiple times in the artifact,
    # but represents one canonical entity.
    assert len(result.entities) == 1
    assert result.entities[0].id == "jira:PAY-1842"


def test_processor_keeps_unresolved_references() -> None:
    repository = FakeEntityRepository()
    processor = make_processor(repository)

    result = processor.process(make_artifact())

    # Nothing can be resolved to a canonical entity.
    assert result.entities == []

    assert len(result.entity_resolutions) >= 1

    assert all(
        resolution.status == EntityResolutionStatus.UNRESOLVED
        for resolution in result.entity_resolutions
    )

    # Events require a canonical entity to attach to.
    assert result.events == []
    assert result.evidence == []