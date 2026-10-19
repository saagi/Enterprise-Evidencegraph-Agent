
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.models import EventType, Source
from app.domain.services import EventExtractor
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


def make_artifact(payload: dict[str, Any] | None = None):
    """Normalize a GitHub fixture into a canonical artifact."""
    record = SourceRecord(
        source=Source.GITHUB,
        source_id="acme/payments-api:pr:829",
        payload=payload if payload is not None else load_github_payload(),
        metadata={},
    )
    return GitHubPRConnector().normalize(record)


def test_extracts_github_lifecycle_events() -> None:
    artifact = make_artifact()

    events = EventExtractor().extract(
        artifact=artifact,
        entity_ids=[PR_ENTITY_ID],
    )

    assert len(events) == 3
    assert {event.event_type for event in events} == {
        EventType.CREATED,
        EventType.CLOSED,
        EventType.MERGED,
    }

    assert all(event.entity_id == PR_ENTITY_ID for event in events)
    assert all(event.source == Source.GITHUB for event in events)


def test_created_event_uses_pr_creation_timestamp() -> None:
    events = EventExtractor().extract(
        artifact=make_artifact(),
        entity_ids=[PR_ENTITY_ID],
    )

    created = next(
        event for event in events
        if event.event_type == EventType.CREATED
    )

    assert created.timestamp == datetime(
        2026, 9, 19, 10, 30, tzinfo=UTC
    )


def test_merged_event_uses_actual_merge_timestamp() -> None:
    events = EventExtractor().extract(
        artifact=make_artifact(),
        entity_ids=[PR_ENTITY_ID],
    )

    merged = next(
        event for event in events
        if event.event_type == EventType.MERGED
    )

    assert merged.timestamp == datetime(
        2026, 9, 21, 16, 45, tzinfo=UTC
    )
    assert merged.data["merged"] is True
    assert merged.data["base_branch"] == "main"


def test_missing_merge_timestamp_does_not_invent_merge_event() -> None:
    payload = load_github_payload()
    payload["merged_at"] = None

    events = EventExtractor().extract(
        artifact=make_artifact(payload),
        entity_ids=[PR_ENTITY_ID],
    )

    assert EventType.MERGED not in {
        event.event_type for event in events
    }

    assert len(events) == 2


def test_open_pr_has_no_closed_or_merged_events() -> None:
    payload = load_github_payload()
    payload["state"] = "open"
    payload["merged"] = False
    payload["merged_at"] = None
    payload["closed_at"] = None

    events = EventExtractor().extract(
        artifact=make_artifact(payload),
        entity_ids=[PR_ENTITY_ID],
    )

    assert len(events) == 1
    assert events[0].event_type == EventType.CREATED


def test_no_entity_produces_no_events() -> None:
    events = EventExtractor().extract(
        artifact=make_artifact(),
        entity_ids=[],
    )

    assert events == []


def test_event_ids_are_deterministic() -> None:
    artifact = make_artifact()
    extractor = EventExtractor()

    first = extractor.extract(
        artifact=artifact,
        entity_ids=[PR_ENTITY_ID],
    )

    second = extractor.extract(
        artifact=artifact,
        entity_ids=[PR_ENTITY_ID],
    )

    assert [event.id for event in first] == [
        event.id for event in second
    ]
