from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from app.domain.models import (
    CanonicalArtifact,
    Entity,
    EntityType,
    RelationshipType,
    Source,
)
from app.domain.services import (
    EntityResolutionResult,
    EntityResolutionStatus,
    ExtractedRelationship,
    RelationshipExtractionOutput,
    RelationshipExtractor,
)


class FakeLLMGateway:
    """Returns predefined structured output without calling an LLM."""

    def __init__(
        self,
        output: RelationshipExtractionOutput,
    ) -> None:
        self._output = output

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[BaseModel],
    ) -> Any:
        return self._output


def make_jira_entity() -> Entity:
    now = datetime.now(UTC)

    return Entity(
        id="jira:PAY-1842",
        type=EntityType.JIRA_TICKET,
        name="Payment requests fail after authentication token refresh",
        source=Source.JIRA,
        source_id="PAY-1842",
        created_at=now,
        updated_at=now,
    )


def make_artifact() -> CanonicalArtifact:
    return CanonicalArtifact(
        id="artifact:jira:PAY-1842",
        source=Source.JIRA,
        source_id="PAY-1842",
        artifact_type="jira_ticket",
        title="Payment failure investigation",
        content={
            "summary": "Payment requests fail after token refresh",
            "description": "Investigation is ongoing.",
            "status": "In Progress",
            "comments": [
                {
                    "id": "comment-102",
                    "body": "Fix is being implemented in PR #829.",
                }
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


def make_llm_output() -> RelationshipExtractionOutput:
    return RelationshipExtractionOutput(
        relationships=[
            ExtractedRelationship(
                source_mention="PAY-1842",
                target_mention="PR #829",
                relationship_type=RelationshipType.IMPLEMENTED_BY,
                confidence=0.96,
                evidence_text=(
                    "Fix is being implemented in PR #829."
                ),
            )
        ]
    )


def test_unresolved_target_creates_candidate_but_not_relationship() -> None:
    gateway = FakeLLMGateway(
        make_llm_output()
    )

    extractor = RelationshipExtractor(
        llm_gateway=gateway
    )

    resolutions = [
        EntityResolutionResult(
            mention="PAY-1842",
            entity_id="jira:PAY-1842",
            entity_type=EntityType.JIRA_TICKET,
            status=EntityResolutionStatus.RESOLVED,
            confidence=1.0,
        ),
        EntityResolutionResult(
            mention="PR #829",
            entity_id=None,
            entity_type=EntityType.GITHUB_PR,
            status=EntityResolutionStatus.UNRESOLVED,
            confidence=0.0,
        ),
    ]

    result = extractor.extract(
        artifact=make_artifact(),
        primary_entity=make_jira_entity(),
        resolutions=resolutions,
    )

    assert len(result.candidates) == 1

    candidate = result.candidates[0]

    assert candidate.source_entity_id == "jira:PAY-1842"
    assert candidate.target_mention == "PR #829"

    assert (
        candidate.relationship_type
        == RelationshipType.IMPLEMENTED_BY
    )

    assert candidate.confidence == 0.96

    # PR #829 is not canonically resolved yet.
    assert result.relationships == []


def test_resolved_target_creates_relationship() -> None:
    gateway = FakeLLMGateway(
        make_llm_output()
    )

    extractor = RelationshipExtractor(
        llm_gateway=gateway
    )

    resolutions = [
        EntityResolutionResult(
            mention="PAY-1842",
            entity_id="jira:PAY-1842",
            entity_type=EntityType.JIRA_TICKET,
            status=EntityResolutionStatus.RESOLVED,
            confidence=1.0,
        ),
        EntityResolutionResult(
            mention="PR #829",
            entity_id="github:payments-api:pr:829",
            entity_type=EntityType.GITHUB_PR,
            status=EntityResolutionStatus.RESOLVED,
            confidence=1.0,
        ),
    ]

    result = extractor.extract(
        artifact=make_artifact(),
        primary_entity=make_jira_entity(),
        resolutions=resolutions,
    )

    assert len(result.candidates) == 1
    assert len(result.relationships) == 1

    relationship = result.relationships[0]

    assert relationship.source_entity_id == (
        "jira:PAY-1842"
    )

    assert relationship.target_entity_id == (
        "github:payments-api:pr:829"
    )

    assert (
        relationship.relationship_type
        == RelationshipType.IMPLEMENTED_BY
    )

    assert relationship.confidence == 0.96

    assert relationship.provenance["method"] == (
        "llm_semantic_extraction"
    )


def test_no_llm_relationship_produces_empty_result() -> None:
    gateway = FakeLLMGateway(
        RelationshipExtractionOutput(
            relationships=[]
        )
    )

    extractor = RelationshipExtractor(
        llm_gateway=gateway
    )

    result = extractor.extract(
        artifact=make_artifact(),
        primary_entity=make_jira_entity(),
        resolutions=[],
    )

    assert result.candidates == []
    assert result.relationships == []