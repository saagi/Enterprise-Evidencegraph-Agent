from datetime import UTC, datetime

from app.domain.models import (
    CanonicalArtifact,
    EventType,
    Source,
)
from app.domain.services import EventExtractor


def make_jira_artifact() -> CanonicalArtifact:
    return CanonicalArtifact(
        id="artifact:jira:PAY-1842",
        source=Source.JIRA,
        source_id="PAY-1842",
        artifact_type="jira_ticket",
        title="Payment requests fail after authentication token refresh",
        content={
            "summary": "Payment requests fail after authentication token refresh",
            "description": "Investigation is ongoing.",
            "status": "In Progress",
            "comments": [
                {
                    "id": "comment-101",
                    "author": {
                        "displayName": "Alice Chen",
                    },
                    "created": "2026-09-19T11:20:00Z",
                    "body": "The issue appears related to token refresh handling.",
                },
                {
                    "id": "comment-102",
                    "author": {
                        "displayName": "Bob Rao",
                    },
                    "created": "2026-09-20T14:30:00Z",
                    "body": "Fix is being implemented in PR #829.",
                },
            ],
        },
        metadata={},
        created_at=datetime(
            2026, 9, 18, 9, 15, tzinfo=UTC
        ),
        updated_at=datetime(
            2026, 9, 20, 14, 30, tzinfo=UTC
        ),
    )


def test_extracts_jira_events() -> None:
    extractor = EventExtractor()

    events = extractor.extract(
        artifact=make_jira_artifact(),
        entity_ids=["jira:PAY-1842"],
    )

    assert len(events) == 4

    event_types = [
        event.event_type
        for event in events
    ]

    assert event_types == [
        EventType.CREATED,
        EventType.UPDATED,
        EventType.COMMENT_ADDED,
        EventType.COMMENT_ADDED,
    ]


def test_created_event_uses_artifact_creation_time() -> None:
    extractor = EventExtractor()

    events = extractor.extract(
        artifact=make_jira_artifact(),
        entity_ids=["jira:PAY-1842"],
    )

    created_event = events[0]

    assert created_event.entity_id == "jira:PAY-1842"
    assert created_event.event_type == EventType.CREATED
    assert created_event.timestamp == datetime(
        2026, 9, 18, 9, 15, tzinfo=UTC
    )


def test_extracts_comment_event_content() -> None:
    extractor = EventExtractor()

    events = extractor.extract(
        artifact=make_jira_artifact(),
        entity_ids=["jira:PAY-1842"],
    )

    comment_events = [
        event
        for event in events
        if event.event_type == EventType.COMMENT_ADDED
    ]

    assert len(comment_events) == 2

    first_comment = comment_events[0]

    assert first_comment.source_id == "comment-101"
    assert first_comment.data["body"] == (
        "The issue appears related to token refresh handling."
    )
    assert first_comment.data["author"] == {
        "displayName": "Alice Chen"
    }


def test_does_not_invent_status_changed_event() -> None:
    extractor = EventExtractor()

    events = extractor.extract(
        artifact=make_jira_artifact(),
        entity_ids=["jira:PAY-1842"],
    )

    assert all(
        event.event_type != EventType.STATUS_CHANGED
        for event in events
    )


def test_returns_no_events_without_entity() -> None:
    extractor = EventExtractor()

    events = extractor.extract(
        artifact=make_jira_artifact(),
        entity_ids=[],
    )

    assert events == []