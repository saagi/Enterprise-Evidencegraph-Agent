import json
from pathlib import Path

import pytest

from app.domain.models import Source
from app.ingestion.connectors import JiraConnector, SourceRecord


FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "fixtures"
    / "jira"
    / "PAY-1842.json"
)


def load_jira_fixture() -> dict:
    with FIXTURE_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def test_normalizes_jira_record() -> None:
    payload = load_jira_fixture()

    record = SourceRecord(
        source=Source.JIRA,
        source_id=payload["key"],
        payload=payload,
        metadata={},
    )

    connector = JiraConnector()

    artifact = connector.normalize(record)

    assert artifact.id == "artifact:jira:PAY-1842"
    assert artifact.source == Source.JIRA
    assert artifact.source_id == "PAY-1842"
    assert artifact.artifact_type == "jira_ticket"

    assert artifact.title == (
        "Payment requests fail after authentication token refresh"
    )

    assert artifact.content["status"] == "In Progress"

    assert artifact.content["description"] == (
        "Some payment requests are failing after the authentication "
        "token is refreshed. Investigation is ongoing."
    )

    assert len(artifact.content["comments"]) == 2

    assert artifact.metadata["project"]["key"] == "PAY"
    assert artifact.metadata["priority"]["name"] == "High"


def test_preserves_record_metadata() -> None:
    payload = load_jira_fixture()

    record = SourceRecord(
        source=Source.JIRA,
        source_id=payload["key"],
        payload=payload,
        metadata={
            "ingestion_id": "sync-001",
        },
    )

    connector = JiraConnector()

    artifact = connector.normalize(record)

    assert artifact.metadata["ingestion_id"] == "sync-001"


def test_rejects_non_jira_source() -> None:
    payload = load_jira_fixture()

    record = SourceRecord(
        source=Source.SLACK,
        source_id="thread-123",
        payload=payload,
        metadata={},
    )

    connector = JiraConnector()

    with pytest.raises(
        ValueError,
        match="JiraConnector cannot normalize source",
    ):
        connector.normalize(record)