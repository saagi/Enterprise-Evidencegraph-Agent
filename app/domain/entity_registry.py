import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.domain.models import EntityType, Source
from app.domain.services import EntityCandidate


@dataclass(frozen=True)
class EntityPattern:
    """Rule for identifying an entity mention in text."""

    entity_type: EntityType
    pattern: re.Pattern[str]
    normalize: Callable[[str], str]
    confidence: float


class EntityIdentificationRegistry:
    """Identifies potential entity references using deterministic rules."""

    def __init__(self, patterns: list[EntityPattern]) -> None:
        self._patterns = patterns

    def identify(
        self,
        *,
        text: str,
        source: Source,
        artifact_id: str,
        repository: str | None = None,
    ) -> list[EntityCandidate]:
        candidates: list[EntityCandidate] = []

        for entity_pattern in self._patterns:
            for match in entity_pattern.pattern.finditer(text):
                mention = match.group(0)
                normalized_id: str | None = entity_pattern.normalize(mention)
                if (
                    entity_pattern.entity_type == EntityType.GITHUB_PR
                    and normalized_id is not None
                    and normalized_id.startswith("github:pr:")
                ):
                    # A PR number has no canonical identity without its repository.
                    normalized_id = (
                        normalize_github_pr(mention, repository=repository)
                        if source == Source.GITHUB
                        else None
                    )
                    if normalized_id is not None and normalized_id.startswith("github:pr:"):
                        normalized_id = None

                candidates.append(
                    EntityCandidate(
                        mention=mention,
                        entity_type=entity_pattern.entity_type,
                        normalized_id=normalized_id,
                        source=source,
                        artifact_id=artifact_id,
                        confidence=entity_pattern.confidence,
                        context=text,
                    )
                )

        return candidates


def normalize_jira_ticket(mention: str) -> str:
    """Convert a Jira ticket mention into its canonical entity ID."""

    ticket_id = mention.upper()

    return f"jira:{ticket_id}"


def create_default_entity_registry() -> EntityIdentificationRegistry:
    """Create the default deterministic entity identification registry."""

    jira_pattern = EntityPattern(
        entity_type=EntityType.JIRA_TICKET,
        pattern=re.compile(
            r"\b[A-Z][A-Z0-9_]*-\d+\b",
            re.IGNORECASE,
        ),
        normalize=normalize_jira_ticket,
        confidence=0.99,
    )

    github_pr_pattern = EntityPattern(
        entity_type=EntityType.GITHUB_PR,
        pattern=re.compile(
            r"\bPR\s*#?\s*\d+\b",
            re.IGNORECASE,
        ),
        normalize=normalize_github_pr,
        confidence=0.90,
    )

    github_pr_url_pattern = EntityPattern(
        entity_type=EntityType.GITHUB_PR,
        pattern=re.compile(
            r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9]\d*\b",
            re.IGNORECASE,
        ),
        normalize=normalize_github_pr_url,
        confidence=0.99,
    )

    return EntityIdentificationRegistry(
        patterns=[
            jira_pattern,
            github_pr_pattern,
            github_pr_url_pattern,
        ]
    )


def normalize_github_pr(mention: str, *, repository: str | None = None) -> str:
    """Normalize a PR mention, scoping its number when context is available."""

    match = re.search(r"\d+", mention)

    if match is None:
        raise ValueError(f"Invalid GitHub PR mention: {mention}")

    number = int(match.group(0))
    if repository is not None and re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
    ):
        return f"github:{repository}:pr:{number}"
    return f"github:pr:{number}"


def normalize_github_pr_url(mention: str) -> str:
    """Preserve explicit repository identity independently of artifact context."""
    owner, repository, _, number = urlsplit(mention).path.strip("/").split("/")
    return f"github:{owner}/{repository}:pr:{int(number)}"
