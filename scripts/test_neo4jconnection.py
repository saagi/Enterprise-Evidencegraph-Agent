
import os

from app.storage.neo4j import Neo4jDatabase


db = Neo4jDatabase(
    uri="bolt://127.0.0.1:7687",
    username="neo4j",
    password=os.environ["NEO4J_PASSWORD"],
)

try:
    db.verify_connectivity()

    with db.session() as session:
        record = session.run(
            "RETURN 1 AS connection_test"
        ).single()

        print("Neo4j connected successfully")
        print("Result:", record["connection_test"])
finally:
    db.dispose()
