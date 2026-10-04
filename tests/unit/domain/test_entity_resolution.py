from datetime import UTC, datetime

from app.domain.models import Entity, EntityType, Source
from app.domain.services import (
    EntityCandidate,
    EntityResolutionMethod,
    EntityResolutionStatus,
    EntityResolver,
)


class FakeEntityRepository:
    """In-memory entity repository used only for unit tests."""

    def __init__(self, entities: list[Entity] | None = None) -> None:
        self._entities = {
            entity.id: entity
            for entity in (entities or [])
        }

    def get(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def save(self, entity: Entity) -> None:
        self._entities[entity.id] = entity


def make_jira_entity() -> Entity:
    now = datetime.now(UTC)

    return Entity(
        id="jira:MAPS-1842",
        type=EntityType.JIRA_TICKET,
        name="Fix routing issue",
        source=Source.JIRA,
        source_id="MAPS-1842",
        created_at=now,
        updated_at=now,
    )


def make_candidate(
    normalized_id: str | None = "jira:MAPS-1842",
) -> EntityCandidate:
    return EntityCandidate(
        mention="MAPS-1842",
        entity_type=EntityType.JIRA_TICKET,
        normalized_id=normalized_id,
        source=Source.SLACK,
        artifact_id="artifact:slack:thread:123",
        confidence=0.99,
        context="MAPS-1842 is still blocked.",
    )


def test_resolves_entity_using_exact_canonical_id() -> None:
    entity = make_jira_entity()

    repository = FakeEntityRepository([entity])
    resolver = EntityResolver(repository)

    result = resolver.resolve(make_candidate())

    assert result.status == EntityResolutionStatus.RESOLVED
    assert result.entity_id == "jira:MAPS-1842"
    assert result.entity_type == EntityType.JIRA_TICKET
    assert result.method == EntityResolutionMethod.EXACT_ID
    assert result.confidence == 1.0
    assert result.candidate_ids == ["jira:MAPS-1842"]


def test_returns_unresolved_when_entity_does_not_exist() -> None:
    repository = FakeEntityRepository()
    resolver = EntityResolver(repository)

    result = resolver.resolve(make_candidate())

    assert result.status == EntityResolutionStatus.UNRESOLVED
    assert result.entity_id is None
    assert result.method is None
    assert result.confidence == 0.0
    assert result.candidate_ids == []


def test_returns_unresolved_when_normalized_id_is_missing() -> None:
    repository = FakeEntityRepository()
    resolver = EntityResolver(repository)

    result = resolver.resolve(
        make_candidate(normalized_id=None)
    )

    assert result.status == EntityResolutionStatus.UNRESOLVED
    assert result.entity_id is None
    assert result.method is None
    assert result.confidence == 0.0