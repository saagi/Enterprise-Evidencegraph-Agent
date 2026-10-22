"""Create the additive relationships table; existing tables are left unchanged."""

import os
from typing import cast

from dotenv import dotenv_values
from sqlalchemy import Table

from app.storage.postgres import PostgresDatabase
from app.storage.schema import RelationshipRow


def main() -> None:
    local_env = dotenv_values(".env")
    database = PostgresDatabase(
        os.getenv("DATABASE_URL")
        or local_env.get("DATABASE_URL")
        or "postgresql+psycopg://evidencegraph:evidencegraph@127.0.0.1:5432/evidencegraph"
    )
    try:
        cast(Table, RelationshipRow.__table__).create(database.engine, checkfirst=True)
        print("Relationship storage initialized")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
