import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

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
    EntityResolver,
    EventExtractor,
    EvidenceExtractor,
    ExtractedRelationship,
    RelationshipExtractionOutput,
    RelationshipExtractor,
)
from app.ingestion.connectors import JiraConnector, SourceRecord
from app.ingestion.orchestrator import IngestionOrchestrator
from app.ingestion.persistence import GraphProjectionError, PostgresPersistenceService
from app.ingestion.processor import ArtifactProcessor, ProcessingResult
from app.storage.graph_projection import PostgresGraphProjection
from app.storage.neo4j import Neo4jDatabase
from app.storage.neo4j_repositories import Neo4jEntityRepository, Neo4jGraphRepository
from app.storage.postgres import PostgresDatabase
from app.storage.repositories import PostgresEntityRepository, PostgresRelationshipRepository
from app.storage.schema import ArtifactRow, EntityRow, EventRow, EvidenceRow, RelationshipRow


@pytest.fixture
def records():
    token = uuid4().hex
    timestamp = datetime.now(UTC)
    source_id = f"SYNC-{int(token[:12], 16)}"
    repo = f"acme/sync-{token}"
    entities = [
        Entity(
            id=f"jira:{source_id}",
            type=EntityType.JIRA_TICKET,
            name="Synchronization test",
            source=Source.JIRA,
            source_id=source_id,
            created_at=timestamp,
            updated_at=timestamp,
        ),
        Entity(
            id=f"github:{repo}:pr:829",
            type=EntityType.GITHUB_PR,
            name="Related PR",
            source=Source.GITHUB,
            source_id=f"{repo}:pr:829",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"repository": repo},
        ),
    ]
    artifact = CanonicalArtifact(
        id=f"artifact:jira:{source_id}",
        source=Source.JIRA,
        source_id=source_id,
        artifact_type="jira_ticket",
        title="Synchronization test",
        content={},
        created_at=timestamp,
        updated_at=timestamp,
    )
    relationship = Relationship(
        id=f"relationship:{token}",
        source_entity_id=entities[0].id,
        relationship_type=RelationshipType.IMPLEMENTED_BY,
        target_entity_id=entities[1].id,
        confidence=0.95,
        provenance={"artifact_id": artifact.id},
        created_at=timestamp,
        observed_at=timestamp,
    )
    return artifact, entities, relationship


@pytest.fixture
def postgres(records):
    database = PostgresDatabase(
        os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://evidencegraph:evidencegraph@127.0.0.1:5432/evidencegraph",
        )
    )
    RelationshipRow.__table__.create(database.engine, checkfirst=True)
    artifact, entities, _ = records
    ids = [entity.id for entity in entities]
    try:
        yield database
    finally:
        with database.session() as session:
            session.execute(delete(RelationshipRow).where(RelationshipRow.source_entity_id.in_(ids)))
            session.execute(delete(EventRow).where(EventRow.entity_id.in_(ids)))
            for entity_id in ids:
                session.execute(
                    delete(EvidenceRow).where(EvidenceRow.entity_ids.contains([entity_id]))
                )
            session.execute(delete(EntityRow).where(EntityRow.id.in_(ids)))
            session.execute(delete(ArtifactRow).where(ArtifactRow.id == artifact.id))
        database.dispose()


@pytest.fixture
def projection(postgres, records):
    local_env = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    password = os.getenv("NEO4J_PASSWORD") or local_env.get("NEO4J_PASSWORD")
    if not password:
        pytest.skip("NEO4J_PASSWORD is required for live projection tests")
    database = Neo4jDatabase(
        os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
        os.getenv("NEO4J_USERNAME", "neo4j"),
        password,
        database=os.getenv("NEO4J_DATABASE", "neo4j"),
    )
    entities = Neo4jEntityRepository(database)
    graph = Neo4jGraphRepository(database)
    _, endpoints, relationship = records
    ids = [entity.id for entity in endpoints]
    try:
        graph.ensure_schema()
        yield SimpleNamespace(
            entities=entities,
            graph=graph,
            database=database,
            replay=PostgresGraphProjection(postgres, entities, graph),
        )
    finally:
        with database.session() as session:
            # Remove only edges incident to these UUID-scoped test nodes.
            session.run(
                "MATCH (entity:Entity) WHERE entity.id IN $ids DETACH DELETE entity",
                ids=ids,
            ).consume()
            session.run(
                "MATCH (identity:RelationshipIdentity {id: $id}) DELETE identity",
                id=relationship.id,
            ).consume()
            # The extractor uses its own canonical relationship ID in the end-to-end case.
            session.run(
                "MATCH (identity:RelationshipIdentity) "
                "WHERE identity.source_entity_id IN $ids DELETE identity",
                ids=ids,
            ).consume()
        database.dispose()


def test_postgres_failure_never_starts_graph_projection(postgres, records):
    artifact, entities, relationship = records
    replay = MagicMock()
    result = ProcessingResult(
        artifact_id=artifact.id,
        entities=entities,
        relationships=[relationship.model_copy(update={"target_entity_id": "missing:sync"})],
    )

    with pytest.raises(IntegrityError):
        PostgresPersistenceService(postgres, replay).persist(artifact, result)

    replay.replay.assert_not_called()
    assert PostgresRelationshipRepository(postgres).get(relationship.id) is None


