# Knowledge Ingestion and Vector Retrieval

Phase 4 adds a production-oriented knowledge foundation. It ends at ranked,
cited retrieval; it does not call an LLM, generate answers, execute tools, or
implement an agent runtime.

## Domain and lifecycle

```text
Workspace
  `-- KnowledgeSource
        `-- KnowledgeDocument (immutable uploaded file)
              |-- KnowledgeIngestionJob
              `-- KnowledgeChunk (text + vector + locator)

semantic search
  `-- RetrievalEvent
        `-- RetrievalHit (rank + score + citation snapshot)
```

`KnowledgeSource` is a logical collection. Phase 4 deliberately supports only
`upload` and `manual` source types; connected providers are deferred. Sources
are deactivated rather than deleted.

An upload atomically creates a `queued` document and ingestion job, then uses
`transaction.on_commit` to dispatch Celery. The lifecycle is:

```text
pending -> queued -> processing -> ready
                          `-------> failed
failed  -> queued (explicit retry)
```

The binary is not replaceable through PATCH. A new file creates a new
document. Only failed documents may use the explicit retry route.

## Upload and extraction security

The accepted formats are UTF-8 `.txt`, `.md`/`.markdown`, and text-based
`.pdf`. The default maximum is 10 MiB and PDFs are limited to 100 pages. Both
limits are settings-driven. Validation checks non-empty content, a safe flat
filename, extension/MIME agreement, common executable/archive signatures,
NUL bytes in text, the PDF signature, PDF structure, encryption, and page
count. Storage names are opaque UUID-derived paths created through Django's
storage abstraction; APIs never expose the storage path.

Extraction is behind a typed `TextExtractor` contract. Plain text and Markdown
use strict UTF-8 decoding. PDF extraction uses pinned `pypdf 6.15.0` and retains page
locators. Parser exceptions map to stable safe codes; full file contents,
chunks, and queries are not written to application logs. Extracted text is
untrusted product data—prompt-looking instructions remain inert text.

Normalization performs NFC Unicode normalization, line-ending normalization,
trailing-whitespace cleanup, NUL removal, and excessive-blank-line collapse.
It does not summarize, translate, paraphrase, or strip meaningful punctuation.
PDF OCR is intentionally unsupported; image-only documents fail with
`knowledge_no_extractable_text`.

## Chunking and embeddings

The `paragraph-char-v1` chunker prefers paragraph, line, then word boundaries,
with a bounded hard split for pathological input. Defaults are 1,200
characters, 150-character overlap, and 20 minimum useful characters. Settings
startup validation enforces `0 <= overlap < chunk_size`. Each chunk has a
stable ordinal, character offsets, and optional page range.

The default provider is offline `supportpilot-deterministic` model
`hashed-token-projection-v1`. It tokenizes case-insensitively, projects each
token into a SHA-256-derived signed bag-of-words vector, and L2-normalizes the
result. This makes builds reproducible across processes while preserving
enough lexical similarity for meaningful integration tests. No key, network,
paid API, or model download is required.

The persisted vector dimension is 256. Provider output is rejected unless the
batch count and every dimension match exactly and every value is numeric and
finite. Provider/model, dimension, extractor version, and chunker version are
stored on the successful ingestion job. Changing dimension is a schema and
re-indexing event.

## Atomicity, retry, and idempotency

Extraction, chunking, and embedding run outside a long transaction. Only
after the complete batch validates does a short atomic finalization replace
chunks, update counts, mark the document ready, and mark the job succeeded.
No partial index can be advertised as ready.

The job row is locked for state transitions. A succeeded delivery is a no-op;
a concurrent second delivery observes `processing` and does no duplicate work.
Transient storage/provider failures requeue with bounded exponential Celery
retry (three attempts by default). Malformed/encrypted PDFs, empty extracted
text, invalid configuration, and invalid vectors are permanent failures.
Persisted errors contain only stable codes and safe messages.

## Retrieval and citations

Retrieval uses cosine distance in PostgreSQL and exposes similarity as
`score = 1 - cosine_distance`, where higher is better. The HNSW index uses
`vector_cosine_ops` (`m=16`, `ef_construction=64`). Default `top_k` is 5 and
the maximum is 20. An optional minimum score is bounded to `[0, 1]`.

The SQL queryset applies workspace, ready-document, active-document, and
active-source predicates before nearest-neighbour ordering. Optional source
and document IDs are first resolved within the current workspace. Ordering is
distance followed by document ID, ordinal, and chunk ID for deterministic
ties. The ORM-independent retrieval contract returns chunk text, score,
document/source identity, and a citation containing page range, character
offsets, and chunk ordinal.

`RetrievalEvent` persists the user query as sensitive product data and records
provider/model and retrieval parameters. `RetrievalHit` stores rank, score,
and the citation snapshot. These are retrieval provenance—not immutable admin
audit events.

## RBAC and tenant behavior

All active workspace roles may list, read, search, and inspect citations.
`owner`, `admin`, and `support_manager` may create/update sources, upload, and
retry failed ingestion. `support_agent` and `viewer` are read-only. Permissions
re-read the database membership on every request, so demotion takes effect
without refreshing the JWT.

Every foreign workspace, source, document, ingestion job, retrieval filter,
and retrieval event resolves as `404`. `KnowledgeChunk` carries an explicit
workspace foreign key in addition to its document relationship so the
security-critical vector predicate is direct and testable.

## API

Routes live below `/api/v1/workspaces/{workspace_id}/knowledge/`:

- `GET/POST sources/`, `GET/PATCH sources/{id}/`
- `GET/POST documents/`, `GET documents/{id}/`
- `POST documents/{id}/retry/`
- `GET ingestion-jobs/{id}/`
- `POST search/`
- `GET retrieval-events/{id}/`

Document upload is multipart. Server-owned workspace, status, hashes, counts,
errors, embeddings, attempt counts, and timestamps are never writable.

## Known limitations and phase boundary

- No OCR, archives, Office/HTML input, connected knowledge providers, or
  object-storage production adapter.
- The deterministic embedding provider is intended for local correctness and
  testing, not neural semantic quality.
- Search events retain raw queries as product data; future retention controls
  should follow the platform's data-governance policy.
- Phase 5 may consume `search_knowledge` and `RetrievedContext`; it must not
  query pgvector ORM expressions directly. No Phase 5 runtime exists here.
