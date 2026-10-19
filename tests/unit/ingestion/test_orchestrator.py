
from datetime import UTC, datetime
from pathlib import Path
import json

import pytest

from app.domain.models import (
    Entity,
    EntityType,
    Source,
)
from app.ingestion.connectors import (
    GitHubPRConnector,
    JiraConnector,
    SourceRecord,
)
from app.ingestion.orchestrator import IngestionOrchestrator
from app.ingestion.processor import ProcessingResult


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


class FakeEntityRepository:
    """In-memory repository with read and upsert support."""

    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}
        self.upsert_calls = 0

    def get_entity(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    def upsert(self, entity: Entity) -> None:
        self.entities[entity.id] = entity
        self.upsert_calls += 1


class FakeProcessor:
    """Records what the orchestrator passes for processing."""

    def __init__(self, repository: FakeEntityRepository) -> None:
        self.repository = repository
        self.processed_artifacts = []

    def process(self, artifact) -> ProcessingResult:
        primary_id = f"{artifact.source.value}:{artifact.source_id}"

        # Primary entity must exist before processing begins.
        assert self.repository.get_entity(primary_id) is not None

        self.processed_artifacts.append(artifact)

        return ProcessingResult(artifact_id=artifact.id)


def load_fixture(source: str, filename: str) -> dict:
    path = FIXTURES / source / filename

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def make_orchestrator(connector):
    repository = FakeEntityRepository()
    processor = FakeProcessor(repository)

    orchestrator = IngestionOrchestrator(
        connector=connector,
        entity_repository=repository,
        entity_writer=repository,
        processor=processor,
    )

    return orchestrator, repository, processor


def test_jira_ingestion_creates_primary_entity() -> None:
    orchestrator, repository, processor = make_orchestrator(
        JiraConnector()
    )

    payload = load_fixture("jira", "PAY-1842.json")

    record = SourceRecord(
        source=Source.JIRA,
        source_id="PAY-1842",
        payload=payload,
        metadata={},
    )

    result = orchestrator.ingest(record)

    entity = repository.get_entity("jira:PAY-1842")

    assert entity is not None
    assert entity.type == EntityType.JIRA_TICKET
    assert entity.source == Source.JIRA
    assert entity.source_id == "PAY-1842"

    assert repository.upsert_calls == 1
    assert len(processor.processed_artifacts) == 1
    assert result.artifact_id == processor.processed_artifacts[0].id


def test_reingesting_jira_upserts_same_entity() -> None:
    orchestrator, repository, processor = make_orchestrator(
        JiraConnector()
    )

    payload = load_fixture("jira", "PAY-1842.json")

    record = SourceRecord(
        source=Source.JIRA,
        source_id="PAY-1842",
        payload=payload,
        metadata={},
    )

    orchestrator.ingest(record)
    orchestrator.ingest(record)

    assert len(repository.entities) == 1
    assert repository.upsert_calls == 2
    assert len(processor.processed_artifacts) == 2


def test_github_ingestion_creates_repository_scoped_pr_entity() -> None:
    orchestrator, repository, processor = make_orchestrator(
        GitHubPRConnector()
    )

    payload = load_fixture("github", "PR-829.json")

    record = SourceRecord(
        source=Source.GITHUB,
        source_id="829",
        payload=payload,
        metadata={},
    )

    result = orchestrator.ingest(record)

    entity = repository.get_entity(
        "github:acme/payments-api:pr:829"
    )

    assert entity is not None
    assert entity.type == EntityType.GITHUB_PR
    assert entity.source == Source.GITHUB
    assert entity.source_id == "acme/payments-api:pr:829"

    assert len(repository.entities) == 1
    assert len(processor.processed_artifacts) == 1
    assert result.artifact_id == (
        "artifact:github:acme/payments-api:pr:829"
    )


def test_github_pr_reference_does_not_create_jira_primary() -> None:
    orchestrator, repository, processor = make_orchestrator(
        GitHubPRConnector()
    )

    payload = load_fixture("github", "PR-829.json")

    record = SourceRecord(
        source=Source.GITHUB,
        source_id="829",
        payload=payload,
        metadata={},
    )

    orchestrator.ingest(record)

    assert repository.get_entity(
        "github:acme/payments-api:pr:829"
    ) is not None

    # The PR references PAY-1842, but that doesn't make
    # the Jira ticket the primary entity of this artifact.
    assert repository.get_entity("jira:PAY-1842") is None


def test_existing_entity_preserves_original_created_at() -> None:
    orchestrator, repository, _ = make_orchestrator(
        JiraConnector()
    )

    original_created_at = datetime(
        2026, 9, 1, tzinfo=UTC
    )

    repository.upsert(
        Entity(
            id="jira:PAY-1842",
            type=EntityType.JIRA_TICKET,
            name="Original ticket",
            source=Source.JIRA,
            source_id="PAY-1842",
            created_at=original_created_at,
            updated_at=original_created_at,
            metadata={"internal_tag": "important"},
        )
    )

    payload = load_fixture("jira", "PAY-1842.json")

    orchestrator.ingest(
        SourceRecord(
            source=Source.JIRA,
            source_id="PAY-1842",
            payload=payload,
            metadata={},
        )
    )

    entity = repository.get_entity("jira:PAY-1842")

    assert entity is not None
    assert entity.created_at == original_created_at
    assert entity.metadata["internal_tag"] == "important"


@pytest.mark.parametrize(
    "source",
    [Source.SLACK, Source.DOCUMENT],
)
def test_unsupported_source_rejected(source: Source) -> None:
    # Test the source policy independently of connector behavior.
    with pytest.raises(ValueError, match="Unsupported source"):
        IngestionOrchestrator._get_entity_type(source)
