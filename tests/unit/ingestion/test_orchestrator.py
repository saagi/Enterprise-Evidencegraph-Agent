"""Unit tests for the atomic ingestion orchestrator."""

from datetime import UTC, datetime
from pathlib import Path
import json

import pytest

from app.domain.models import Entity, EntityType, Source
from app.ingestion.connectors import GitHubPRConnector, JiraConnector, SourceRecord
from app.ingestion.orchestrator import IngestionOrchestrator
from app.ingestion.processor import ProcessingResult


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


class FakeEntityRepository:
    """Read-only from the orchestrator's perspective; writes happen in persistence."""

    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}
        self.save_calls = 0

    def get(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    def save(self, entity: Entity) -> None:
        self.entities[entity.id] = entity
        self.save_calls += 1


class FakeProcessor:
    """Checks that the supplied primary entity has not been persisted early."""

    def __init__(self, repository: FakeEntityRepository) -> None:
        self.repository = repository
        self.processed_artifacts = []
        self.received_primary_entities: list[Entity] = []
        self.fail = False

    def process(self, artifact, primary_entity=None) -> ProcessingResult:
        if self.fail:
            raise RuntimeError("Processing failed")

        assert primary_entity is not None
        assert primary_entity.id == f"{artifact.source.value}:{artifact.source_id}"
        assert self.repository.save_calls == 0 or (
            # Preexisting entities may have been seeded in the test.
            self.repository.get(primary_entity.id) is not None
        )

        self.processed_artifacts.append(artifact)
        self.received_primary_entities.append(primary_entity)
        return ProcessingResult(
            artifact_id=artifact.id,
            entities=[primary_entity],
        )


class FakePersistence:
    """Simulates committing a completed ingestion result."""

    def __init__(self, repository: FakeEntityRepository) -> None:
        self.repository = repository
        self.calls = 0
        self.fail = False

    def persist(self, artifact, result: ProcessingResult) -> None:
        self.calls += 1
        if self.fail:
            raise RuntimeError("Persistence failed")
        assert result.artifact_id == artifact.id
        for entity in result.entities:
            self.repository.save(entity)


def load_fixture(source: str, filename: str) -> dict:
    path = FIXTURES / source / filename
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def make_orchestrator(connector):
    repository = FakeEntityRepository()
    processor = FakeProcessor(repository)
    persistence = FakePersistence(repository)
    orchestrator = IngestionOrchestrator(
        connector=connector,
        entity_repository=repository,
        processor=processor,
        persistence=persistence,
    )
    return orchestrator, repository, processor, persistence


def make_jira_record() -> SourceRecord:
    return SourceRecord(
        source=Source.JIRA,
        source_id="PAY-1842",
        payload=load_fixture("jira", "PAY-1842.json"),
        metadata={},
    )


def make_github_record() -> SourceRecord:
    return SourceRecord(
        source=Source.GITHUB,
        source_id="829",
        payload=load_fixture("github", "PR-829.json"),
        metadata={},
    )


def test_jira_ingestion_creates_primary_entity() -> None:
    orchestrator, repository, processor, persistence = make_orchestrator(JiraConnector())
    result = orchestrator.ingest(make_jira_record())

    entity = repository.get("jira:PAY-1842")
    assert entity is not None
    assert entity.type == EntityType.JIRA_TICKET
    assert entity.source == Source.JIRA
    assert entity.source_id == "PAY-1842"
    assert repository.save_calls == 1
    assert persistence.calls == 1
    assert len(processor.processed_artifacts) == 1
    assert result.artifact_id == processor.processed_artifacts[0].id
    assert processor.received_primary_entities[0] == entity


def test_reingesting_jira_upserts_same_entity() -> None:
    orchestrator, repository, processor, persistence = make_orchestrator(JiraConnector())
    record = make_jira_record()
    orchestrator.ingest(record)
    orchestrator.ingest(record)

    assert len(repository.entities) == 1
    assert repository.save_calls == 2
    assert persistence.calls == 2
    assert len(processor.processed_artifacts) == 2


def test_github_ingestion_creates_repository_scoped_pr_entity() -> None:
    orchestrator, repository, processor, persistence = make_orchestrator(GitHubPRConnector())
    result = orchestrator.ingest(make_github_record())

    entity = repository.get("github:acme/payments-api:pr:829")
    assert entity is not None
    assert entity.type == EntityType.GITHUB_PR
    assert entity.source == Source.GITHUB
    assert entity.source_id == "acme/payments-api:pr:829"
    assert len(repository.entities) == 1
    assert len(processor.processed_artifacts) == 1
    assert persistence.calls == 1
    assert result.artifact_id == "artifact:github:acme/payments-api:pr:829"


def test_github_pr_reference_does_not_create_jira_primary() -> None:
    orchestrator, repository, _, _ = make_orchestrator(GitHubPRConnector())
    orchestrator.ingest(make_github_record())

    assert repository.get("github:acme/payments-api:pr:829") is not None
    assert repository.get("jira:PAY-1842") is None


def test_existing_entity_preserves_original_created_at() -> None:
    orchestrator, repository, processor, persistence = make_orchestrator(JiraConnector())
    original_created_at = datetime(2026, 9, 1, tzinfo=UTC)
    repository.save(
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
    writes_before = repository.save_calls
    orchestrator.ingest(make_jira_record())

    entity = repository.get("jira:PAY-1842")
    assert entity is not None
    assert entity.created_at == original_created_at
    assert entity.metadata["internal_tag"] == "important"
    assert repository.save_calls == writes_before + 1
    assert persistence.calls == 1
    assert processor.received_primary_entities[0].created_at == original_created_at


def test_processing_failure_does_not_write_entity() -> None:
    orchestrator, repository, processor, persistence = make_orchestrator(JiraConnector())
    processor.fail = True

    with pytest.raises(RuntimeError, match="Processing failed"):
        orchestrator.ingest(make_jira_record())

    assert repository.entities == {}
    assert repository.save_calls == 0
    assert persistence.calls == 0


def test_persistence_failure_does_not_write_entity() -> None:
    orchestrator, repository, processor, persistence = make_orchestrator(JiraConnector())
    persistence.fail = True

    with pytest.raises(RuntimeError, match="Persistence failed"):
        orchestrator.ingest(make_jira_record())

    assert len(processor.processed_artifacts) == 1
    assert persistence.calls == 1
    assert repository.entities == {}
    assert repository.save_calls == 0


@pytest.mark.parametrize("source", [Source.SLACK, Source.DOCUMENT])
def test_unsupported_source_rejected(source: Source) -> None:
    with pytest.raises(ValueError, match="Unsupported source"):
        IngestionOrchestrator._get_entity_type(source)
