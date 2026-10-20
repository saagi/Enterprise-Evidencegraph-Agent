
import os
import time
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text

from app.domain.models import Entity, EntityType, Source
from app.storage.postgres import PostgresDatabase
from app.storage.repositories import PostgresEntityRepository


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://evidencegraph:evidencegraph@127.0.0.1:5432/evidencegraph",
)


def measure(label, operation):
    start = time.perf_counter()

    try:
        result = operation()
        elapsed = time.perf_counter() - start
        print(f"{label:<28}: {elapsed:.3f}s", flush=True)
        return result
    except Exception:
        elapsed = time.perf_counter() - start
        print(f"{label:<28}: FAILED after {elapsed:.3f}s", flush=True)
        raise


def main():
    print("\n=== PostgreSQL Performance Diagnostics ===\n", flush=True)
    print(f"Database host: {DATABASE_URL.split('@')[-1]}", flush=True)

    db = measure(
        "Create SQLAlchemy engine",
        lambda: PostgresDatabase(DATABASE_URL),
    )

    entity_id = f"jira:PROFILE-{uuid4().hex[:12]}"
    now = datetime.now(UTC)

    entity = Entity(
        id=entity_id,
        type=EntityType.JIRA_TICKET,
        name="Performance diagnostic",
        source=Source.JIRA,
        source_id=entity_id.removeprefix("jira:"),
        created_at=now,
        updated_at=now,
        metadata={"diagnostic": True},
    )

    repo = PostgresEntityRepository(db)

    try:
        connection = measure(
            "Establish DB connection",
            lambda: db.engine.connect(),
        )

        try:
            measure(
                "Raw SELECT 1",
                lambda: connection.execute(text("SELECT 1")).scalar(),
            )
        finally:
            connection.close()

        measure(
            "Repository first upsert",
            lambda: repo.upsert(entity),
        )

        stored = measure(
            "Repository first read",
            lambda: repo.get_entity(entity_id),
        )

        assert stored is not None

        updated = entity.model_copy(
            update={"name": "Updated performance diagnostic"}
        )

        measure(
            "Repository second upsert",
            lambda: repo.upsert(updated),
        )

        stored = measure(
            "Repository second read",
            lambda: repo.get_entity(entity_id),
        )

        assert stored is not None
        assert stored.name == "Updated performance diagnostic"

    finally:
        def cleanup():
            with db.session() as session:
                session.execute(
                    text("DELETE FROM entities WHERE id = :entity_id"),
                    {"entity_id": entity_id},
                )

        try:
            measure("Cleanup", cleanup)
        finally:
            measure("Dispose engine", db.dispose)

    print("\nDiagnostics completed successfully.", flush=True)


if __name__ == "__main__":
    main()
