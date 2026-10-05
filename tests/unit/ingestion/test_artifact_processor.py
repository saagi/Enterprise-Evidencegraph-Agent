from datetime import UTC, datetime

from app.domain.entity_registry import create_default_entity_registry
from app.domain.models import CanonicalArtifact, Entity, EntityType, Source
from app.domain.services import EntityResolutionStatus, EntityResolver
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
    now = datetime.now(UTC)

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
                    "body": "PAY-1842 appears related to token refresh handling.",
                },
                {
                    "id": "comment-102",
                    "body": "Fix is being implemented in PR #829.",
                },
            ],
        },
        metadata={},
        created_at=now,
        updated_at=now,
    )

def test_processor_identifies_resolved_and_unresolved_entities() -> None:
    entity = make_pay_entity()

    repository = FakeEntityRepository([entity])

    processor = ArtifactProcessor(
        entity_registry=create_default_entity_registry(),
        entity_resolver=EntityResolver(repository),
    )

    result = processor.process(make_artifact())

    assert result.artifact_id == "artifact:jira:PAY-1842"

    # Only canonical entities that successfully resolved appear here.
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

    assert len(resolved) == 3
    assert all(
        resolution.entity_id == "jira:PAY-1842"
        for resolution in resolved
    )

    assert len(unresolved) == 1

    assert unresolved[0].mention == "PR #829"
    assert unresolved[0].entity_type == EntityType.GITHUB_PR
    assert unresolved[0].entity_id is None


def test_processor_deduplicates_same_entity_mentions() -> None:
    entity = make_pay_entity()

    repository = FakeEntityRepository([entity])

    processor = ArtifactProcessor(
        entity_registry=create_default_entity_registry(),
        entity_resolver=EntityResolver(repository),
    )

    result = processor.process(make_artifact())

    assert len(result.entities) == 1
    assert result.entities[0].id == "jira:PAY-1842"


def test_processor_keeps_unresolved_references() -> None:
    repository = FakeEntityRepository()

    processor = ArtifactProcessor(
        entity_registry=create_default_entity_registry(),
        entity_resolver=EntityResolver(repository),
    )

    result = processor.process(make_artifact())

    assert result.entities == []

    assert len(result.entity_resolutions) >= 1

    assert all(
        resolution.status == EntityResolutionStatus.UNRESOLVED
        for resolution in result.entity_resolutions
    )