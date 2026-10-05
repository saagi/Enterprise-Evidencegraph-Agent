from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from app.domain.models import CanonicalArtifact, Source


class SourceRecord(BaseModel):
    """Raw record retrieved from an external source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Source
    source_id: str
    payload: dict[str, Any]
    metadata: dict[str, Any]


class SourceConnector(Protocol):
    """Contract implemented by source-specific connectors."""

    def normalize(self, record: SourceRecord) -> CanonicalArtifact:
        ...


class JiraConnector:
    """Normalizes Jira source records into canonical artifacts."""

    def normalize(self, record: SourceRecord) -> CanonicalArtifact:
        if record.source != Source.JIRA:
            raise ValueError(
                f"JiraConnector cannot normalize source: {record.source}"
            )

        payload = record.payload
        fields = payload["fields"]

        created_at = datetime.fromisoformat(
            fields["created"].replace("Z", "+00:00")
        )

        updated_at = datetime.fromisoformat(
            fields["updated"].replace("Z", "+00:00")
        )

        content = {
            "summary": fields["summary"],
            "description": fields.get("description"),
            "status": fields["status"]["name"],
            "comments": fields.get("comments", []),
        }

        metadata = {
            "priority": fields.get("priority"),
            "project": fields.get("project"),
            "assignee": fields.get("assignee"),
            **record.metadata,
        }

        return CanonicalArtifact(
            id=f"artifact:jira:{record.source_id}",
            source=Source.JIRA,
            source_id=record.source_id,
            artifact_type="jira_ticket",
            title=fields["summary"],
            content=content,
            metadata=metadata,
            created_at=created_at,
            updated_at=updated_at,
        )