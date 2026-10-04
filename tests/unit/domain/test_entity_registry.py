from app.domain.entity_registry import create_default_entity_registry
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