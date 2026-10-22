# Graph persistence and recovery

PostgreSQL owns canonical entities and relationships. Neo4j is a rebuildable
projection. PostgreSQL and Neo4j do not share an atomic transaction.

## Initialize and replay

From the repository root, using the project's Python environment:

```bash
./venv/python.exe -m scripts.init_relationship_storage
./venv/python.exe -m scripts.sync_graph
```

The first command creates only the additive `relationships` table if absent;
existing tables are not altered. This is a development bootstrap, not a general
schema migration framework. The second initializes graph constraints and replays
all canonical entities followed by relationships.

Scripts read `DATABASE_URL`, `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, and
`NEO4J_DATABASE` from the environment, falling back to the local `.env`.
Environment values take precedence. Local database defaults are used except
for `NEO4J_PASSWORD`, which is required. Credentials are never printed.

## Connect projection to ingestion

Construct the repositories with existing database managers, then provide the
projection to the existing persistence service:

```python
from app.ingestion.persistence import PostgresPersistenceService
from app.storage.graph_projection import PostgresGraphProjection
from app.storage.neo4j_repositories import Neo4jEntityRepository, Neo4jGraphRepository

graph = Neo4jGraphRepository(neo4j_database)
graph.ensure_schema()
projection = PostgresGraphProjection(
    postgres_database,
    Neo4jEntityRepository(neo4j_database),
    graph,
)
persistence = PostgresPersistenceService(
    postgres_database,
    graph_projection=projection,
)
```

Pass `persistence` to `IngestionOrchestrator` as before. Omitting
`graph_projection` retains PostgreSQL-only ingestion. Schema initialization
remains explicit; constructors do not create constraints.

## Commit and recovery behavior

Ingestion atomically persists the artifact, entities, evidence, events, and
validated relationships in PostgreSQL. An invalid endpoint, identity conflict,
or other PostgreSQL failure rolls back this transaction and prevents projection.

After commit, projection reads canonical PostgreSQL rows rather than the
in-memory processing result. This preserves PostgreSQL's creation timestamps.
One SQL statement captures a consistent snapshot of both record sets. All rows
are validated before any graph writes. Entity nodes are written before edges.

If Neo4j fails after PostgreSQL commits, ingestion raises `GraphProjectionError`.
The error explicitly means the canonical ingestion succeeded and the graph may
be incomplete. Run `scripts.sync_graph` to recover, or call `projection.replay()`.
Replay can also repair a graph after a process exits between the two stores.
Repeated replay updates existing IDs without duplicating nodes or edges.

Cooperating replay workers use a PostgreSQL transaction advisory lock. Each
worker captures its snapshot after acquiring the lock, so a waiting worker sees
commits that arrived during the preceding replay. Direct graph repository writes
do not participate in this full-replay lock.

## Identity and traversal

- PostgreSQL relationship IDs use `Text`, with endpoint foreign keys and
  database checks for confidence and supported relationship types.
- A relationship ID cannot change endpoints or type; updates may refresh
  confidence, provenance, observation time, and metadata. PostgreSQL preserves
  its original creation time.
- Neo4j `:Entity` nodes share canonical PostgreSQL IDs.
- Typed directed edges preserve relationship IDs, confidence, timestamps, and
  JSON-encoded provenance/metadata. Missing endpoints are rejected transactionally.
- Unique `:RelationshipIdentity` helper nodes serialize writes to the same edge
  ID across types. They are operational projection records, not domain entities.
- `get_neighbors()` returns distinct, ID-sorted, one-hop neighbors in either
  direction; it excludes the queried entity itself and isolated helper nodes.

## PR resolution

`PR #829` inside a GitHub artifact uses that artifact's valid repository metadata.
Explicit `https://github.com/owner/repository/pull/829` references identify a PR
directly in either Jira or GitHub artifacts. The referenced canonical entity must
already exist in PostgreSQL for resolution and validated relationship creation.

An unscoped Jira PR number stays unresolved even when only one currently stored
PR happens to match it. No Jira-to-repository mapping is inferred. Repository
spelling follows the existing connector identity conventions.

## Current limits

Full replay materializes all records and holds a PostgreSQL transaction/lock
while graph writes run. It is suitable for the current local vertical slice;
incremental outbox delivery and a background retry worker remain future work.
Projection is eventually consistent and upsert-only: deleted canonical rows are
not removed from Neo4j. Commits after a replay snapshot appear on a later replay.
There is no source-version guard against older payloads overwriting newer
canonical state, nor persistent storage for unresolved relationship candidates.

## Validation

```bash
./venv/python.exe -m pytest -q -p no:cacheprovider
```

Live integration tests cover constraint enforcement, atomic rollback, replay
recovery, canonical timestamps, concurrent writes/replays, one-hop traversal,
and a Jira PR URL flowing through ingestion into both stores. Test data uses
unique IDs and scoped cleanup. Missing Neo4j credentials skip graph integration
cases; with credentials configured, connection or authentication failures fail.
