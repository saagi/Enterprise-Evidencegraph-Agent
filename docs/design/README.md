# Design decisions and tradeoffs

Design records describe agreed behavior, why it was chosen, alternatives, and
its costs. They are not evidence that a feature is implemented. The repository
remains authoritative for actual behavior.

## Records

| Area | Record | Status |
| --- | --- | --- |
| Embeddings and vector indexing | [Embedding layer](EMBEDDING_LAYER.md) | First adapter/tokenizer increment implemented; live compatibility and indexing pipeline pending |
| Graph persistence and recovery | [Graph persistence](../GRAPH_PERSISTENCE.md) | Implemented; operational behavior and limitations documented |

## Maintenance rules

1. Read the relevant design record before changing the affected behavior.
2. Record new decisions and their tradeoffs before implementation. Follow the
   user's current authorization; documenting a decision does not authorize code
   or schema changes by itself.
3. When a decision changes, update its current description, rationale,
   alternatives, consequences, and validation needs. Add a dated change-history
   entry explaining what changed and why. Do not silently erase prior choices.
4. Distinguish user-agreed decisions from proposals, implementation details, and
   assumptions awaiting verification. Do not choose a fallback silently.
5. When implementation completes, update implementation status and link the
   relevant code/tests. Update PROJECT_CONTEXT.md when the milestone changes.
6. If code contradicts a design record, report the discrepancy first. Do not
   rewrite documentation to hide it or claim planned behavior is implemented.
7. Ask for the user's preference before recommending a choice unless the user
   has requested a recommendation or authorized autonomous decisions for that work.

## Format for future records

Use a focused Markdown file for each subsystem or significant design topic.
Use structured tables for decisions and their tradeoffs. Prefer a compact
two-column table per decision so detailed tradeoffs remain readable without an
extremely wide table.

| Record component | Required contents |
| --- | --- |
| Overview | Status, last-updated date, scope, and current implementation boundary |
| Decision | Stable decision ID and chosen behavior |
| Rationale | Why the choice fits the project |
| Alternatives | Other options considered and their differences |
| Tradeoffs | Costs, limitations, risks, and consequences of the choice |
| Verification | Dependencies, unresolved assumptions, and validation requirements |
| Change history | Dated changes with reasons; preserve superseded choices when relevant |

Do not store credentials, real source content, or raw sensitive API responses
in design records.
