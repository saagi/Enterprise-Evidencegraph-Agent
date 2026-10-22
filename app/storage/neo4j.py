
from collections.abc import Iterator
from contextlib import contextmanager

from neo4j import Driver, GraphDatabase, Session


class Neo4jDatabase:
    """Manages Neo4j connections and database sessions."""

    def __init__(
        self,
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j",
    ) -> None:
        if not uri.startswith(("bolt://", "neo4j://")):
            raise ValueError(
                "Expected a bolt:// or neo4j:// URI"
            )

        self._database = database

        self._driver: Driver = GraphDatabase.driver(
            uri,
            auth=(username, password),
        )

    @property
    def driver(self) -> Driver:
        return self._driver

    def verify_connectivity(self) -> None:
        """Verify the database is reachable."""
        self._driver.verify_connectivity()

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Provide a short-lived Neo4j session."""
        with self._driver.session(
            database=self._database
        ) as session:
            yield session

    def dispose(self) -> None:
        """Release pooled database connections."""
        self._driver.close()
