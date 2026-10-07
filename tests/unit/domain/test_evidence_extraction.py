from datetime import UTC, datetime

from app.domain.models import (
    CanonicalArtifact,
    EvidenceType,
    Source,
)
from app.domain.services import EvidenceExtractor


def make_jira_artifact() -> CanonicalArtifact:
    return CanonicalArtifact(
        id="artifact:jira:PAY-1842",
        source=Source.JIRA,
        source_id="PAY-1842",
        artifact_type="jira_ticket",
        title="Payment requests fail after authentication token refresh",
        content={
            "summary": (
                "Payment requests fail after authentication "
                "token refresh"
            ),
            "description": "Investigation is ongoing.",
            "status": "In Progress",
            "comments": [
                {
                    "id": "comment-101",
                    "author": {
                        "displayName": "Alice Chen",
                    },
                    "created": "2026-09-19T11:20:00Z",
                    "body": (
                        "The issue appears related to "
                        "token refresh handling."
                    ),
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


def test_extracts_jira_evidence() -> None:
    extractor = EvidenceExtractor()

    evidence = extractor.extract(
        artifact=make_jira_artifact(),
        entity_ids=["jira:PAY-1842"],
    )

    assert len(evidence) == 3

    assert [
        item.evidence_type
        for item in evidence
    ] == [
        EvidenceType.STATUS_UPDATE,
        EvidenceType.COMMENT,
        EvidenceType.COMMENT,
    ]


def test_extracts_status_as_structured_claim() -> None:
    extractor = EvidenceExtractor()

    evidence = extractor.extract(
        artifact=make_jira_artifact(),
        entity_ids=["jira:PAY-1842"],
    )

    status_evidence = evidence[0]

    assert status_evidence.evidence_type == EvidenceType.STATUS_UPDATE
    assert status_evidence.entity_ids == ["jira:PAY-1842"]

    assert status_evidence.claim == (
        "Ticket status is In Progress"
    )

    assert status_evidence.content == "In Progress"

    assert status_evidence.timestamp == datetime(
        2026, 9, 20, 14, 30, tzinfo=UTC
    )


def test_extracts_comment_as_evidence() -> None:
    extractor = EvidenceExtractor()

    evidence = extractor.extract(
        artifact=make_jira_artifact(),
        entity_ids=["jira:PAY-1842"],
    )

    comment_evidence = [
        item
        for item in evidence
        if item.source_id == "comment-102"
    ]

    assert len(comment_evidence) == 1

    item = comment_evidence[0]

    assert item.evidence_type == EvidenceType.COMMENT

    assert item.claim == (
        "Fix is being implemented in PR #829."
    )

    assert item.content == (
        "Fix is being implemented in PR #829."
    )

    assert item.metadata["author"] == {
        "displayName": "Bob Rao"
    }


def test_evidence_preserves_source_location() -> None:
    extractor = EvidenceExtractor()

    evidence = extractor.extract(
        artifact=make_jira_artifact(),
        entity_ids=["jira:PAY-1842"],
    )

    comment_evidence = [
        item
        for item in evidence
        if item.source_id == "comment-101"
    ][0]

    assert comment_evidence.location is not None

    assert comment_evidence.location.artifact_id == (
        "artifact:jira:PAY-1842"
    )


def test_returns_no_evidence_without_entity() -> None:
    extractor = EvidenceExtractor()

    evidence = extractor.extract(
        artifact=make_jira_artifact(),
        entity_ids=[],
    )

    assert evidence == []