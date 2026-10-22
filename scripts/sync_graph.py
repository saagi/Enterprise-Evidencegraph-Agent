"""Replay PostgreSQL entities and relationships into the Neo4j projection."""

import os

from dotenv import dotenv_values

from app.storage.graph_projection import PostgresGraphProjection
from app.storage.neo4j import Neo4jDatabase
from app.storage.neo4j_repositories import Neo4jEntityRepository, Neo4jGraphRepository
from app.storage.postgres import PostgresDatabase


def main() -> None:
    local_env = dotenv_values(".env")

    def setting(name: str, default: str = "") -> str:
        return os.getenv(name) or local_env.get(name) or default

    password = setting("NEO4J_PASSWORD")
    if not password:
        raise ValueError("NEO4J_PASSWORD is required")
    postgres = PostgresDatabase(
        setting(
            "DATABASE_URL",
            "postgresql+psycopg://evidencegraph:evidencegraph@127.0.0.1:5432/evidencegraph",
        )
    )
    try:
        neo4j = Neo4jDatabase(
            uri=setting("NEO4J_URI", "bolt://127.0.0.1:7687"),
            username=setting("NEO4J_USERNAME", "neo4j"),
            password=password,
            database=setting("NEO4J_DATABASE", "neo4j"),
        )
        try:
            neo4j.verify_connectivity()
            graph = Neo4jGraphRepository(neo4j)
            graph.ensure_schema()
            PostgresGraphProjection(postgres, Neo4jEntityRepository(neo4j), graph).replay()
            print("Graph replay completed")
        finally:
            neo4j.dispose()
    finally:
        postgres.dispose()


if __name__ == "__main__":
    main()