def test_graph_failure_leaves_postgres_committed_and_replay_recovers(
    postgres, projection, records
):
    artifact, entities, relationship = records
    failing_graph = MagicMock(wraps=projection.graph)
    failing_graph.save_relationship.side_effect = RuntimeError("Simulated Neo4j failure")
    replay = PostgresGraphProjection(postgres, projection.entities, failing_graph)
    result = ProcessingResult(
        artifact_id=artifact.id, entities=entities, relationships=[relationship]
    )

    with pytest.raises(GraphProjectionError, match="PostgreSQL ingestion committed"):
        PostgresPersistenceService(postgres, replay).persist(artifact, result)

    assert PostgresRelationshipRepository(postgres).get(relationship.id) == relationship
    assert projection.entities.get(entities[0].id) == entities[0]
    assert projection.graph.get_neighbors(entities[0].id) == []

    projection.replay.replay()
    projection.replay.replay()

    assert projection.graph.get_neighbors(entities[0].id) == [entities[1]]
    with projection.database.session() as session:
        record = session.run(
            "MATCH ()-[edge {id: $id}]->() RETURN count(edge) AS count",
            id=relationship.id,
        ).single(strict=True)
        assert record["count"] == 1


def test_projection_reads_preserved_postgres_creation_times(postgres, projection, records):
    artifact, entities, relationship = records
    result = ProcessingResult(
        artifact_id=artifact.id, entities=entities, relationships=[relationship]
    )
    PostgresPersistenceService(postgres).persist(artifact, result)
    later = relationship.created_at + timedelta(days=1)
    refreshed = result.model_copy(
        update={
            "entities": [entity.model_copy(update={"created_at": later}) for entity in entities],
            "relationships": [relationship.model_copy(update={"created_at": later})],
        }
    )

    PostgresPersistenceService(postgres, projection.replay).persist(artifact, refreshed)

    assert projection.entities.get(entities[0].id).created_at == entities[0].created_at
    with projection.database.session() as session:
        record = session.run(
            "MATCH ()-[edge {id: $id}]->() RETURN edge.created_at AS created_at",
            id=relationship.id,
        ).single(strict=True)
        assert record["created_at"].to_native() == relationship.created_at


def test_jira_pr_url_ingestion_persists_and_projects_relationship(postgres, projection, records):
    artifact, entities, _ = records
    source, target = entities
    repository = PostgresEntityRepository(postgres)
    repository.save(target)
    repo = target.metadata["repository"]
    url = f"https://github.com/{repo}/pull/829"
    gateway = MagicMock()
    gateway.generate_structured.return_value = RelationshipExtractionOutput(
        relationships=[
            ExtractedRelationship(
                source_mention=source.source_id,
                target_mention=url,
                relationship_type=RelationshipType.IMPLEMENTED_BY,
                confidence=0.95,
                evidence_text=f"Fix implemented in {url}",
            )
        ]
    )
    processor = ArtifactProcessor(
        create_default_entity_registry(),
        EntityResolver(repository),
        EventExtractor(),
        EvidenceExtractor(),
        RelationshipExtractor(gateway),
    )
    orchestrator = IngestionOrchestrator(
        JiraConnector(), repository, processor,
        PostgresPersistenceService(postgres, projection.replay),
    )
    record = SourceRecord(
        source=Source.JIRA,
        source_id=source.source_id,
        payload={
            "fields": {
                "summary": f"{source.source_id} investigation",
                "description": f"Fix implemented in {url}",
                "status": {"name": "In Progress"},
                "created": artifact.created_at.isoformat(),
                "updated": artifact.updated_at.isoformat(),
            }
        },
        metadata={},
    )

    result = orchestrator.ingest(record)
    result = orchestrator.ingest(record)

    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert relationship.target_entity_id == target.id
    assert PostgresRelationshipRepository(postgres).get(relationship.id) == relationship
    assert projection.graph.get_neighbors(source.id) == [target]
    with postgres.session() as session:
        assert session.scalar(
            select(func.count()).select_from(RelationshipRow)
            .where(RelationshipRow.source_entity_id == source.id)
        ) == 1


def test_concurrent_replay_waits_and_projects_latest_committed_snapshot(
    postgres, projection, records
):
    artifact, entities, relationship = records
    PostgresPersistenceService(postgres).persist(
        artifact,
        ProcessingResult(artifact_id=artifact.id, entities=entities, relationships=[relationship]),
    )
    entered = Event()
    release = Event()
    second_started = Event()
    overlapping_write = Event()
    guard = Lock()
    first_call = True

    def save(entity):
        nonlocal first_call
        with guard:
            should_pause = first_call
            first_call = False
        if should_pause:
            entered.set()
            if not release.wait(timeout=10):
                raise RuntimeError("Replay test timed out waiting for release")
        elif not release.is_set():
            overlapping_write.set()
        projection.entities.save(entity)

    pausing_entities = MagicMock(wraps=projection.entities)
    pausing_entities.save.side_effect = save
    replay = PostgresGraphProjection(postgres, pausing_entities, projection.graph)

    def second_replay():
        second_started.set()
        replay.replay()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(replay.replay)
        try:
            assert entered.wait(timeout=10)
            updated = entities[0].model_copy(update={"name": "Committed during first replay"})
            PostgresEntityRepository(postgres).save(updated)
            second = pool.submit(second_replay)
            assert second_started.wait(timeout=10)
            assert not overlapping_write.wait(timeout=0.25)
        finally:
            release.set()
        first.result(timeout=10)
        second.result(timeout=10)

    assert projection.entities.get(updated.id) == updated
    assert projection.graph.get_neighbors(updated.id) == [entities[1]]
