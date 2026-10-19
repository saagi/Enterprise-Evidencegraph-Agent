
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.domain.models import Source
from app.ingestion.connectors import (
    GitHubPRConnector,
    SourceRecord,
)


FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "fixtures"
    / "github"
    / "PR-829.json"
)


def load_github_payload() -> dict[str, Any]:
    """Load the synthetic GitHub PR fixture."""
    with FIXTURE_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def make_source_record(
    payload: dict[str, Any] | None = None,
    source: Source = Source.GITHUB,
) -> SourceRecord:
    """Create a GitHub source record for testing."""
    return SourceRecord(
        source=source,
        source_id="acme/payments-api:pr:829",
        payload=payload if payload is not None else load_github_payload(),
        metadata={"ingestion_method": "fixture"},
    )


def test_github_connector_normalizes_pr() -> None:
    connector = GitHubPRConnector()
    artifact = connector.normalize(make_source_record())

    assert artifact.id == (
        "artifact:github:acme/payments-api:pr:829"
    )
    assert artifact.source == Source.GITHUB
    assert artifact.source_id == "acme/payments-api:pr:829"
    assert artifact.artifact_type == "github_pr"

    assert artifact.title == (
        "Fix payment failures after authentication token refresh"
    )
    assert artifact.content["number"] == 829
    assert artifact.content["state"] == "closed"
    assert artifact.content["merged"] is True
    assert "PAY-1842" in artifact.content["body"]

    assert artifact.metadata["repository"] == "acme/payments-api"
    assert artifact.metadata["author"] == "alice-chen"
    assert artifact.metadata["ingestion_method"] == "fixture"


def test_github_connector_preserves_timestamps() -> None:
    connector = GitHubPRConnector()
    artifact = connector.normalize(make_source_record())

    assert artifact.created_at == datetime(
        2026, 9, 19, 10, 30, tzinfo=UTC
    )
    assert artifact.updated_at == datetime(
        2026, 9, 21, 16, 45, tzinfo=UTC
    )
    assert artifact.content["merged_at"] == "2026-09-21T16:45:00Z"
    assert artifact.content["closed_at"] == "2026-09-21T16:45:00Z"


def test_github_connector_preserves_unknown_merge_status() -> None:
    payload = load_github_payload()
    payload.pop("merged")
    payload.pop("merged_at")

    connector = GitHubPRConnector()
    artifact = connector.normalize(
        make_source_record(payload=payload)
    )

    assert artifact.content["merged"] is None
    assert artifact.content["merged_at"] is None


def test_github_connector_rejects_non_github_source() -> None:
    connector = GitHubPRConnector()

    record = make_source_record(source=Source.JIRA)

    with pytest.raises(
        ValueError,
        match="GitHubPRConnector cannot normalize source",
    ):
        connector.normalize(record)


def test_github_connector_preserves_repository_identity() -> None:
    payload = load_github_payload()

    payload["base"]["repo"]["full_name"] = "acme/checkout-service"

    connector = GitHubPRConnector()
    artifact = connector.normalize(
        make_source_record(payload=payload)
    )

    assert artifact.source_id == "acme/checkout-service:pr:829"
    assert artifact.id == (
        "artifact:github:acme/checkout-service:pr:829"
    )
