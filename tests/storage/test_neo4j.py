
from unittest.mock import MagicMock, patch

import pytest

from app.storage.neo4j import Neo4jDatabase


def test_rejects_invalid_uri():
    with pytest.raises(ValueError):
        Neo4jDatabase(
            uri="http://localhost:7474",
            username="neo4j",
            password="test",
        )


@patch("app.storage.neo4j.GraphDatabase.driver")
def test_initializes_driver(mock_driver):
    db = Neo4jDatabase(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="test",
    )

    mock_driver.assert_called_once_with(
        "bolt://localhost:7687",
        auth=("neo4j", "test"),
    )

    assert db.driver is mock_driver.return_value


@patch("app.storage.neo4j.GraphDatabase.driver")
def test_verify_connectivity(mock_driver):
    db = Neo4jDatabase(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="test",
    )

    db.verify_connectivity()

    mock_driver.return_value.verify_connectivity.assert_called_once()


@patch("app.storage.neo4j.GraphDatabase.driver")
def test_session_lifecycle(mock_driver):
    mock_session = MagicMock()
    mock_driver.return_value.session.return_value.__enter__.return_value = (
        mock_session
    )

    db = Neo4jDatabase(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="test",
    )

    with db.session() as session:
        assert session is mock_session

    mock_driver.return_value.session.assert_called_once_with(
        database="neo4j"
    )
    mock_driver.return_value.session.return_value.__exit__.assert_called_once()


@patch("app.storage.neo4j.GraphDatabase.driver")
def test_dispose(mock_driver):
    db = Neo4jDatabase(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="test",
    )

    db.dispose()

    mock_driver.return_value.close.assert_called_once()
