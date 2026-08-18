# ADR 0001: PostgreSQL and pgvector for Knowledge Retrieval

- Status: Accepted
- Date: 2026-08-18

## Context

SupportPilot already uses PostgreSQL as its tenant-scoped transactional store
and ships pgvector. Phase 4 needs atomic document/index state, direct workspace
filtering, cosine nearest-neighbour search, and citation provenance. It does
not yet have evidence that operational scale requires a separate vector
service.

## Decision

Store 256-dimension chunk embeddings in a pgvector `VectorField`. Query with
cosine distance after applying workspace and document/source lifecycle
predicates in SQL. Use an HNSW `vector_cosine_ops` index and retain ordinary
relational indexes for tenant/status/filter paths.

## Consequences

Benefits:

- tenant ownership, vectors, document state, and provenance share one
  transactional boundary;
- foreign-workspace vectors can be excluded in the database query itself;
- backup, migration, observability, and local development reuse PostgreSQL;
- later agent code depends on a retrieval service rather than vector-store
  vendor details.

Trade-offs:

- changing vector dimension requires a migration and re-index;
- HNSW consumes additional storage and its tuning must be revisited using real
  workload evidence;
- a dedicated vector database may eventually offer operational features or
  scale characteristics PostgreSQL does not, but it would also add a second
  consistency and tenancy boundary.

We will reconsider this decision only with measured workload or operational
requirements, not speculative scale claims.
