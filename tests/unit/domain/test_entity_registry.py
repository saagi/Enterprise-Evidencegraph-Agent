import pytest

from app.domain.entity_registry import create_default_entity_registry, normalize_github_pr
from app.domain.models import EntityType, Source


def test_identifies_jira_ticket() -> None:
    registry = create_default_entity_registry()

    candidates = registry.identify(
        text="MAPS-1842 is still blocked.",
        source=Source.SLACK,
        artifact_id="artifact:slack:thread:123",
    )

    assert len(candidates) == 1

    candidate = candidates[0]

    assert candidate.mention == "MAPS-1842"
    assert candidate.entity_type == EntityType.JIRA_TICKET
    assert candidate.normalized_id == "jira:MAPS-1842"
    assert candidate.source == Source.SLACK
    assert candidate.confidence == 0.99


def test_normalizes_lowercase_jira_ticket() -> None:
    registry = create_default_entity_registry()

    candidates = registry.identify(
        text="maps-1842 is still blocked.",
        source=Source.SLACK,
        artifact_id="artifact:slack:thread:123",
    )

    assert len(candidates) == 1
    assert candidates[0].mention == "maps-1842"
    assert candidates[0].normalized_id == "jira:MAPS-1842"


def test_identifies_multiple_jira_tickets() -> None:
    registry = create_default_entity_registry()

    candidates = registry.identify(
        text="MAPS-1842 is blocked by PLATFORM-928.",
        source=Source.SLACK,
        artifact_id="artifact:slack:thread:123",
    )

    assert len(candidates) == 2

    assert candidates[0].normalized_id == "jira:MAPS-1842"
    assert candidates[1].normalized_id == "jira:PLATFORM-928"


def test_returns_empty_list_when_no_entity_is_found() -> None:
    registry = create_default_entity_registry()

    candidates = registry.identify(
        text="The deployment is still blocked.",
        source=Source.SLACK,
        artifact_id="artifact:slack:thread:123",
    )

    assert candidates == []


def test_identifies_github_pr() -> None:
    registry = create_default_entity_registry()

    candidates = registry.identify(
        text="Fix is being implemented in PR #829.",
        source=Source.JIRA,
        artifact_id="artifact:jira:PAY-1842",
    )

    assert len(candidates) == 1

    candidate = candidates[0]

    assert candidate.mention == "PR #829"
    assert candidate.entity_type == EntityType.GITHUB_PR
    assert candidate.normalized_id is None
    assert candidate.confidence == 0.90


def test_identifies_jira_ticket_and_github_pr() -> None:
    registry = create_default_entity_registry()

    candidates = registry.identify(
        text="PAY-1842 is fixed by PR #829.",
        source=Source.SLACK,
        artifact_id="artifact:slack:thread:123",
    )

    assert len(candidates) == 2

    assert candidates[0].normalized_id == "jira:PAY-1842"
    assert candidates[1].normalized_id is None


@pytest.mark.parametrize("mention", ["PR #829", "pr 829", "PR829", "PR #0829"])
def test_scopes_github_pr_to_artifact_repository(mention: str) -> None:
    candidates = create_default_entity_registry().identify(
        text=f"Follow up on {mention}.",
        source=Source.GITHUB,
        artifact_id="artifact:github:acme/payments-api:pr:100",
        repository="acme/payments-api",
    )

    assert len(candidates) == 1
    assert candidates[0].normalized_id == "github:acme/payments-api:pr:829"


@pytest.mark.parametrize("repository", [None, "payments-api", "", "acme/repo/extra"])
def test_missing_or_invalid_repository_keeps_github_pr_unresolved(
    repository: str | None,
) -> None:
    candidates = create_default_entity_registry().identify(
        text="See PR #829.",
        source=Source.GITHUB,
        artifact_id="artifact:github:unknown",
        repository=repository,
    )

    assert candidates[0].normalized_id is None


def test_jira_repository_metadata_does_not_infer_pr_repository() -> None:
    candidates = create_default_entity_registry().identify(
        text="See PR #829.",
        source=Source.JIRA,
        artifact_id="artifact:jira:PAY-1842",
        repository="acme/payments-api",
    )

    assert candidates[0].normalized_id is None


@pytest.mark.parametrize("source", [Source.JIRA, Source.GITHUB])
def test_explicit_pr_url_uses_its_own_repository(source: Source) -> None:
    url = "https://github.com/other/other-repo/pull/829"
    candidates = create_default_entity_registry().identify(
        text=f"Implemented by {url}.",
        source=source,
        artifact_id="artifact:test",
        repository="acme/payments-api",
    )

    assert len(candidates) == 1
    assert candidates[0].mention == url
    assert candidates[0].normalized_id == "github:other/other-repo:pr:829"


def test_pr_normalization_without_context_retains_temporary_id_compatibility() -> None:
    assert normalize_github_pr("PR #829") == "github:pr:829"
