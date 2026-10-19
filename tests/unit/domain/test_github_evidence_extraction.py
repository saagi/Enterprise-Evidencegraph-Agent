
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.models import CanonicalArtifact, EvidenceType, Source
from app.domain.services import EvidenceExtractor
from app.ingestion.connectors import GitHubPRConnector, SourceRecord


FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "fixtures"
    / "github"
    / "PR-829.json"
)

PR_ENTITY_ID = "github:acme/payments-api:pr:829"


def load_github_payload() -> dict[str, Any]:
    """Load the synthetic GitHub PR fixture."""
    with FIXTURE_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def make_artifact(
    payload: dict[str, Any] | None = None,
) -> CanonicalArtifact:
    """Normalize a GitHub fixture into a canonical artifact."""
    record = SourceRecord(
        source=Source.GITHUB,
        source_id="acme/payments-api:pr:829",
        payload=payload if payload is not None else load_github_payload(),
        metadata={},
    )
    return GitHubPRConnector().normalize(record)


def test_extracts_merge_and_description_evidence() -> None:
    artifact = make_artifact()

    evidence = EvidenceExtractor().extract(
        artifact=artifact,
        entity_ids=[PR_ENTITY_ID],
    )

    assert len(evidence) == 2

    assert {item.id.rsplit(":", 1)[-1] for item in evidence} == {
        "merged",
        "description",
    }

    assert all(item.source == Source.GITHUB for item in evidence)
    assert all(item.entity_ids == [PR_ENTITY_ID] for item in evidence)


def test_merge_evidence_uses_actual_merge_timestamp() -> None:
    evidence = EvidenceExtractor().extract(
        artifact=make_artifact(),
        entity_ids=[PR_ENTITY_ID],
    )

    merged = next(
        item for item in evidence
        if item.id.endswith(":merged")
    )

    assert merged.evidence_type == EvidenceType.PR_CHANGE
    assert merged.claim == "Pull request was merged"
    assert merged.timestamp == datetime(
        2026, 9, 21, 16, 45, tzinfo=UTC
    )
    assert merged.metadata["merged"] is True


def test_description_evidence_preserves_original_content() -> None:
    artifact = make_artifact()

    evidence = EvidenceExtractor().extract(
        artifact=artifact,
        entity_ids=[PR_ENTITY_ID],
    )

    description = next(
        item for item in evidence
        if item.id.endswith(":description")
    )

    expected_body = artifact.content["body"]

    assert description.evidence_type == EvidenceType.DOCUMENTATION
    assert description.content == expected_body
    assert description.claim == expected_body
    assert "PAY-1842" in description.content


def test_evidence_preserves_source_location() -> None:
    artifact = make_artifact()

    evidence = EvidenceExtractor().extract(
        artifact=artifact,
        entity_ids=[PR_ENTITY_ID],
    )

    for item in evidence:
        assert item.location is not None
        assert item.location.artifact_id == artifact.id
        assert item.location.url == (
            "https://github.com/acme/payments-api/pull/829"
        )


def test_missing_merge_timestamp_does_not_create_merge_evidence() -> None:
    payload = load_github_payload()
    payload["merged_at"] = None

    evidence = EvidenceExtractor().extract(
        artifact=make_artifact(payload),
        entity_ids=[PR_ENTITY_ID],
    )

    assert len(evidence) == 1
    assert evidence[0].id.endswith(":description")


def test_unmerged_pr_does_not_create_merge_evidence() -> None:
    payload = load_github_payload()
    payload["merged"] = False
    payload["merged_at"] = None

    evidence = EvidenceExtractor().extract(
        artifact=make_artifact(payload),
        entity_ids=[PR_ENTITY_ID],
    )

    assert all(
        not item.id.endswith(":merged")
        for item in evidence
    )


def test_empty_description_does_not_create_description_evidence() -> None:
    payload = load_github_payload()
    payload["body"] = ""

    evidence = EvidenceExtractor().extract(
        artifact=make_artifact(payload),
        entity_ids=[PR_ENTITY_ID],
    )

    assert len(evidence) == 1
    assert evidence[0].id.endswith(":merged")


def test_no_entity_produces_no_evidence() -> None:
    evidence = EvidenceExtractor().extract(
        artifact=make_artifact(),
        entity_ids=[],
    )

    assert evidence == []


def test_evidence_ids_are_deterministic() -> None:
    artifact = make_artifact()
    extractor = EvidenceExtractor()

    first = extractor.extract(
        artifact=artifact,
        entity_ids=[PR_ENTITY_ID],
    )

    second = extractor.extract(
        artifact=artifact,
        entity_ids=[PR_ENTITY_ID],
    )

    assert [item.id for item in first] == [
        item.id for item in second
    ]
