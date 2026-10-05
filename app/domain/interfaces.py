from collections.abc import Sequence
from typing import Any, Protocol

from app.domain.models import (
    CanonicalArtifact,
    Entity,
    Event,
    Evidence,
    Relationship,
)


class ArtifactRepository(Protocol):
    """Persistence contract for canonical artifacts."""

    def get(self, artifact_id: str) -> CanonicalArtifact | None:
        ...

    def save(self, artifact: CanonicalArtifact) -> None:
        ...


class EntityRepository(Protocol):
    """Persistence contract for canonical entities."""

    def get(self, entity_id: str) -> Entity | None:
        ...

    def save(self, entity: Entity) -> None:
        ...


class EvidenceRepository(Protocol):
    """Persistence contract for evidence."""

    def get(self, evidence_id: str) -> Evidence | None:
        ...

    def save(self, evidence: Evidence) -> None:
        ...

    def get_for_entities(
        self,
        entity_ids: Sequence[str],
    ) -> list[Evidence]:
        ...


class EventRepository(Protocol):
    """Persistence contract for events."""

    def save(self, event: Event) -> None:
        ...

    def get_for_entity(self, entity_id: str) -> list[Event]:
        ...


class GraphRepository(Protocol):
    """Persistence and traversal contract for the entity graph."""

    def save_relationship(self, relationship: Relationship) -> None:
        ...

    def get_neighbors(
        self,
        entity_id: str,
    ) -> list[Entity]:
        ...


class VectorSearchResult(Protocol):
    """Minimum contract expected from a vector-search result."""

    @property
    def artifact_id(self) -> str:
        ...

    @property
    def evidence_id(self) -> str | None:
        ...

    @property
    def score(self) -> float:
        ...


class VectorStore(Protocol):
    """Semantic retrieval contract."""

    def add(
        self,
        *,
        text: str,
        artifact_id: str,
        evidence_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        ...

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> Sequence[VectorSearchResult]:
        ...


class RawStorage(Protocol):
    """Storage contract for raw source payloads."""

    def put(
        self,
        path: str,
        content: bytes,
    ) -> None:
        ...

    def get(self, path: str) -> bytes:
        ...