
from datetime import UTC, datetime
from typing import Protocol
from unittest.mock import Mock

import pytest

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
    ExtractedRelationship,
    RelationshipCandidate,
    RelationshipExtractionOutput,
    RelationshipExtractionResult,
    RelationshipExtractor,
)
from app.ingestion.processor import ArtifactProcessor
from app.models.gateway import LLMGateway


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



def test_github_events_and_evidence_belong_to_pr() -> None:
    pr_id = "github:acme/payments-api:pr:829"
    jira_id = "jira:PAY-1842"

    now = datetime(2026, 9, 21, 16, 45, tzinfo=UTC)

    pr_entity = Entity(
        id=pr_id,
        type=EntityType.GITHUB_PR,
        name="Fix payment failures after token refresh",
        source=Source.GITHUB,
        source_id="acme/payments-api:pr:829",
        created_at=now,
        updated_at=now,
    )

    repository = FakeEntityRepository(
        entities={
            jira_id: make_jira_entity(),
            pr_id: pr_entity,
        }
    )

    artifact = CanonicalArtifact(
        id="artifact:github:acme/payments-api:pr:829",
        source=Source.GITHUB,
        source_id="acme/payments-api:pr:829",
        artifact_type="github_pr",
        title="Fix payment failures",
        content={
            "body": "Fixes PAY-1842.",
            "state": "closed",
            "merged": True,
            "merged_at": "2026-09-21T16:45:00Z",
            "closed_at": "2026-09-21T16:45:00Z",
            "base_branch": "main",
            "head_branch": "fix/payment-token-refresh",
        },
        metadata={
            "url": "https://github.com/acme/payments-api/pull/829",
        },
        created_at=datetime(2026, 9, 19, 10, 30, tzinfo=UTC),
        updated_at=now,
    )

    processor = make_processor(repository)
    result = processor.process(artifact)

    assert jira_id in [entity.id for entity in result.entities]
    assert pr_id in [entity.id for entity in result.entities]

    assert len(result.events) == 3
    assert len(result.evidence) == 2

    assert all(
        event.entity_id == pr_id
        for event in result.events
    )

    assert all(
        evidence.entity_ids == [pr_id]
        for evidence in result.evidence
    )


def test_missing_primary_entity_does_not_misattribute_github_events() -> None:
    jira_entity = make_jira_entity()

    repository = FakeEntityRepository(
        entities={jira_entity.id: jira_entity}
    )

    artifact = CanonicalArtifact(
        id="artifact:github:acme/payments-api:pr:829",
        source=Source.GITHUB,
        source_id="acme/payments-api:pr:829",
        artifact_type="github_pr",
        title="Fix PAY-1842",
        content={
            "body": "Fixes PAY-1842.",
            "merged": True,
            "merged_at": "2026-09-21T16:45:00Z",
            "closed_at": "2026-09-21T16:45:00Z",
        },
        created_at=datetime(2026, 9, 19, tzinfo=UTC),
        updated_at=datetime(2026, 9, 21, tzinfo=UTC),
    )

    result = make_processor(repository).process(artifact)

    assert [entity.id for entity in result.entities] == [
        "jira:PAY-1842"
    ]

    assert result.events == []
    assert result.evidence == []
    assert result.relationships == []


# ---------------------------------------------------------------------------
# In-memory primary entity processing (atomic ingestion preparation)
# ---------------------------------------------------------------------------


def test_processes_in_memory_primary_entity() -> None:
    artifact = make_artifact()
    repository = FakeEntityRepository()
    primary_entity = make_jira_entity()

    result = make_processor(repository).process(
        artifact, primary_entity=primary_entity
    )

    assert repository.get(primary_entity.id) is None
    assert [entity.id for entity in result.entities].count(primary_entity.id) == 1
    assert len(result.events) == 4
    assert all(event.entity_id == primary_entity.id for event in result.events)
    assert len(result.evidence) == 3
    assert all(primary_entity.id in item.entity_ids for item in result.evidence)


def test_rejects_mismatched_primary_entity() -> None:
    artifact = make_artifact()
    repository = FakeEntityRepository()
    wrong_entity = make_jira_entity().model_copy(
        update={"id": "jira:PAY-9999"}
    )

    with pytest.raises(ValueError, match="primary entity"):
        make_processor(repository).process(
            artifact, primary_entity=wrong_entity
        )


def test_does_not_duplicate_supplied_primary_entity() -> None:
    artifact = make_artifact()
    primary_entity = make_jira_entity()
    repository = FakeEntityRepository(
        entities={primary_entity.id: primary_entity}
    )

    result = make_processor(repository).process(
        artifact, primary_entity=primary_entity
    )

    assert [entity.id for entity in result.entities].count(primary_entity.id) == 1


