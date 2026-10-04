from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    """Base model for all domain objects."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class EntityType(StrEnum):
    JIRA_TICKET = "jira_ticket"
    SLACK_THREAD = "slack_thread"
    GITHUB_PR = "github_pr"
    DOCUMENT = "document"
    PROJECT = "project"


class RelationshipType(StrEnum):
    BELONGS_TO = "belongs_to"
    DISCUSSED_IN = "discussed_in"
    IMPLEMENTED_BY = "implemented_by"
    RELATED_TO = "related_to"
    REFERENCES = "references"
    MENTIONS = "mentions"


class EventType(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    STATUS_CHANGED = "status_changed"
    COMMENT_ADDED = "comment_added"
    OPENED = "opened"
    CLOSED = "closed"
    MERGED = "merged"
    REVERTED = "reverted"
    DEPLOYMENT_REPORTED = "deployment_reported"
    DECISION_MADE = "decision_made"
    BLOCKER_REPORTED = "blocker_reported"


class EvidenceType(StrEnum):
    STATUS_UPDATE = "status_update"
    COMMENT = "comment"
    PR_CHANGE = "pr_change"
    DEPLOYMENT_REPORT = "deployment_report"
    DECISION = "decision"
    BLOCKER = "blocker"
    DOCUMENTATION = "documentation"
    POLICY = "policy"
    DISCUSSION = "discussion"


class Source(StrEnum):
    JIRA = "jira"
    SLACK = "slack"
    GITHUB = "github"
    DOCUMENT = "document"


class Entity(DomainModel):
    id: str
    type: EntityType
    name: str
    source: Source
    source_id: str

    created_at: datetime
    updated_at: datetime

    metadata: dict[str, Any] = Field(default_factory=dict)


class Relationship(DomainModel):
    id: str

    source_entity_id: str
    relationship_type: RelationshipType
    target_entity_id: str

    confidence: float = Field(ge=0.0, le=1.0)
    provenance: dict[str, Any]

    observed_at: datetime
    created_at: datetime

    metadata: dict[str, Any] = Field(default_factory=dict)


class Event(DomainModel):
    id: str
    entity_id: str

    event_type: EventType
    timestamp: datetime

    source: Source
    source_id: str

    data: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)

    evidence_id: str | None = None

    created_at: datetime


class EvidenceLocation(DomainModel):
    """Location of evidence within its source."""

    artifact_id: str | None = None

    page: int | None = Field(default=None, ge=1)
    section: str | None = None

    message_id: str | None = None
    thread_id: str | None = None

    url: str | None = None


class Evidence(DomainModel):
    id: str

    entity_ids: list[str]

    source: Source
    source_id: str
    evidence_type: EvidenceType

    claim: str
    content: str

    timestamp: datetime | None = None

    location: EvidenceLocation | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime


class CanonicalArtifact(DomainModel):
    id: str

    source: Source
    source_id: str
    artifact_type: str

    title: str | None = None
    content: dict[str, Any]

    metadata: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime
    updated_at: datetime