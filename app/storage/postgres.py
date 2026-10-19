
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


class PostgresDatabase:
    """Manages PostgreSQL connections and database sessions."""

    def __init__(
        self,
        database_url: str,
        echo: bool = False,
    ) -> None:
        if not database_url.startswith(
            "postgresql+psycopg://"
        ):
            raise ValueError(
                "Expected a PostgreSQL URL using the psycopg driver"
            )

        self._engine: Engine = create_engine(
            database_url,
            echo=echo,
            pool_pre_ping=True,
        )

        self._session_factory = sessionmaker(
            bind=self._engine,
            autoflush=False,
            expire_on_commit=False,
        )

    @property
    def engine(self) -> Engine:
        return self._engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Commit successful transactions and roll back failures."""

        db_session = self._session_factory()

        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise
        finally:
            db_session.close()

    def dispose(self) -> None:
        """Release pooled database connections."""
        self._engine.dispose()