def test_supplied_primary_entity_replaces_stored_version() -> None:
    stored_entity = make_jira_entity()
    repository = FakeEntityRepository(
        entities={stored_entity.id: stored_entity}
    )
    refreshed_entity = stored_entity.model_copy(
        update={
            "name": "Updated payment investigation",
            "updated_at": datetime(2026, 9, 21, tzinfo=UTC),
            "metadata": {"priority": "High"},
        }
    )

    result = make_processor(repository).process(
        make_artifact(),
        primary_entity=refreshed_entity,
    )

    primary_entities = [
        entity
        for entity in result.entities
        if entity.id == refreshed_entity.id
    ]
    assert primary_entities == [refreshed_entity]
    assert repository.get(stored_entity.id) == stored_entity


def make_pr_entity(repository: str, number: int = 829) -> Entity:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    source_id = f"{repository}:pr:{number}"
    return Entity(
        id=f"github:{source_id}",
        type=EntityType.GITHUB_PR,
        name="Payment fix",
        source=Source.GITHUB,
        source_id=source_id,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize("target_exists", [True, False])
def test_github_pr_reference_resolves_only_in_artifact_repository(
    target_exists: bool,
) -> None:
    target = make_pr_entity("acme/payments-api")
    other = make_pr_entity("other/payments-api")
    entities = {other.id: other}
    if target_exists:
        entities[target.id] = target
    primary = make_pr_entity("acme/payments-api", number=100)
    artifact = CanonicalArtifact(
        id=f"artifact:{primary.id}",
        source=Source.GITHUB,
        source_id=primary.source_id,
        artifact_type="github_pr",
        title="Follow-up",
        content={"body": "Follow up on PR #829."},
        metadata={"repository": "acme/payments-api"},
        created_at=primary.created_at,
        updated_at=primary.updated_at,
    )

    result = make_processor(FakeEntityRepository(entities)).process(
        artifact, primary_entity=primary
    )

    resolution = result.entity_resolutions[0]
    assert resolution.entity_id == (target.id if target_exists else None)
    assert other.id not in [entity.id for entity in result.entities]


def test_jira_pr_number_stays_unresolved_even_with_matching_entities() -> None:
    first = make_pr_entity("acme/payments-api")
    second = make_pr_entity("other/payments-api")
    artifact = make_artifact().model_copy(
        update={"metadata": {"repository": "acme/payments-api"}}
    )

    result = make_processor(
        FakeEntityRepository({first.id: first, second.id: second})
    ).process(artifact, primary_entity=make_jira_entity())

    resolution = next(item for item in result.entity_resolutions if item.mention == "PR #829")
    assert resolution.status == EntityResolutionStatus.UNRESOLVED
    assert resolution.entity_id is None


def test_jira_explicit_pr_url_resolves_repository_scoped_entity() -> None:
    target = make_pr_entity("acme/payments-api")
    url = "https://github.com/acme/payments-api/pull/829"
    artifact = make_artifact().model_copy(
        update={"content": {"description": f"Fix implemented by {url}."}}
    )

    result = make_processor(FakeEntityRepository({target.id: target})).process(
        artifact, primary_entity=make_jira_entity()
    )

    resolution = next(item for item in result.entity_resolutions if item.mention == url)
    assert resolution.entity_id == target.id
    assert target.id in [entity.id for entity in result.entities]


@pytest.mark.parametrize("explicit_url", [True, False])
def test_real_relationship_extractor_uses_repository_aware_resolution(
    explicit_url: bool,
) -> None:
    target = make_pr_entity("acme/payments-api")
    other = make_pr_entity("other/payments-api")
    mention = (
        "https://github.com/acme/payments-api/pull/829"
        if explicit_url
        else "PR #829"
    )
    artifact = make_artifact().model_copy(
        update={"content": {"description": f"Fix implemented by {mention}."}}
    )
    gateway = Mock(spec=LLMGateway)
    gateway.generate_structured.return_value = RelationshipExtractionOutput(
        relationships=[
            ExtractedRelationship(
                source_mention="PAY-1842",
                target_mention=mention,
                relationship_type=RelationshipType.IMPLEMENTED_BY,
                confidence=0.95,
                evidence_text=f"Fix implemented by {mention}.",
            )
        ]
    )
    processor = ArtifactProcessor(
        entity_registry=create_default_entity_registry(),
        entity_resolver=EntityResolver(FakeEntityRepository({target.id: target, other.id: other})),
        event_extractor=EventExtractor(),
        evidence_extractor=EvidenceExtractor(),
        relationship_extractor=RelationshipExtractor(llm_gateway=gateway),
    )

    result = processor.process(artifact, primary_entity=make_jira_entity())

    assert len(result.relationship_candidates) == 1
    if explicit_url:
        assert len(result.relationships) == 1
        assert result.relationships[0].target_entity_id == target.id
        assert result.relationships[0].source_entity_id == "jira:PAY-1842"
    else:
        assert result.relationships == []
